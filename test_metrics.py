"""Unit tests for metrics.compute_rsi.

Focus: RSI must be dtype-agnostic. The price history can reach compute_rsi as a
pyarrow-backed Series (the Streamlit Cloud crash), so the same input on a numpy
backend and an arrow backend must yield identical results, and degenerate inputs
must return None instead of raising.
"""
import numpy as np
import pandas as pd
import pytest

import metrics as mt


def _prices(n: int = 60, seed: int = 0) -> np.ndarray:
    return 100.0 + np.cumsum(np.random.default_rng(seed).normal(0, 1, n))


def test_rsi_numpy_and_arrow_backends_match():
    """Same prices, numpy vs pyarrow dtype -> identical RSI (no arrow crash)."""
    p = _prices()
    numpy_rsi = mt.compute_rsi(pd.Series(p, dtype="float64"), 14)
    arrow_rsi = mt.compute_rsi(pd.Series(p, dtype="float64[pyarrow]"), 14)
    assert numpy_rsi is not None
    assert arrow_rsi == pytest.approx(numpy_rsi)


def test_rsi_arrow_series_with_interior_nulls():
    """pd.NA holes in an arrow Series are dropped, not fatal."""
    vals = [100.0, 101.0, pd.NA, 102.0, 99.0, 103.0, 101.0, 104.0,
            100.0, 105.0, 102.0, 106.0, 101.0, 107.0, 103.0, 108.0]
    rsi = mt.compute_rsi(pd.Series(vals, dtype="float64[pyarrow]"), 14)
    assert rsi is not None
    assert 0.0 <= rsi <= 100.0


def test_rsi_all_gains_returns_100():
    rsi = mt.compute_rsi(pd.Series(np.arange(20, dtype="float64")), 14)
    assert rsi == 100.0


@pytest.mark.parametrize("series", [
    pd.Series([], dtype="float64"),
    pd.Series([1.0, 2.0, 3.0]),                 # fewer than period+1 points
    pd.Series([np.nan] * 30),                   # all NaN
    pd.Series([np.nan] * 30, dtype="float64[pyarrow]"),
])
def test_rsi_degenerate_inputs_return_none(series):
    assert mt.compute_rsi(series, 14) is None


def test_rsi_none_input_returns_none():
    assert mt.compute_rsi(None, 14) is None


def test_rsi_dataframe_uses_first_column():
    """Duplicate columns make hist[sym] a DataFrame; take the first column."""
    p = _prices()
    df = pd.DataFrame({"AAPL": p})
    assert mt.compute_rsi(df, 14) == pytest.approx(
        mt.compute_rsi(pd.Series(p), 14)
    )


# --------------------------------------------------------------------------
# build_value_series: net cash must be inception-to-date, not window-to-date.
# A position bought before hist.index[0] used to contribute market value with
# zero cost, so `value - cashflow.cumsum()` reported the whole position as
# profit (a -8,141 book charted as +91,859).
# --------------------------------------------------------------------------

def _tx(rows: list[tuple[str, str, str, float, float]]) -> pd.DataFrame:
    """rows: (symbol, iso_date, side, qty, price)."""
    return pd.DataFrame([
        {"symbol": s, "trade_date": pd.Timestamp(d), "side": side,
         "qty": q, "price": px, "signed_qty": q if side == "BUY" else -q}
        for s, d, side, q, px in rows
    ])


def _hist(prices: list[float], start: str = "2025-09-21", sym: str = "BTC-USD") -> pd.DataFrame:
    return pd.DataFrame({sym: prices},
                        index=pd.date_range(start, periods=len(prices), freq="D"))


def test_pnl_curve_matches_true_pnl_for_position_bought_before_window():
    """The reported bug: 1 BTC at 100k, history window starts a year later."""
    v, cf = mt.build_value_series(
        _tx([("BTC-USD", "2024-01-10", "BUY", 1.0, 100_000.0)]),
        _hist([60_000.0, 55_000.0, 91_859.0]),
    )
    pnl = v - cf.cumsum()
    assert pnl.iloc[-1] == pytest.approx(-8_141.0)
    assert pnl.iloc[0] == pytest.approx(-40_000.0)


def test_pre_window_sells_net_against_pre_window_buys():
    """Opening cash is net (buys - sells), not gross cost."""
    v, cf = mt.build_value_series(
        _tx([("BTC-USD", "2024-01-10", "BUY", 2.0, 100_000.0),
             ("BTC-USD", "2024-06-10", "SELL", 1.0, 120_000.0)]),
        _hist([90_000.0, 91_859.0]),
    )
    assert cf.cumsum().iloc[-1] == pytest.approx(80_000.0)   # 200k out, 120k back
    assert (v - cf.cumsum()).iloc[-1] == pytest.approx(11_859.0)


def test_in_window_transactions_still_counted_once():
    """Regression guard: the warm-up must not double-count same-window buys."""
    v, cf = mt.build_value_series(
        _tx([("BTC-USD", "2025-09-22", "BUY", 1.0, 50_000.0)]),
        _hist([60_000.0, 55_000.0, 91_859.0]),
    )
    assert cf.tolist() == pytest.approx([0.0, 50_000.0, 0.0])
    assert (v - cf.cumsum()).iloc[-1] == pytest.approx(41_859.0)


