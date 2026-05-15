"""Core portfolio logic: parse Yahoo CSV, net positions, realized/unrealized P&L, XIRR."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

import pandas as pd


# ----- Parsing ---------------------------------------------------------------

_COL_ALIASES = {
    "symbol":         ["Symbol", "Ticker", "Stock", "Stock Symbol"],
    "trade_date":     ["Trade Date", "Date", "Purchase Date", "Transaction Date"],
    "price":          ["Purchase Price", "Price", "Trade Price", "Unit Price"],
    "qty":            ["Quantity", "Qty", "Shares", "Units"],
    "side":           ["Transaction Type", "Type", "Action", "Side"],
    "snapshot_price": ["Current Price", "Last Price", "Market Price"],
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip() for c in df.columns]
    rename = {}
    for canonical, candidates in _COL_ALIASES.items():
        for c in candidates:
            if c in df.columns and canonical not in rename.values():
                rename[c] = canonical
                break
    return df.rename(columns=rename)


def load_transactions(csv_path) -> pd.DataFrame:
    # Sniff the first chunk so we can give a useful error if the upload is not actually a CSV
    # (e.g. Yahoo's export API returns a JSON 500 sometimes, saved as .csv by the browser).
    try:
        if hasattr(csv_path, "read"):
            head = csv_path.read(2048)
            if isinstance(head, bytes):
                head = head.decode("utf-8", errors="ignore")
            csv_path.seek(0)
        else:
            with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(2048)
    except Exception:
        head = ""
    stripped = head.lstrip()
    if stripped.startswith("{") or '"finance"' in stripped or '"error"' in stripped[:200]:
        raise ValueError(
            "The uploaded file looks like a JSON error response from Yahoo, not a CSV. "
            "Yahoo's portfolio-export API likely returned an error. "
            "Try re-exporting in a few minutes from Yahoo Finance → Portfolio → ⋯ → "
            "Export Transactions, and make sure the downloaded file starts with the header row "
            "(Symbol, Current Price, Date, ...)."
        )
    if not stripped:
        raise ValueError("The uploaded file is empty.")

    df = pd.read_csv(csv_path)
    df = _normalize_columns(df)

    required = {"symbol", "trade_date", "price", "qty", "side"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            "CSV is missing required columns: "
            f"{sorted(missing)}. Columns found: {list(df.columns)}. "
            f"Expected one of: {[_COL_ALIASES[c] for c in sorted(missing)]}"
        )

    # Parse dates — try Yahoo's compact YYYYMMDD first, then fall back to anything pandas understands.
    td = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
    if td.isna().all():
        td = pd.to_datetime(df["trade_date"], errors="coerce")
    df["trade_date"] = td

    df["qty"] = pd.to_numeric(df["qty"], errors="coerce").fillna(0.0)
    df["price"] = pd.to_numeric(df["price"], errors="coerce").fillna(0.0)
    if "snapshot_price" in df.columns:
        df["snapshot_price"] = pd.to_numeric(df["snapshot_price"], errors="coerce")
    else:
        df["snapshot_price"] = pd.NA

    df["side"] = df["side"].astype(str).str.upper().str.strip()
    # Normalize side values: BUY / SELL with common aliases
    df["side"] = df["side"].replace({
        "B": "BUY", "BOUGHT": "BUY", "PURCHASE": "BUY", "BUY TO OPEN": "BUY",
        "S": "SELL", "SOLD": "SELL", "SALE": "SELL", "SELL TO CLOSE": "SELL",
    })

    df = df.dropna(subset=["trade_date", "symbol"])
    df["signed_qty"] = df.apply(lambda r: r["qty"] if r["side"] == "BUY" else -r["qty"], axis=1)
    df["cashflow"] = -(df["signed_qty"] * df["price"])
    return df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)


# ----- FIFO lot accounting ---------------------------------------------------

@dataclass
class Lot:
    trade_date: date
    qty: float
    price: float


def fifo_match(transactions: Iterable[dict]) -> tuple[list[Lot], float, float]:
    """Walk transactions in date order, FIFO-match sells against open buy lots.

    Returns (open_lots, realized_pnl, total_invested_in_open_lots).
    """
    open_lots: list[Lot] = []
    realized = 0.0
    for t in transactions:
        if t["side"] == "BUY":
            open_lots.append(Lot(t["trade_date"], t["qty"], t["price"]))
        else:  # SELL
            remaining = t["qty"]
            sell_price = t["price"]
            while remaining > 1e-9 and open_lots:
                lot = open_lots[0]
                take = min(lot.qty, remaining)
                realized += take * (sell_price - lot.price)
                lot.qty -= take
                remaining -= take
                if lot.qty <= 1e-9:
                    open_lots.pop(0)
            # If sells exceed buys (short position) — ignore for simplicity
    invested = sum(l.qty * l.price for l in open_lots)
    return open_lots, realized, invested


# ----- Position aggregation --------------------------------------------------

def build_positions(tx: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for symbol, grp in tx.groupby("symbol"):
        grp = grp.sort_values("trade_date")
        records = grp[["trade_date", "side", "qty", "price"]].to_dict("records")
        # Convert pandas Timestamp -> date
        for r in records:
            r["trade_date"] = r["trade_date"].date() if hasattr(r["trade_date"], "date") else r["trade_date"]
        open_lots, realized, invested = fifo_match(records)
        qty = sum(l.qty for l in open_lots)
        avg_cost = (invested / qty) if qty > 1e-9 else 0.0
        first_buy = grp[grp["side"] == "BUY"]["trade_date"].min()
        snapshot_price = grp["snapshot_price"].dropna().iloc[-1] if grp["snapshot_price"].notna().any() else None
        rows.append({
            "symbol": symbol,
            "qty": qty,
            "avg_cost": avg_cost,
            "invested": invested,
            "realized_pnl": realized,
            "first_buy": first_buy,
            "snapshot_price": snapshot_price,
        })
    return pd.DataFrame(rows).sort_values("symbol").reset_index(drop=True)


def enrich_with_prices(positions: pd.DataFrame, price_map: dict[str, float]) -> pd.DataFrame:
    df = positions.copy()
    df["current_price"] = df["symbol"].map(price_map).fillna(df["snapshot_price"])
    df["market_value"] = df["qty"] * df["current_price"]
    df["unrealized_pnl"] = df["market_value"] - df["invested"]
    df["total_pnl"] = df["unrealized_pnl"] + df["realized_pnl"]
    df["return_pct"] = df.apply(
        lambda r: (r["unrealized_pnl"] / r["invested"] * 100.0) if r["invested"] > 1e-9 else 0.0,
        axis=1,
    )
    return df


# ----- XIRR ------------------------------------------------------------------

def xnpv(rate: float, cashflows: list[tuple[date, float]]) -> float:
    if not cashflows:
        return 0.0
    t0 = cashflows[0][0]
    return sum(cf / ((1 + rate) ** ((d - t0).days / 365.0)) for d, cf in cashflows)


def xirr(cashflows: list[tuple[date, float]], guess: float = 0.1) -> float | None:
    """Newton-Raphson XIRR. Returns annualized rate, or None if it doesn't converge."""
    if len(cashflows) < 2:
        return None
    has_pos = any(cf > 0 for _, cf in cashflows)
    has_neg = any(cf < 0 for _, cf in cashflows)
    if not (has_pos and has_neg):
        return None
    rate = guess
    for _ in range(100):
        f = xnpv(rate, cashflows)
        # numerical derivative
        df = (xnpv(rate + 1e-6, cashflows) - f) / 1e-6
        if abs(df) < 1e-12:
            break
        new_rate = rate - f / df
        if new_rate <= -0.999:
            new_rate = (rate - 0.999) / 2  # damp
        if abs(new_rate - rate) < 1e-8:
            return new_rate
        rate = new_rate
    return rate if abs(xnpv(rate, cashflows)) < 1e-3 else None


