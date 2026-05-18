"""yfinance adapter — quotes, history, metadata, dividends. Single seam for swapping data sources."""
from __future__ import annotations

from functools import lru_cache

import pandas as pd

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False


def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    if not HAS_YF or not symbols:
        return {}
    out: dict[str, dict] = {}
    try:
        tickers = yf.Tickers(" ".join(symbols))
        for sym in symbols:
            try:
                t = tickers.tickers.get(sym)
                if t is None:
                    continue
                info = t.fast_info
                price = float(info.get("last_price") or info.get("lastPrice") or 0) or None
                prev = float(info.get("previous_close") or info.get("previousClose") or 0) or None
                ccy = info.get("currency") or "USD"
                if price:
                    out[sym] = {"price": price, "prev_close": prev or price, "currency": ccy}
            except Exception:
                continue
    except Exception:
        pass
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
    rows = []
    for s in symbols:
        m = fetch_metadata(s)
        rows.append({"symbol": s, **m})
    return pd.DataFrame(rows)


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
        return {
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
    """Pulls Revenue and EBITDA rows out of a yfinance income-statement DF."""
    if df is None or df.empty:
        return pd.DataFrame()
    rev_keys = ["Total Revenue", "TotalRevenue", "Revenue", "OperatingRevenue"]
    ebitda_keys = ["EBITDA", "Normalized EBITDA", "NormalizedEBITDA"]
    out = pd.DataFrame(index=df.columns)
    for k in rev_keys:
        if k in df.index:
            out["revenue"] = df.loc[k]
            break
    for k in ebitda_keys:
        if k in df.index:
            out["ebitda"] = df.loc[k]
            break
    out = out.sort_index()
    # Drop rows where everything is NaN
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
