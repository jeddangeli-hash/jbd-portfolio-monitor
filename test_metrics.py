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
