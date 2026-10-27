"""Bond (BTP) valuation — pure logic, kept separate from the CSV/stock engine.

Inflation-linked BTP Italia coupons are quoted in REAL terms (the inflation
uplift is applied to the principal separately at redemption). For those we
compute a REAL yield-to-maturity from the real coupon stream + redemption at
100, and approximate the NOMINAL yield via Fisher (nominal ≈ real + assumed
inflation). Fixed-rate BTPs (coupon_real=False) quote nominal coupons, so the
same IRR is already the nominal yield and no inflation is added.

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
    coupon_real: bool = True  # False for a fixed-rate (nominal-coupon) BTP
    # True when all interest is paid in one lump with the redemption; the lump is
    # lump_coupon_pct of nominal (coupon_pct is then only the quoted per-year rate)
    coupon_at_maturity: bool = False
    lump_coupon_pct: float = 0.0

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
    def maturity_coupon(self) -> float:
        """Lump-sum coupon per 100 face paid at maturity (coupon_at_maturity bonds)."""
        return self.lump_coupon_pct

    def coupon_dates(self) -> list[date]:
        """All remaining coupon dates from next_coupon through maturity inclusive."""
        if self.coupon_at_maturity:
            return [self.maturity]
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

    def _ytm(self, valuation: date | None = None) -> float | None:
        """IRR of (−clean price) today + coupons + redemption 100, per 100 face.

        Reuses portfolio.xirr; returns None if it doesn't converge.
        """
        val = valuation or date.today()
        if self.coupon_at_maturity:
            # The buyer pays the rateo on top of the clean price and gets it back
            # inside the lump coupon, so the outflow is the dirty price.
            dirty = self.price_market + self.accrued / self.nominal * 100.0
            return pf.xirr([(val, -dirty), (self.maturity, 100.0 + self.maturity_coupon())])
        coupon = self.coupon_pct / self.frequency  # per period, per 100 face
        cf: list[tuple[date, float]] = [(val, -self.price_market)]
        for d in self.coupon_dates():
            if d > val:
                cf.append((d, coupon))
        cf.append((self.maturity, 100.0))  # principal redemption, on top of final coupon
        return pf.xirr(cf)

    def ytm_real(self, valuation: date | None = None) -> float | None:
        """Real YTM — only defined when the coupons are quoted in real terms."""
        return self._ytm(valuation) if self.coupon_real else None

    def ytm_nominal(self, inflation_pct: float, valuation: date | None = None) -> float | None:
        """Nominal YTM: Fisher (real + inflation) for real coupons, the plain IRR otherwise."""
        y = self._ytm(valuation)
        if y is None:
            return None
        return y + inflation_pct / 100.0 if self.coupon_real else y


# ----- persistence ----------------------------------------------------------

DEFAULT_BONDS = [
    {
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
        "coupon_real": True,
        "coupon_at_maturity": False,
        "lump_coupon_pct": 0.0,
    },
    {  # BTP-27OT31 VAL, bought 2026-10-27. Fixed-rate (nominal) coupon, paid once at maturity.
        "isin": "IT0005735227",
        "nominal": 100000.0,
        "price_load": 100.0,
        "price_market": 100.13,
        "coupon_pct": 4.54,
        "frequency": 1,
        "accrued": 22.07,
        "next_coupon": "2031-10-27",
        "maturity": "2031-10-27",
        "currency": "EUR",
        "coupon_real": False,
        "coupon_at_maturity": True,
        "lump_coupon_pct": 22.70,  # 4.54% × 5 years, gross, single payment
    },
]


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
        coupon_real=bool(d.get("coupon_real", True)),
        coupon_at_maturity=bool(d.get("coupon_at_maturity", False)),
        lump_coupon_pct=float(d.get("lump_coupon_pct", 0.0)),
    )


def load_bonds_data(path) -> list[dict]:
    """Saved bond list; DEFAULT_BONDS if the file is missing or unreadable."""
    p = Path(path)
    if p.exists():
        try:
            saved = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(saved, list) and saved:
                return [{**DEFAULT_BONDS[0], **b} for b in saved]
        except (OSError, ValueError):
            pass
    return [dict(b) for b in DEFAULT_BONDS]


def save_bonds_data(path, data: list[dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    out = []
    for b in data:
        b = dict(b)
        for k in ("next_coupon", "maturity"):
            if hasattr(b.get(k), "isoformat"):
                b[k] = b[k].isoformat()
        out.append(b)
    p.write_text(json.dumps(out, indent=2), encoding="utf-8")
