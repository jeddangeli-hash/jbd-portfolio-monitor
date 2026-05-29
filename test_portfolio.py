"""Unit tests for lifetime cost/value and FIFO realized-event logic in portfolio.py.

No network: everything runs off in-memory CSVs through the real parsing pipeline.
"""
import io

import pandas as pd
import pytest

import portfolio as pf


def _tx(csv: str) -> pd.DataFrame:
    """Parse an in-memory Yahoo-style CSV through the real loader."""
    return pf.load_transactions(io.StringIO(csv))


def _positions(csv: str, price_map: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    tx = _tx(csv)
    pos = pf.enrich_with_prices(pf.build_positions(tx), price_map)
    return tx, pos


# --------------------------------------------------------------------------
# build_lifetime_stats
# --------------------------------------------------------------------------

def test_lifetime_open_position_with_partial_sale():
    # Bought 20 (10@100 + 10@120), sold 5@150, still holds 15 at $160.
    csv = (
        "Symbol,Trade Date,Purchase Price,Quantity,Transaction Type\n"
        "AAA,20240101,100,10,BUY\n"
        "AAA,20240201,120,10,BUY\n"
        "AAA,20240301,150,5,SELL\n"
    )
    tx, pos = _positions(csv, {"AAA": 160.0})
    ls = pf.build_lifetime_stats(pos, tx).loc["AAA"]

    assert ls["gross_buys_qty"] == pytest.approx(20.0)
    assert ls["gross_sells_qty"] == pytest.approx(5.0)
    assert ls["avg_buy_lifetime"] == pytest.approx(2200.0 / 20.0)   # 110
    assert ls["avg_sale_lifetime"] == pytest.approx(150.0)
    assert ls["total_invested_lifetime"] == pytest.approx(2200.0)
    assert ls["total_returned_lifetime"] == pytest.approx(750.0)
    assert ls["current_market_value"] == pytest.approx(15 * 160.0)  # 2400
    assert ls["total_value_lifetime"] == pytest.approx(2400.0 + 750.0)
    assert ls["troic"] == pytest.approx(3150.0 / 2200.0 - 1.0)


def test_lifetime_closed_position_market_value_zero():
    # Bought 20@50, sold all 20@80 -> closed, no open market value.
    csv = (
        "Symbol,Trade Date,Purchase Price,Quantity,Transaction Type\n"
        "BBB,20240110,50,20,BUY\n"
        "BBB,20240410,80,20,SELL\n"
    )
    tx, pos = _positions(csv, {"BBB": 90.0})
    ls = pf.build_lifetime_stats(pos, tx).loc["BBB"]

    assert ls["current_market_value"] == pytest.approx(0.0)
    assert ls["total_value_lifetime"] == pytest.approx(1600.0)       # only returned cash
    assert ls["troic"] == pytest.approx(1600.0 / 1000.0 - 1.0)       # 60%


def test_lifetime_open_no_sales_troic_equals_paper_return():
    csv = (
        "Symbol,Trade Date,Purchase Price,Quantity,Transaction Type\n"
        "CCC,20240115,200,3,BUY\n"
    )
    tx, pos = _positions(csv, {"CCC": 210.0})
    ls = pf.build_lifetime_stats(pos, tx).loc["CCC"]

    assert ls["gross_sells_qty"] == pytest.approx(0.0)
    assert pd.isna(ls["avg_sale_lifetime"])
    assert ls["total_returned_lifetime"] == pytest.approx(0.0)
    assert ls["troic"] == pytest.approx(630.0 / 600.0 - 1.0)         # 5% == paper return


def test_lifetime_troic_none_when_no_buys():
    # A SELL with no prior BUY: invested == 0 -> troic must be None, avg_buy None.
    csv = (
        "Symbol,Trade Date,Purchase Price,Quantity,Transaction Type\n"
        "ZZZ,20240601,50,10,SELL\n"
    )
    tx, pos = _positions(csv, {"ZZZ": 55.0})
    ls = pf.build_lifetime_stats(pos, tx).loc["ZZZ"]

    assert ls["total_invested_lifetime"] == pytest.approx(0.0)
    assert pd.isna(ls["avg_buy_lifetime"])
    assert ls["troic"] is None or pd.isna(ls["troic"])


def test_lifetime_weighted_average_buy():
    # 100@10 + 50@14 -> weighted avg = 1700/150
    csv = (
        "Symbol,Trade Date,Purchase Price,Quantity,Transaction Type\n"
        "DDD,20240105,10,100,BUY\n"
        "DDD,20240205,14,50,BUY\n"
    )
    tx, pos = _positions(csv, {"DDD": 18.0})
    ls = pf.build_lifetime_stats(pos, tx).loc["DDD"]

    assert ls["avg_buy_lifetime"] == pytest.approx(1700.0 / 150.0)
    assert ls["total_invested_lifetime"] == pytest.approx(1700.0)


# --------------------------------------------------------------------------
# realized_events
# --------------------------------------------------------------------------

def _fifo_realized(grp: pd.DataFrame) -> float:
    recs = grp.sort_values("trade_date")[["trade_date", "side", "qty", "price"]].to_dict("records")
    for r in recs:
        r["trade_date"] = r["trade_date"].date()
    _, realized, _ = pf.fifo_match(recs)
    return realized


def test_realized_events_total_matches_fifo_match():
    csv = (
        "Symbol,Trade Date,Purchase Price,Quantity,Transaction Type\n"
        "AAA,20240101,100,10,BUY\n"
        "AAA,20240201,120,10,BUY\n"
        "AAA,20240301,150,5,SELL\n"
        "BBB,20240110,50,20,BUY\n"
        "BBB,20240410,80,20,SELL\n"
    )
    tx = _tx(csv)
    ev = pf.realized_events(tx)
    for sym, grp in tx.groupby("symbol"):
        ev_sum = float(ev[ev["symbol"] == sym]["realized_pnl"].sum())
        assert ev_sum == pytest.approx(_fifo_realized(grp))


def test_realized_events_attributes_sell_date():
    csv = (
        "Symbol,Trade Date,Purchase Price,Quantity,Transaction Type\n"
        "AAA,20230101,10,100,BUY\n"
        "AAA,20240601,15,100,SELL\n"
    )
    ev = pf.realized_events(_tx(csv))
    assert len(ev) == 1
    row = ev.iloc[0]
    assert row["sell_date"] == pd.Timestamp("2024-06-01").date()
    assert row["realized_pnl"] == pytest.approx(500.0)


def test_realized_events_records_full_short_skip():
    # Pure short: sell with no prior buy -> 0 realized, 10 shares skipped.
    csv = (
        "Symbol,Trade Date,Purchase Price,Quantity,Transaction Type\n"
        "SHORT,20240601,50,10,SELL\n"
    )
    ev = pf.realized_events(_tx(csv))
    assert ev.attrs["short_skipped"] == {"SHORT": 10.0}
    assert float(ev["realized_pnl"].sum()) == pytest.approx(0.0)


def test_realized_events_records_partial_short_skip():
    # Bought 4, sold 10 -> 4 matched, 6 skipped. Realized on the 4 covered shares.
    csv = (
        "Symbol,Trade Date,Purchase Price,Quantity,Transaction Type\n"
        "PART,20240101,10,4,BUY\n"
        "PART,20240301,20,10,SELL\n"
    )
    ev = pf.realized_events(_tx(csv))
    assert ev.attrs["short_skipped"] == {"PART": pytest.approx(6.0)}
    # 4 shares matched at +10 each = 40
    assert float(ev["realized_pnl"].sum()) == pytest.approx(40.0)


def test_realized_events_empty_when_no_sells():
    csv = (
        "Symbol,Trade Date,Purchase Price,Quantity,Transaction Type\n"
        "AAA,20240101,10,100,BUY\n"
    )
    ev = pf.realized_events(_tx(csv))
    assert ev.empty
    assert ev.attrs["short_skipped"] == {}
