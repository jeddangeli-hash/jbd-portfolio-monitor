"""Performance & risk metrics: TWR, drawdown, volatility, Sharpe, period returns."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd


def build_value_series(tx: pd.DataFrame, hist: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Reconstruct daily portfolio value and net deposit (positive = $ into portfolio).

    hist: wide DF, datetime index, one column per symbol, close prices.
    tx:   transactions DF from portfolio.load_transactions.

    Returns (value_series, cashflow_series) aligned to hist.index.
    """
    if hist.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    # Forward-fill prices so NaN holes (delisted tickers, penny stocks, missing days)
    # don't collapse portfolio value to 0 and produce spurious -100% TWR days.
    hist = hist.ffill()

    symbols = list(hist.columns)
    qty: dict[str, float] = {s: 0.0 for s in symbols}

    tx_by_date: dict[date, list[dict]] = {}
    for _, r in tx.sort_values("trade_date").iterrows():
        d = r["trade_date"].date() if hasattr(r["trade_date"], "date") else r["trade_date"]
        tx_by_date.setdefault(d, []).append({
            "symbol": r["symbol"], "side": r["side"],
            "qty": float(r["qty"]), "price": float(r["price"]),
            "signed_qty": float(r["signed_qty"]),
        })

    hist_start = hist.index[0].date()
    for d in sorted(tx_by_date.keys()):
        if d < hist_start:
            for r in tx_by_date[d]:
                if r["symbol"] in qty:
                    qty[r["symbol"]] += r["signed_qty"]

    values, cashflows = [], []
    for ts in hist.index:
        d = ts.date() if hasattr(ts, "date") else ts
        cf = 0.0
        for r in tx_by_date.get(d, []):
            if r["symbol"] in qty:
                if r["side"] == "BUY":
                    cf += r["qty"] * r["price"]
                else:
                    cf -= r["qty"] * r["price"]
                qty[r["symbol"]] += r["signed_qty"]
        row = hist.loc[ts]
        v = float(sum(qty[s] * row[s] for s in symbols if pd.notna(row[s])))
        values.append(v)
        cashflows.append(cf)

    return pd.Series(values, index=hist.index, name="value"), pd.Series(cashflows, index=hist.index, name="cashflow")


def twr_curve(values: pd.Series, cashflows: pd.Series) -> pd.Series:
    """Chain-linked daily TWR growth factor series, normalized to 1.0 at start.

    Robust against data artifacts: skips days where prior value is unknown,
    treats v_t == 0 with positive cashflow as a data hole (carry forward),
    clips absurd single-day returns at ±50% as a final safety net.
    """
    if len(values) < 2:
        return pd.Series([1.0] * len(values), index=values.index)
    growth = [1.0]
    prev_v = values.iloc[0]
    for i in range(1, len(values)):
        v_t = values.iloc[i]
        c_t = cashflows.iloc[i]
        # Need a meaningful basis from yesterday
        if prev_v <= 1e-6:
            growth.append(growth[-1])
            if v_t > 1e-6:
                prev_v = v_t
            continue
        # Data hole: deposited cash but end-of-day value is 0 -> carry forward
        if v_t <= 1e-6 and c_t > 1e-6:
            growth.append(growth[-1])
            continue
        r = (v_t - c_t) / prev_v - 1.0
        # Clip absurd returns (likely yfinance data artifacts: missing splits,
        # penny stock noise, etc.). Genuine ±50% portfolio days are vanishingly rare.
        if r < -0.5:
            r = -0.5
        elif r > 1.0:
            r = 1.0
        growth.append(growth[-1] * (1.0 + r))
        prev_v = v_t
    return pd.Series(growth, index=values.index, name="twr")


def daily_dollar_change(values: pd.Series, cashflows: pd.Series) -> pd.Series:
    """Daily $ change attributable to market moves (excludes deposits/withdrawals).

    market_pnl_t = v_t - v_{t-1} - c_t
    """
    if len(values) < 2:
        return pd.Series(dtype=float, index=values.index)
    diff = values.diff() - cashflows
    diff.iloc[0] = 0.0
    return diff


