"""Unit tests for the Italian capital-gain tax simulator (tax.py).

No network: realized P&L is derived from in-memory CSVs via the real FIFO logic.
"""
import io

import pandas as pd
import pytest

import portfolio as pf
import tax


def _tx(csv: str) -> pd.DataFrame:
    return pf.load_transactions(io.StringIO(csv))


# A multi-year scenario reused across tests:
#   2022: +500 (GAIN1) and -800 (LOSS1)  -> net -300
#   2023: -1000 (LOSS2)                   -> net -1000
#   2024: +2000 (GAIN2)                   -> net +2000
MULTI_YEAR = (
    "Symbol,Trade Date,Purchase Price,Quantity,Transaction Type\n"
    "GAIN1,20220101,10,100,BUY\n"
    "GAIN1,20220601,15,100,SELL\n"
    "LOSS1,20220201,20,100,BUY\n"
    "LOSS1,20220701,12,100,SELL\n"
    "LOSS2,20230101,30,50,BUY\n"
    "LOSS2,20230301,10,50,SELL\n"
    "GAIN2,20240101,5,100,BUY\n"
    "GAIN2,20240501,25,100,SELL\n"
)


# --------------------------------------------------------------------------
# compute_realized_pnl_by_year
# --------------------------------------------------------------------------

def test_realized_by_year_attributes_to_sale_year():
    rby = tax.compute_realized_pnl_by_year(_tx(MULTI_YEAR))
    by_year = rby.groupby("year")["realized_pnl"].sum()
    assert by_year.loc[2022] == pytest.approx(-300.0)   # 500 - 800
    assert by_year.loc[2023] == pytest.approx(-1000.0)
    assert by_year.loc[2024] == pytest.approx(2000.0)


def test_realized_by_year_empty_when_no_sales():
    csv = (
        "Symbol,Trade Date,Purchase Price,Quantity,Transaction Type\n"
        "AAA,20240101,10,100,BUY\n"
    )
    rby = tax.compute_realized_pnl_by_year(_tx(csv))
    assert rby.empty


# --------------------------------------------------------------------------
# compute_post_tax_table
# --------------------------------------------------------------------------

def test_post_tax_gain_is_taxed_at_26pct():
    # Single year, single gain of 500 -> 130 tax, 370 net.
    csv = (
        "Symbol,Trade Date,Purchase Price,Quantity,Transaction Type\n"
        "G,20240101,10,100,BUY\n"
        "G,20240601,15,100,SELL\n"
    )
    rby = tax.compute_realized_pnl_by_year(_tx(csv))
    pt = tax.compute_post_tax_table(rby)
    row = pt[pt["year"] == 2024].iloc[0]
    assert row["net"] == pytest.approx(500.0)
    assert row["imposta"] == pytest.approx(130.0)
    assert row["net_post_tax"] == pytest.approx(370.0)
    assert row["carryforward_uscente"] == pytest.approx(0.0)


def test_post_tax_loss_carryforward_offsets_future_gain():
    rby = tax.compute_realized_pnl_by_year(_tx(MULTI_YEAR))
    pt = tax.compute_post_tax_table(rby, initial_carryforward=0.0).set_index("year")

    # 2022: net -300, no tax, carry out -300
    assert pt.loc[2022, "imposta"] == pytest.approx(0.0)
    assert pt.loc[2022, "carryforward_uscente"] == pytest.approx(-300.0)
    # 2023: net -1000, carry in -300 -> carry out -1300, no tax
    assert pt.loc[2023, "carryforward_entrante"] == pytest.approx(-300.0)
    assert pt.loc[2023, "carryforward_uscente"] == pytest.approx(-1300.0)
    assert pt.loc[2023, "imposta"] == pytest.approx(0.0)
    # 2024: gain 2000, carry in -1300 -> base 700 -> tax 182, carry out 0
    assert pt.loc[2024, "net_compensato"] == pytest.approx(700.0)
    assert pt.loc[2024, "imposta"] == pytest.approx(182.0)
    assert pt.loc[2024, "net_post_tax"] == pytest.approx(1818.0)
    assert pt.loc[2024, "carryforward_uscente"] == pytest.approx(0.0)


def test_post_tax_totals():
    rby = tax.compute_realized_pnl_by_year(_tx(MULTI_YEAR))
    pt = tax.compute_post_tax_table(rby)
    assert float(pt["net"].sum()) == pytest.approx(700.0)
    assert float(pt["imposta"].sum()) == pytest.approx(182.0)
    assert float(pt["net_post_tax"].sum()) == pytest.approx(518.0)
    # carryforward residuo = last row's carry out
    assert float(pt["carryforward_uscente"].iloc[-1]) == pytest.approx(0.0)


def test_post_tax_initial_carryforward_is_normalized_to_negative():
    rby = tax.compute_realized_pnl_by_year(_tx(MULTI_YEAR))
    pt = tax.compute_post_tax_table(rby, initial_carryforward=200.0).set_index("year")
    # First year carry in = -200 (positive input normalized to a loss reserve)
    assert pt.loc[2022, "carryforward_entrante"] == pytest.approx(-200.0)
    # 2024 base = 2000 + (-1300 - 200) = 500 -> tax 130
    assert pt.loc[2024, "imposta"] == pytest.approx(130.0)


def test_post_tax_year_with_only_losses_pays_no_tax():
    csv = (
        "Symbol,Trade Date,Purchase Price,Quantity,Transaction Type\n"
        "L,20240101,30,50,BUY\n"
        "L,20240301,10,50,SELL\n"
    )
    rby = tax.compute_realized_pnl_by_year(_tx(csv))
    pt = tax.compute_post_tax_table(rby)
    row = pt[pt["year"] == 2024].iloc[0]
    assert row["net"] == pytest.approx(-1000.0)
    assert row["imposta"] == pytest.approx(0.0)
    assert row["carryforward_uscente"] == pytest.approx(-1000.0)


def test_post_tax_empty_input_returns_empty_table():
    empty = pd.DataFrame(columns=["year", "symbol", "realized_pnl"])
    pt = tax.compute_post_tax_table(empty)
    assert pt.empty
    assert list(pt.columns) == tax.POST_TAX_COLUMNS


def test_post_tax_first_year_carry_entrante_is_not_negative_zero():
    # Regression: -abs(0.0) used to yield -0.0, rendering as "€-0".
    import math
    csv = (
        "Symbol,Trade Date,Purchase Price,Quantity,Transaction Type\n"
        "G,20240101,10,100,BUY\n"
        "G,20240601,15,100,SELL\n"
    )
    rby = tax.compute_realized_pnl_by_year(_tx(csv))
    pt = tax.compute_post_tax_table(rby, initial_carryforward=0.0)
    carry_in = float(pt["carryforward_entrante"].iloc[0])
    assert carry_in == 0.0
    assert math.copysign(1.0, carry_in) > 0  # positive zero, not -0.0
