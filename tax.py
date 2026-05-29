"""Italian capital-gain tax simulator (simplified, personal use).

Assumptions — surfaced in the Post-tax tab disclaimer:
- 26% flat rate on realized capital gains (non-qualified holdings, ordinary regime).
- Realized losses offset realized gains within a calendar year; unused losses
  carry forward to later years.
- Carryforward is modeled as UNLIMITED in time. The real Italian regime caps it
  at 4 fiscal years — this simulator deliberately ignores that limit.
- Dividends are NOT taxed here (they are not modeled as CSV transactions).
- No FX conversion — values are summed as-is, like the rest of the app.
"""
from __future__ import annotations

import pandas as pd

import portfolio as pf

POST_TAX_COLUMNS = [
    "year", "gain_lordo", "loss_lordo", "net", "carryforward_entrante",
    "net_compensato", "imposta", "net_post_tax", "carryforward_uscente",
]


def compute_realized_pnl_by_year(transactions_df: pd.DataFrame) -> pd.DataFrame:
    """Attribute each SELL's realized P&L to the calendar year of the sale.

    Uses portfolio.realized_events (FIFO with sell dates). Returns one row per
    sell event: columns year (int), symbol (str), realized_pnl (float). The
    short-position skip info is propagated via the frame's .attrs["short_skipped"].
    """
    events = pf.realized_events(transactions_df)
    short_skipped = events.attrs.get("short_skipped", {})
    if events.empty:
        out = pd.DataFrame(columns=["year", "symbol", "realized_pnl"])
        out.attrs["short_skipped"] = short_skipped
        return out
    out = events.copy()
    out["year"] = out["sell_date"].apply(lambda d: d.year)
    out = out[["year", "symbol", "realized_pnl"]].reset_index(drop=True)
    out.attrs["short_skipped"] = short_skipped
    return out


def compute_post_tax_table(realized_by_year: pd.DataFrame,
                           initial_carryforward: float = 0.0,
                           tax_rate: float = 0.26) -> pd.DataFrame:
    """Aggregate realized P&L by year and apply the tax with loss carryforward.

    Carryforward is modeled as a value <= 0 (a reserve of unused losses). The
    user-supplied initial_carryforward is a POSITIVE amount of prior unabsorbed
    losses; it is normalized to -abs(...) for the first year.

    Per year, processed in ascending order:
        gain_lordo            = Σ realized > 0
        loss_lordo            = Σ realized < 0            (<= 0)
        net                   = gain_lordo + loss_lordo
        carryforward_entrante = carry from the prior year (<= 0)
        net_compensato        = net + carryforward_entrante
        imposta               = max(0, net_compensato) * tax_rate
        carryforward_uscente  = min(0, net_compensato)
        net_post_tax          = net - imposta

    Only years that actually have realized sales appear as rows; the carryforward
    still propagates across any gap years. Returns a DataFrame with columns:
    year, gain_lordo, loss_lordo, net, carryforward_entrante, net_compensato,
    imposta, net_post_tax, carryforward_uscente.
    """
    if realized_by_year is None or realized_by_year.empty:
        return pd.DataFrame(columns=POST_TAX_COLUMNS)

    grouped = realized_by_year.groupby("year")["realized_pnl"]
    gain = grouped.apply(lambda s: float(s[s > 0].sum()))
    loss = grouped.apply(lambda s: float(s[s < 0].sum()))
    years = sorted(int(y) for y in gain.index)

    carry = -abs(float(initial_carryforward)) + 0.0  # prior losses, <= 0 (+0.0 avoids -0.0)
    rows = []
    for y in years:
        gl = float(gain.get(y, 0.0))
        ll = float(loss.get(y, 0.0))
        net = gl + ll
        carry_in = carry
        net_comp = net + carry_in
        imposta = max(0.0, net_comp) * tax_rate
        carry_out = min(0.0, net_comp)
        net_post = net - imposta
        rows.append({
            "year": y,
            "gain_lordo": gl,
            "loss_lordo": ll,
            "net": net,
            "carryforward_entrante": carry_in,
            "net_compensato": net_comp,
            "imposta": imposta,
            "net_post_tax": net_post,
            "carryforward_uscente": carry_out,
        })
        carry = carry_out
    return pd.DataFrame(rows, columns=POST_TAX_COLUMNS)
