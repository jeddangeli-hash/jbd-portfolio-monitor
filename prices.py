"""yfinance adapter — quotes, history, metadata, dividends. Single seam for swapping data sources."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import pandas as pd

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False


# Exchange suffixes quoted in EUR. Lets the batched path skip the per-symbol
# currency lookup for the common cases; anything not recognised falls back to it.
_EUR_SUFFIXES = (".MI", ".DE", ".F", ".SG", ".BE", ".DU", ".MU", ".HM", ".PA",
                 ".AS", ".MC", ".BR", ".LS", ".VI", ".HE", ".IR")
_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def guess_currency(symbol: str) -> str | None:
    """Quote currency from the ticker's shape, or None when it can't be told."""
    s = symbol.upper()
    if s.endswith("=X"):                      # FX pair, e.g. EURUSD=X → USD
        return s[3:6] if len(s) == 8 else None
    if "-" in s:                              # crypto pair, e.g. BTC-USD
        tail = s.rsplit("-", 1)[1]
        return tail if tail in ("USD", "EUR", "GBP") else None
    if s.endswith(_EUR_SUFFIXES):
        return "EUR"
    if "." not in s and not _ISIN.match(s):   # plain US ticker
        return "USD"
    return None


def _quote_one(sym: str) -> tuple[str, dict | None]:
    """Per-symbol fast_info lookup (slow path: one request per symbol)."""
    try:
        info = yf.Ticker(sym).fast_info
        price = float(info.get("last_price") or info.get("lastPrice") or 0) or None
        prev = float(info.get("previous_close") or info.get("previousClose") or 0) or None
        ccy = info.get("currency") or "USD"
        if price:
            return sym, {"price": price, "prev_close": prev or price, "currency": ccy}
    except Exception:
        pass
    return sym, None


def _closes_from_download(data: pd.DataFrame, symbols: list[str]) -> dict[str, pd.Series]:
    """Per-symbol Close series from a yf.download frame (either column layout)."""
    out: dict[str, pd.Series] = {}
    if data is None or data.empty:
        return out
    if isinstance(data.columns, pd.MultiIndex):
        lvl0 = set(data.columns.get_level_values(0))
        for sym in symbols:
            if sym in lvl0 and "Close" in data[sym].columns:
                out[sym] = data[sym]["Close"].dropna()
    elif "Close" in data.columns and len(symbols) == 1:
        out[symbols[0]] = data["Close"].dropna()
    return out


def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    """Last price, previous close and currency per symbol.

    Fast path: ONE batched daily download for every symbol whose currency can be
    told from the ticker. Whatever that misses (unknown currency, no data) goes
    through the per-symbol lookup, run in parallel.
    """
    if not HAS_YF or not symbols:
        return {}
    out: dict[str, dict] = {}
    batch = [s for s in symbols if guess_currency(s)]
    if batch:
        try:
            data = yf.download(tickers=" ".join(batch), period="5d", interval="1d",
                               auto_adjust=False, group_by="ticker", progress=False,
                               threads=True)
            for sym, closes in _closes_from_download(data, batch).items():
                if len(closes) == 0:
                    continue
                price = float(closes.iloc[-1])
                prev = float(closes.iloc[-2]) if len(closes) > 1 else price
                if price:
                    out[sym] = {"price": price, "prev_close": prev, "currency": guess_currency(sym)}
        except Exception:
            pass
    rest = [s for s in symbols if s not in out]
    if rest:
        with ThreadPoolExecutor(max_workers=min(16, len(rest))) as ex:
            for sym, q in ex.map(_quote_one, rest):
                if q:
                    out[sym] = q
    return out


@lru_cache(maxsize=256)
def fetch_metadata(symbol: str) -> dict:
    """Returns {'sector', 'industry', 'country', 'currency', 'quoteType', 'longName'} when available."""
    if not HAS_YF:
        return {}
    try:
        t = yf.Ticker(symbol)
        info = {}
        try:
            info = t.get_info() or {}
        except Exception:
            try:
                info = t.info or {}
            except Exception:
                info = {}
        return {
            "sector": info.get("sector") or "Unknown",
            "industry": info.get("industry") or "Unknown",
            "country": info.get("country") or "Unknown",
            "currency": info.get("currency") or "USD",
            "quoteType": info.get("quoteType") or "EQUITY",
            "longName": info.get("longName") or info.get("shortName") or symbol,
        }
    except Exception:
        return {}


def fetch_metadata_bulk(symbols: list[str]) -> pd.DataFrame:
    # One slow get_info() per symbol — run them in parallel.
    symbols = list(symbols)
    if not symbols:
        return pd.DataFrame(columns=["symbol"])
    with ThreadPoolExecutor(max_workers=min(16, len(symbols))) as ex:
        metas = list(ex.map(fetch_metadata, symbols))
    return pd.DataFrame([{"symbol": s, **m} for s, m in zip(symbols, metas)])


@lru_cache(maxsize=128)
def fetch_history(symbol: str, period: str = "6mo") -> pd.DataFrame:
    if not HAS_YF:
        return pd.DataFrame()
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period=period, auto_adjust=True)
        return hist[["Close"]].rename(columns={"Close": "close"})
    except Exception:
        return pd.DataFrame()


def fetch_history_bulk(symbols: list[str], period: str = "6mo") -> pd.DataFrame:
    if not HAS_YF or not symbols:
        return pd.DataFrame()
    try:
        data = yf.download(
            tickers=" ".join(symbols),
            period=period,
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=True,
        )
        if isinstance(data.columns, pd.MultiIndex):
            closes = pd.DataFrame({s: data[s]["Close"] for s in symbols if s in data.columns.get_level_values(0)})
        else:
            closes = data[["Close"]].rename(columns={"Close": symbols[0]})
        # Strip timezone info for clean date alignment
        if hasattr(closes.index, "tz") and closes.index.tz is not None:
            closes.index = closes.index.tz_localize(None)
        return closes.dropna(how="all")
    except Exception:
        return pd.DataFrame()


def fetch_intraday_bulk(symbols: list[str], period: str = "5d",
                        interval: str = "15m", prepost: bool = False) -> pd.DataFrame:
    """Intraday closes, one column per symbol, on a shared UTC index.

    ignore_tz=False keeps each exchange's timestamps tz-aware so US, EU and
    crypto bars line up once converted to UTC (the default would strip the
    zones and misalign them by hours).
    """
    if not HAS_YF or not symbols:
        return pd.DataFrame()
    try:
        data = yf.download(tickers=" ".join(symbols), period=period, interval=interval,
                           auto_adjust=True, group_by="ticker", progress=False,
                           threads=True, ignore_tz=False, prepost=prepost)
    except Exception:
        return pd.DataFrame()
    closes = _closes_from_download(data, list(symbols))
    if not closes:
        return pd.DataFrame()
    frame = pd.DataFrame(closes).sort_index()
    idx = pd.DatetimeIndex(frame.index)
    frame.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return frame


def fetch_earnings_dates(symbol: str) -> list[tuple[pd.Timestamp, bool]]:
    """Recent and upcoming earnings releases as (UTC timestamp, has_time).

    get_earnings_dates carries the release time (that is what tells pre-market
    from after-market); when it fails, the calendar's date-only entries are used
    with has_time=False.
    """
    if not HAS_YF:
        return []
    t = yf.Ticker(symbol)
    try:
        df = t.get_earnings_dates(limit=8)
        if df is not None and not df.empty:
            idx = pd.DatetimeIndex(df.index)
            idx = idx.tz_localize("America/New_York") if idx.tz is None else idx
            return [(ts, True) for ts in idx.tz_convert("UTC")]
    except Exception:
        pass
    try:
        cal = t.calendar or {}
        days = cal.get("Earnings Date") if isinstance(cal, dict) else None
        return [(pd.Timestamp(d).tz_localize("America/New_York").tz_convert("UTC"), False)
                for d in (days or [])]
    except Exception:
        return []


def fetch_earnings_bulk(symbols: list[str]) -> dict[str, list[tuple[pd.Timestamp, bool]]]:
    symbols = list(symbols)
    if not symbols:
        return {}
    with ThreadPoolExecutor(max_workers=min(16, len(symbols))) as ex:
        return dict(zip(symbols, ex.map(fetch_earnings_dates, symbols)))


@lru_cache(maxsize=128)
def fetch_dividends(symbol: str) -> pd.Series:
    """Returns Series of per-share dividend amounts, indexed by ex-date."""
    if not HAS_YF:
        return pd.Series(dtype=float)
    try:
        t = yf.Ticker(symbol)
        divs = t.dividends
        if hasattr(divs.index, "tz") and divs.index.tz is not None:
            divs.index = divs.index.tz_localize(None)
        return divs
    except Exception:
        return pd.Series(dtype=float)


@lru_cache(maxsize=256)
def fetch_key_stats(symbol: str) -> dict:
    """Trailing/forward P/E, analyst target price, recommendation, etc."""
    if not HAS_YF:
        return {}
    try:
        t = yf.Ticker(symbol)
        info = {}
        try:
            info = t.get_info() or {}
        except Exception:
            try:
                info = t.info or {}
            except Exception:
                info = {}

        # Next earnings date — try calendar first, then info timestamps
        next_earnings = None
        try:
            cal = t.calendar
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if ed:
                    next_earnings = ed[0] if isinstance(ed, (list, tuple)) else ed
            elif cal is not None and hasattr(cal, "index"):
                if "Earnings Date" in getattr(cal, "index", []):
                    row = cal.loc["Earnings Date"]
                    next_earnings = row.iloc[0] if hasattr(row, "iloc") else row
        except Exception:
            pass
        if next_earnings is None:
            ts = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
            if ts:
                try:
                    next_earnings = pd.Timestamp(ts, unit="s")
                except Exception:
                    next_earnings = None

        return {
            "next_earnings": next_earnings,
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio") or info.get("trailingPegRatio"),
            "target_mean": info.get("targetMeanPrice"),
            "target_high": info.get("targetHighPrice"),
            "target_low": info.get("targetLowPrice"),
            "recommendation_mean": info.get("recommendationMean"),
            "recommendation_key": info.get("recommendationKey"),
            "n_analysts": info.get("numberOfAnalystOpinions"),
            "currency": info.get("currency", "USD"),
            "market_cap": info.get("marketCap"),
            "long_name": info.get("longName") or info.get("shortName"),
            "summary": info.get("longBusinessSummary"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "country": info.get("country"),
            "website": info.get("website"),
            "employees": info.get("fullTimeEmployees"),
            "city": info.get("city"),
        }
    except Exception:
        return {}


def _extract_rev_ebitda(df: pd.DataFrame) -> pd.DataFrame:
    """Pulls Revenue, EBITDA and Net Income rows out of a yfinance income-statement DF."""
    if df is None or df.empty:
        return pd.DataFrame()
    rev_keys = ["Total Revenue", "TotalRevenue", "Revenue", "OperatingRevenue"]
    ebitda_keys = ["EBITDA", "Normalized EBITDA", "NormalizedEBITDA"]
    ni_keys = ["Net Income", "NetIncome", "Net Income Common Stockholders",
               "NetIncomeCommonStockholders", "Net Income From Continuing Operation Net Minority Interest"]
    out = pd.DataFrame(index=df.columns)
    for k in rev_keys:
        if k in df.index:
            out["revenue"] = df.loc[k]
            break
    for k in ebitda_keys:
        if k in df.index:
            out["ebitda"] = df.loc[k]
            break
    for k in ni_keys:
        if k in df.index:
            out["net_income"] = df.loc[k]
            break
    out = out.sort_index()
    if out.empty:
        return out
    return out.dropna(how="all")


@lru_cache(maxsize=128)
def fetch_annual_financials(symbol: str) -> pd.DataFrame:
    if not HAS_YF:
        return pd.DataFrame()
    try:
        t = yf.Ticker(symbol)
        df = None
        try:
            df = t.income_stmt
        except Exception:
            df = None
        if df is None or df.empty:
            try:
                df = t.financials
            except Exception:
                df = None
        return _extract_rev_ebitda(df)
    except Exception:
        return pd.DataFrame()


@lru_cache(maxsize=128)
def fetch_quarterly_financials(symbol: str) -> pd.DataFrame:
    if not HAS_YF:
        return pd.DataFrame()
    try:
        t = yf.Ticker(symbol)
        df = None
        try:
            df = t.quarterly_income_stmt
        except Exception:
            df = None
        if df is None or df.empty:
            try:
                df = t.quarterly_financials
            except Exception:
                df = None
        return _extract_rev_ebitda(df)
    except Exception:
        return pd.DataFrame()


def fetch_benchmark(symbol: str, period: str = "1y") -> pd.Series:
    h = fetch_history(symbol, period=period)
    if h.empty:
        return pd.Series(dtype=float)
    s = h["close"]
    if hasattr(s.index, "tz") and s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    return s
