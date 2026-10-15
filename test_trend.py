"""Tests for trend.py (period performance on the Home page)."""
import pandas as pd
import pytest

import trend

IDX = pd.bdate_range("2025-12-22", "2026-10-15")  # Mon 22 Dec 2025 … Thu 15 Oct 2026


def test_daily_base_week_starts_from_previous_friday():
    base = trend.daily_base("1S", IDX)
    assert base == pd.Timestamp("2026-10-09")  # Friday before Monday 12 Oct


def test_daily_base_ytd_and_months():
    assert trend.daily_base("YTD", IDX) == pd.Timestamp("2025-12-31")
    assert trend.daily_base("1M", IDX) == pd.Timestamp("2026-09-15")
    assert trend.daily_base("1A", IDX) is None          # history shorter than a year
    assert trend.daily_base("Inizio", IDX) is None
    assert trend.daily_base("1G", IDX) == IDX[-2]


def test_period_curve_ignores_cash_added_inside_window():
    idx = pd.date_range("2026-01-01", periods=4)
    values = pd.Series([100.0, 110.0, 210.0, 231.0], index=idx)   # +100 bought on day 3
    cash = pd.Series([100.0, 0.0, 100.0, 0.0], index=idx)
    r = trend.period_curve(values, cash, base=idx[1])
    assert r.iloc[0] == 0.0
    # day 3: pnl = 210 - 110 - 100 = 0 ; day 4: pnl = 21 on capital 210
    assert r.iloc[1] == pytest.approx(0.0)
    assert r.iloc[2] == pytest.approx(21 / 210)


def test_period_curve_inception_is_pnl_over_net_cash():
    idx = pd.date_range("2026-01-01", periods=3)
    values = pd.Series([100.0, 120.0, 90.0], index=idx)
    cash = pd.Series([100.0, 0.0, -40.0], index=idx)               # sold 40 on day 3
    r = trend.period_curve(values, cash, base=None)
    assert r.iloc[-1] == pytest.approx((90 - 60) / 60)


def test_intraday_curve_values_current_holdings():
    ts = pd.date_range("2026-10-14 20:00", periods=4, freq="15min", tz="UTC")
    bars = pd.DataFrame({"A": [10.0, 11.0, None, 12.0], "B": [5.0, None, 5.0, 4.0]}, index=ts)
    qty = pd.Series({"A": 2.0, "B": 4.0})
    curve, base = trend.intraday_curve(bars, qty, start=ts[1])
    assert base == ts[0]
    v0 = 2 * 10 + 4 * 5
    assert curve.iloc[-1] == pytest.approx((2 * 12 + 4 * 4) / v0 - 1)
    assert curve.iloc[1] == pytest.approx((2 * 11 + 4 * 5) / v0 - 1)   # B forward-filled


def test_intraday_window_today_and_two_sessions():
    # Fri 9 Oct and Mon 12 Oct have stock bars; Sat/Sun only crypto.
    ts = pd.DatetimeIndex([
        "2026-10-09 14:00", "2026-10-10 12:00", "2026-10-11 12:00",
        "2026-10-12 14:00", "2026-10-12 15:00"], tz="UTC")
    bars = pd.DataFrame({"AAPL": [1, None, None, 1, 1], "BTC-USD": [1, 1, 1, 1, 1]},
                        index=ts, dtype=float)
    one = trend.intraday_window(bars, "1G", ["AAPL"])
    two = trend.intraday_window(bars, "2G", ["AAPL"])
    assert one.tz_convert(trend.LOCAL_TZ).date().isoformat() == "2026-10-12"
    assert two.tz_convert(trend.LOCAL_TZ).date().isoformat() == "2026-10-09"


def test_symbol_period_return_and_sparkline():
    idx = pd.date_range("2026-01-01", periods=100)
    p = pd.Series(range(1, 101), index=idx, dtype=float)
    assert trend.symbol_period_return(p, idx[49]) == pytest.approx(100 / 50 - 1)
    assert trend.symbol_period_return(p, None) is None
    sl = trend.sparkline(p, idx[49], points=10)
    assert sl[0] == 50.0 and sl[-1] == 100.0 and len(sl) <= 11


def test_benchmark_curve_uses_last_price_on_or_before_base():
    idx = pd.DatetimeIndex(["2026-10-09", "2026-10-12", "2026-10-13"])   # Fri, Mon, Tue
    spx = pd.Series([100.0, 102.0, 99.0], index=idx)
    base = pd.Timestamp("2026-10-11")                                     # Sunday
    c = trend.benchmark_curve(spx, base)
    assert c.index[0] == base and c.iloc[0] == 0.0
    assert c.tolist()[1:] == pytest.approx([0.02, -0.01])
    assert trend.benchmark_curve(spx, None).empty