def test_trade_on_a_day_without_a_bar_lands_on_the_next_bar():
    """A Saturday buy against a weekday-only index used to vanish entirely."""
    hist = pd.DataFrame({"BTC-USD": [100.0, 110.0, 120.0]},
                        index=pd.DatetimeIndex(["2026-01-09", "2026-01-12", "2026-01-13"]))
    v, cf = mt.build_value_series(_tx([("BTC-USD", "2026-01-10", "BUY", 2.0, 105.0)]), hist)
    assert cf.tolist() == pytest.approx([0.0, 210.0, 0.0])
    assert v.tolist() == pytest.approx([0.0, 220.0, 240.0])


def test_opening_cash_does_not_distort_twr():
    """TWR ignores element 0 of the cashflow series — it must stay unchanged."""
    tx = _tx([("BTC-USD", "2024-01-10", "BUY", 1.0, 100_000.0)])
    hist = _hist([60_000.0, 55_000.0, 91_859.0])
    v, cf = mt.build_value_series(tx, hist)
    twr = mt.twr_curve(v, cf)
    # Pure price path 60k -> 55k -> 91,859, no flows inside the window.
    assert float(twr.iloc[-1]) == pytest.approx(91_859.0 / 60_000.0)


def test_trim_to_first_holding_preserves_total_cash():
    """A pre-window buy whose price column starts late keeps its cost basis."""
    v = pd.Series([0.0, 0.0, 91_859.0], index=pd.date_range("2025-09-21", periods=3))
    cf = pd.Series([100_000.0, 0.0, 0.0], index=v.index)
    v2, cf2 = mt.trim_to_first_holding(v, cf)
    assert len(v2) == 1
    assert cf2.sum() == pytest.approx(100_000.0)
    assert (v2 - cf2.cumsum()).iloc[-1] == pytest.approx(-8_141.0)


def test_trim_to_first_holding_noop_when_never_positive():
    v = pd.Series([0.0, 0.0], index=pd.date_range("2025-09-21", periods=2))
    cf = pd.Series([0.0, 0.0], index=v.index)
    v2, cf2 = mt.trim_to_first_holding(v, cf)
    assert v2.equals(v) and cf2.equals(cf)


def test_symbols_absent_from_history_are_skipped_on_both_sides():
    """No price column -> neither its value nor its cash enters the series."""
    v, cf = mt.build_value_series(
        _tx([("BTC-USD", "2024-01-10", "BUY", 1.0, 100_000.0),
             ("DOGE-USD", "2024-01-10", "BUY", 1000.0, 0.30)]),
        _hist([91_859.0]),
    )
    assert cf.sum() == pytest.approx(100_000.0)
    assert v.iloc[-1] == pytest.approx(91_859.0)


# --------------------------------------------------------------------------
# Per-class breakdown (Generale "Total P&L over time"): the class curves are
# built independently, so they must still sum to the aggregate curve exactly.
# --------------------------------------------------------------------------

def _pnl(tx: pd.DataFrame, hist: pd.DataFrame) -> pd.Series:
    v, cf = mt.build_value_series(tx, hist)
    return v - cf.cumsum()


def test_per_class_pnl_curves_sum_to_the_aggregate():
    tx = pd.concat([
        _tx([("BTC-USD", "2024-01-10", "BUY", 1.0, 100_000.0)]).assign(asset_class="crypto"),
        _tx([("AAPL", "2025-09-22", "BUY", 10.0, 200.0),
             ("AAPL", "2025-09-23", "SELL", 4.0, 220.0)]).assign(asset_class="stocks"),
    ], ignore_index=True)
    hist = pd.DataFrame(
        {"BTC-USD": [60_000.0, 55_000.0, 91_859.0], "AAPL": [210.0, 215.0, 190.0]},
        index=pd.date_range("2025-09-21", periods=3, freq="D"),
    )

    agg = _pnl(tx, hist)
    parts = [
        _pnl(sub, hist[[s for s in hist.columns if s in set(sub["symbol"])]])
        for _, sub in tx.groupby("asset_class")
    ]
    summed = sum(parts[1:], parts[0])
    assert summed.tolist() == pytest.approx(agg.tolist())
    # And the aggregate still reflects the pre-window crypto cost basis.
    assert agg.iloc[-1] == pytest.approx(-8_141.0 + (6 * 190.0 - (10 * 200.0 - 4 * 220.0)))


def test_symbol_held_in_two_classes_does_not_merge():
    """Same ticker in two classes: each keeps its own qty, both share the price."""
    tx = pd.concat([
        _tx([("BTC-USD", "2025-09-22", "BUY", 1.0, 50_000.0)]).assign(asset_class="crypto"),
        _tx([("BTC-USD", "2025-09-22", "BUY", 2.0, 50_000.0)]).assign(asset_class="etf"),
    ], ignore_index=True)
    hist = _hist([60_000.0, 91_859.0])

    agg = _pnl(tx, hist)
    parts = [
        _pnl(sub, hist[[s for s in hist.columns if s in set(sub["symbol"])]])
        for _, sub in tx.groupby("asset_class")
    ]
    assert sum(parts[1:], parts[0]).tolist() == pytest.approx(agg.tolist())
    # 3 BTC bought at 50k, marked at 91,859.
    assert agg.iloc[-1] == pytest.approx(3 * 91_859.0 - 3 * 50_000.0)
