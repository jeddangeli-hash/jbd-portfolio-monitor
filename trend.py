"""Period performance ("Andamento") — pure logic behind the Home trend chart.

Two kinds of window:

* Intraday (1G, 2G): holdings are taken as they are now and valued on 15-minute
  bars; the return is value / value at the window's base bar − 1.
* Daily (1S … Inizio): the value series is rebuilt from transactions, so buys
  and sells inside the window are cash, not performance. The return at day t is
  (P&L earned since the base day) ÷ (value at the base day + net cash added
  since), which for "Inizio" reduces to the familiar total P&L ÷ net cash.
"""
from __future__ import annotations

import pandas as pd

PERIODS = ["1G", "2G", "1S", "1M", "6M", "YTD", "1A", "Inizio"]
PERIOD_LABELS = {"1G": "1G", "2G": "2G", "1S": "Settimana", "1M": "1M", "6M": "6M",
                 "YTD": "YTD", "1A": "1A", "Inizio": "Dall'inizio"}
INTRADAY = {"1G", "2G"}
LOCAL_TZ = "Europe/Rome"
BENCHMARK = "^GSPC"  # S&P 500 index


def daily_base(period: str, index: pd.DatetimeIndex) -> pd.Timestamp | None:
    """Index point whose close the window is measured from, or None = from inception.

    1S counts from the last close before this week's Monday, YTD from the last
    close of the previous year, 1M/6M/1A from the last close on or before the
    same date one month / six months / one year ago.
    """
    if len(index) == 0 or period == "Inizio":
        return None
    last = index[-1]
    if period in ("1G", "2G"):  # daily fallback when intraday data is missing
        k = 2 if period == "1G" else 3
        return index[-k] if len(index) >= k else None
    if period == "1S":
        cutoff, strict = last.normalize() - pd.Timedelta(days=last.weekday()), True
    elif period == "YTD":
        cutoff, strict = pd.Timestamp(year=last.year, month=1, day=1, tz=last.tz), True
    else:
        months = {"1M": 1, "6M": 6, "1A": 12}[period]
        cutoff, strict = last - pd.DateOffset(months=months), False
    before = index[index < cutoff] if strict else index[index <= cutoff]
    return before[-1] if len(before) else None


def period_curve(values: pd.Series, cashflows: pd.Series,
                 base: pd.Timestamp | None) -> pd.Series:
    """Simple return (fraction) through the window; first point is the base at 0."""
    if values.empty:
        return pd.Series(dtype=float)
    if base is None or base not in values.index:
        cum = cashflows.cumsum()
        r = (values - cum) / cum.where(cum > 1e-9)
        return r.dropna()
    v0 = float(values.loc[base])
    win = values.index > base
    cf_in = cashflows[win].cumsum()
    pnl = values[win] - v0 - cf_in
    capital = v0 + cf_in.clip(lower=0.0)
    r = pnl / capital.where(capital > 1e-9)
    return pd.concat([pd.Series([0.0], index=[base]), r]).dropna()


def intraday_window(bars: pd.DataFrame, period: str,
                    session_symbols: list[str] | None = None) -> pd.Timestamp | None:
    """Start of the 1G / 2G window on intraday bars (UTC index).

    Days are local (Europe/Rome) calendar days. 2G spans the last two days on
    which a non-24/7 symbol traded, so a weekend of crypto-only bars doesn't
    count as a session; with no such symbol every day counts.
    """
    if bars.empty:
        return None
    local = bars.index.tz_convert(LOCAL_TZ)
    cols = [c for c in (session_symbols or []) if c in bars.columns]
    traded = bars[cols].notna().any(axis=1).to_numpy() if cols else None
    days = sorted(set(local.normalize()[traded] if traded is not None and traded.any()
                      else local.normalize()))
    n = 1 if period == "1G" else 2
    start_day = days[-n] if len(days) >= n else days[0]
    latest = local.normalize().max()
    if n == 1:
        start_day = latest  # 1G is always "today" (latest local day with any bar)
    return start_day.tz_convert("UTC")


def intraday_curve(bars_eur: pd.DataFrame, qty: pd.Series,
                   start: pd.Timestamp) -> tuple[pd.Series, pd.Timestamp | None]:
    """Return of the current holdings over intraday bars from `start`.

    Bars are forward-filled so a symbol whose market is closed contributes flat.
    Returns (curve as fraction with the base point at 0, base timestamp).
    """
    cols = [c for c in bars_eur.columns if c in qty.index and qty[c] > 0]
    if not cols:
        return pd.Series(dtype=float), None
    filled = bars_eur[cols].ffill()
    value = (filled * qty[cols]).sum(axis=1, min_count=1).dropna()
    before = value[value.index < start]
    after = value[value.index >= start]
    if before.empty or after.empty:
        return pd.Series(dtype=float), None
    base_ts, v0 = before.index[-1], float(before.iloc[-1])
    if v0 <= 0:
        return pd.Series(dtype=float), None
    curve = pd.concat([pd.Series([0.0], index=[base_ts]), after / v0 - 1.0])
    return curve, base_ts


def symbol_period_return(prices: pd.Series, base: pd.Timestamp | None) -> float | None:
    """Price change of one symbol from the base point to its latest price."""
    p = prices.dropna()
    if p.empty or base is None:
        return None
    b = p[p.index <= base]
    if b.empty or not b.iloc[-1]:
        return None
    return float(p.iloc[-1] / b.iloc[-1] - 1.0)


def sparkline(prices: pd.Series, base: pd.Timestamp | None, points: int = 60) -> list[float]:
    """Window prices, thinned to at most `points` values, for a table sparkline."""
    p = prices.ffill().dropna()
    if base is not None:
        p = p[p.index >= base]
    if len(p) > points:
        step = len(p) / points
        p = p.iloc[[int(i * step) for i in range(points)] + [len(p) - 1]]
    return [round(float(x), 6) for x in p]


def benchmark_curve(prices: pd.Series, base: pd.Timestamp | None) -> pd.Series:
    """Price return of a benchmark from `base` (fraction, base point at 0).

    The base is the portfolio's own base point; when the benchmark has no
    print exactly there (weekend, other exchange's holiday) its last earlier
    price is used, or its first price if it starts later.
    """
    p = prices.ffill().dropna()
    if p.empty or base is None:
        return pd.Series(dtype=float)
    before = p[p.index <= base]
    p0 = float(before.iloc[-1]) if len(before) else float(p.iloc[0])
    if not p0:
        return pd.Series(dtype=float)
    after = p[p.index > base]
    return pd.concat([pd.Series([0.0], index=[base]), after / p0 - 1.0])