def daily_pct_change(values: pd.Series, cashflows: pd.Series) -> pd.Series:
    """Daily TWR % return per day (same convention as twr_curve)."""
    if len(values) < 2:
        return pd.Series(dtype=float, index=values.index)
    out = [0.0]
    prev_v = values.iloc[0]
    for i in range(1, len(values)):
        v_t = values.iloc[i]
        c_t = cashflows.iloc[i]
        if prev_v <= 1e-6 or (v_t <= 1e-6 and c_t > 1e-6):
            out.append(0.0)
            if v_t > 1e-6:
                prev_v = v_t
            continue
        r = (v_t - c_t) / prev_v - 1.0
        if r < -0.5:
            r = -0.5
        elif r > 1.0:
            r = 1.0
        out.append(r)
        prev_v = v_t
    return pd.Series(out, index=values.index, name="daily_return")


def annualized_return(growth: pd.Series) -> float | None:
    if len(growth) < 2 or growth.iloc[0] <= 0:
        return None
    days = (growth.index[-1] - growth.index[0]).days
    if days <= 0:
        return None
    total = growth.iloc[-1] / growth.iloc[0]
    return float(total ** (365.0 / days) - 1.0)


def drawdown_series(growth: pd.Series) -> pd.Series:
    if growth.empty:
        return growth
    peak = growth.cummax()
    return (growth - peak) / peak


def max_drawdown(growth: pd.Series) -> float:
    dd = drawdown_series(growth)
    return float(dd.min()) if not dd.empty else 0.0


def daily_returns(growth: pd.Series) -> pd.Series:
    return growth.pct_change().dropna()


def volatility(growth: pd.Series, periods_per_year: int = 252) -> float | None:
    r = daily_returns(growth)
    if len(r) < 2:
        return None
    return float(r.std() * np.sqrt(periods_per_year))


def sharpe(growth: pd.Series, rf: float = 0.04, periods_per_year: int = 252) -> float | None:
    ann = annualized_return(growth)
    vol = volatility(growth, periods_per_year)
    if ann is None or vol is None or vol == 0:
        return None
    return float((ann - rf) / vol)


def period_return(growth: pd.Series, days: int) -> float | None:
    if growth.empty:
        return None
    end = growth.index[-1]
    cutoff = end - pd.Timedelta(days=days)
    window = growth[growth.index >= cutoff]
    if len(window) < 2 or window.iloc[0] <= 0:
        return None
    return float(window.iloc[-1] / window.iloc[0] - 1.0)


def ytd_return(growth: pd.Series) -> float | None:
    if growth.empty:
        return None
    end = growth.index[-1]
    yr_start = pd.Timestamp(year=end.year, month=1, day=1, tz=end.tz if hasattr(end, "tz") else None)
    window = growth[growth.index >= yr_start]
    if len(window) < 2 or window.iloc[0] <= 0:
        return None
    return float(window.iloc[-1] / window.iloc[0] - 1.0)


def period_returns_table(growth: pd.Series) -> dict[str, float | None]:
    return {
        "1M": period_return(growth, 30),
        "3M": period_return(growth, 91),
        "6M": period_return(growth, 182),
        "YTD": ytd_return(growth),
        "1Y": period_return(growth, 365),
        "ITD": (float(growth.iloc[-1] / growth.iloc[0] - 1.0)
                if len(growth) >= 2 and growth.iloc[0] > 0 else None),
    }


def benchmark_growth(hist_close: pd.Series) -> pd.Series:
    """Normalize a close-price series to growth factor starting at 1.0."""
    s = hist_close.dropna()
    if s.empty:
        return s
    return s / s.iloc[0]


def position_contribution(positions: pd.DataFrame) -> pd.DataFrame:
    """Rank holdings by their absolute contribution to total P&L."""
    df = positions[["symbol", "unrealized_pnl", "realized_pnl", "invested", "market_value"]].copy()
    df["total_pnl"] = df["unrealized_pnl"] + df["realized_pnl"]
    total = df["total_pnl"].sum()
    df["contribution_pct"] = df["total_pnl"] / total * 100.0 if total else 0.0
    return df.sort_values("total_pnl", ascending=False).reset_index(drop=True)
