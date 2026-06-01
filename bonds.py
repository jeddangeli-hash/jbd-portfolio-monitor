"""Bond (BTP) valuation — pure logic, kept separate from the CSV/stock engine.

The target instrument is an inflation-linked BTP Italia: coupons are quoted in
REAL terms (the inflation uplift is applied to the principal separately at
redemption). We therefore compute a REAL yield-to-maturity from the real coupon
stream + redemption at 100, and approximate the NOMINAL yield via Fisher
(nominal ≈ real + assumed inflation).

Reuses portfolio.xirr for the YTM solve — a redemption-at-100 plus dated coupons
is just a cashflow stream, so its annualized IRR is the yield to maturity.
"""
from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import portfolio as pf  # reuse xirr (IRR of dated cashflows == YTM)


def _add_months(d: date, n: int) -> date:
    """Add n calendar months, clamping the day to the target month's length."""
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


@dataclass
class Bond:
    isin: str
    nominal: float          # face value held, in currency units
    price_load: float       # average load (purchase) price, base 100
    price_market: float     # current market price, base 100 (clean)
    coupon_pct: float       # annual REAL coupon rate, %
    frequency: int          # coupons per year (2 = semiannual)
    accrued: float          # accrued interest (rateo), shown separately
    next_coupon: date       # next coupon date
    maturity: date          # redemption date
    currency: str = "EUR"

    # ----- clean capital values (accrued excluded, by design) -----
    @property
    def load_value(self) -> float:
        return self.nominal * self.price_load / 100.0

    @property
    def market_value(self) -> float:
        return self.nominal * self.price_market / 100.0

    @property
    def pnl(self) -> float:
        return self.market_value - self.load_value

    @property
    def return_pct(self) -> float:
        return (self.pnl / self.load_value * 100.0) if self.load_value else 0.0

    @property
    def current_yield(self) -> float:
        """Annual coupon ÷ market price (base 100), in %."""
        return (self.coupon_pct / self.price_market * 100.0) if self.price_market else 0.0

    # ----- cashflows & yields (per 100 face) -----
    def coupon_dates(self) -> list[date]:
        """All remaining coupon dates from next_coupon through maturity inclusive."""
        step = max(1, round(12 / self.frequency))
        out: list[date] = []
        d = self.next_coupon
        # guard against a misconfigured schedule running away
        while d <= self.maturity and len(out) < 600:
            out.append(d)
            d = _add_months(d, step)
        if not out or out[-1] != self.maturity:
            out.append(self.maturity)
        return out

    def ytm_real(self, valuation: date | None = None) -> float | None:
        """Real YTM: IRR of (−clean price) today + real coupons + redemption 100.

        Per 100 face. Reuses portfolio.xirr; returns None if it doesn't converge.
        """
        val = valuation or date.today()
        coupon = self.coupon_pct / self.frequency  # per period, per 100 face
        cf: list[tuple[date, float]] = [(val, -self.price_market)]
        for d in self.coupon_dates():
            if d > val:
                cf.append((d, coupon))
        cf.append((self.maturity, 100.0))  # principal redemption, on top of final coupon
        return pf.xirr(cf)

    def ytm_nominal(self, inflation_pct: float, valuation: date | None = None) -> float | None:
        """Fisher approximation: nominal ≈ real + assumed inflation."""
        r = self.ytm_real(valuation)
        return (r + inflation_pct / 100.0) if r is not None else None


# ----- persistence ----------------------------------------------------------

DEFAULT_BOND = {
    "isin": "IT0005648255",
    "nominal": 150000.0,
    "price_load": 100.8978,
    "price_market": 102.37,
    "coupon_pct": 1.85,
    "frequency": 2,
    "accrued": 972.33,
    "next_coupon": "2026-06-04",
    "maturity": "2032-06-04",
    "currency": "EUR",
}


def bond_from_dict(d: dict) -> Bond:
    return Bond(
        isin=str(d["isin"]),
        nominal=float(d["nominal"]),
        price_load=float(d["price_load"]),
        price_market=float(d["price_market"]),
        coupon_pct=float(d["coupon_pct"]),
        frequency=int(d["frequency"]),
        accrued=float(d["accrued"]),
        next_coupon=d["next_coupon"] if isinstance(d["next_coupon"], date)
        else date.fromisoformat(str(d["next_coupon"])),
        maturity=d["maturity"] if isinstance(d["maturity"], date)
        else date.fromisoformat(str(d["maturity"])),
        currency=str(d.get("currency", "EUR")),
    )


def load_bond_data(path) -> dict:
    """Saved bond dict merged over DEFAULT_BOND; DEFAULT_BOND if missing/unreadable."""
    p = Path(path)
    if p.exists():
        try:
            return {**DEFAULT_BOND, **json.loads(p.read_text(encoding="utf-8"))}
        except Exception:
            return dict(DEFAULT_BOND)
    return dict(DEFAULT_BOND)


def save_bond_data(path, data: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    out = dict(data)
    for k in ("next_coupon", "maturity"):
        v = out.get(k)
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
    p.write_text(json.dumps(out, indent=2), encoding="utf-8")