def position_xirr(symbol: str, tx: pd.DataFrame, current_price: float | None,
                  qty: float, valuation_date: date) -> float | None:
    """Build cashflow list for a symbol: BUYs negative, SELLs positive, current MV positive at today."""
    rows = tx[tx["symbol"] == symbol].sort_values("trade_date")
    cf: list[tuple[date, float]] = []
    for _, r in rows.iterrows():
        d = r["trade_date"].date() if hasattr(r["trade_date"], "date") else r["trade_date"]
        cf.append((d, float(r["cashflow"])))
    if qty > 1e-9 and current_price:
        cf.append((valuation_date, qty * current_price))
    return xirr(cf)


def portfolio_xirr(tx: pd.DataFrame, positions: pd.DataFrame, valuation_date: date) -> float | None:
    cf: list[tuple[date, float]] = []
    for _, r in tx.iterrows():
        d = r["trade_date"].date() if hasattr(r["trade_date"], "date") else r["trade_date"]
        cf.append((d, float(r["cashflow"])))
    total_mv = float((positions["qty"] * positions["current_price"]).sum())
    if total_mv > 0:
        cf.append((valuation_date, total_mv))
    return xirr(cf)


# ----- Day change ------------------------------------------------------------

def day_change(positions: pd.DataFrame, prev_close_map: dict[str, float]) -> pd.DataFrame:
    df = positions.copy()
    df["prev_close"] = df["symbol"].map(prev_close_map)
    df["day_change_$"] = (df["current_price"] - df["prev_close"]) * df["qty"]
    df["day_change_%"] = (df["current_price"] - df["prev_close"]) / df["prev_close"] * 100.0
    return df
