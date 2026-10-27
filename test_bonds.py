"""Bond valuation: real vs fixed-rate yields and the multi-bond persistence list."""
from datetime import date

import pytest

import bonds

VAL = date(2026, 10, 27)


def _bond(**over) -> bonds.Bond:
    base = dict(bonds.DEFAULT_BONDS[1])
    base.update(over)
    return bonds.bond_from_dict(base)


def test_fixed_rate_ytm_is_nominal_and_ignores_inflation():
    b = _bond()
    assert b.ytm_real(VAL) is None
    assert b.ytm_nominal(2.0, VAL) == pytest.approx(b.ytm_nominal(5.0, VAL))


def test_bullet_coupon_is_the_fixed_lump_paid_once_at_maturity():
    b = _bond()
    assert b.coupon_dates() == [b.maturity]
    assert b.maturity_coupon() == pytest.approx(22.70)


def test_bullet_ytm_at_par_matches_the_issuer_sheet():
    # Sheet: 22.70% lump over 5 years bought at 100 ≈ 4.18% compounded.
    b = _bond(price_market=100.0, accrued=0.0)
    assert b.ytm_nominal(2.0, date(2026, 10, 27)) == pytest.approx(0.0418, abs=1e-4)


def test_real_coupon_ytm_gets_the_fisher_inflation_add_on():
    b = _bond(coupon_real=True)
    assert b.ytm_nominal(2.0, VAL) == pytest.approx(b.ytm_real(VAL) + 0.02)


def test_new_btp_values_match_the_broker_screen():
    b = _bond()
    assert b.market_value == pytest.approx(100_130.0)
    assert b.pnl == pytest.approx(130.0)


def test_missing_file_gives_both_default_bonds(tmp_path):
    loaded = bonds.load_bonds_data(tmp_path / "absent.json")
    assert [b["isin"] for b in loaded] == ["IT0005648255", "IT0005735227"]


def test_saved_bonds_round_trip_with_dates(tmp_path):
    path = tmp_path / "bond.json"
    data = [{**d, "next_coupon": date.fromisoformat(d["next_coupon"])}
            for d in bonds.DEFAULT_BONDS]
    bonds.save_bonds_data(path, data)
    loaded = bonds.load_bonds_data(path)
    assert [bonds.bond_from_dict(d) for d in loaded] == [
        bonds.bond_from_dict(d) for d in bonds.DEFAULT_BONDS]


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "bond.json"
    path.write_text("{not json", encoding="utf-8")
    assert len(bonds.load_bonds_data(path)) == 2
