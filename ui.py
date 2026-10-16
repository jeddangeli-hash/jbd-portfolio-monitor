"""Visual layer: global CSS, KPI cards and the brand header.

Colours mirror .streamlit/config.toml (dark theme). Everything here returns or
emits HTML strings, so app.py stays about data and layout.
"""
from __future__ import annotations

from datetime import datetime
from html import escape

import streamlit as st

POS = "#22c55e"
NEG = "#f43f5e"
ACCENT = "#4f8cff"
# Categorical palette for pies/bars (same as theme.chartCategoricalColors).
PALETTE = ["#4f8cff", "#22c3a6", "#f5a524", "#a78bfa", "#f472b6",
           "#38bdf8", "#fb7185", "#a3e635", "#facc15", "#94a3b8"]

CSS = """
<style>
:root {
  --bg: #0b0f17; --card: #121925; --card-2: #172031; --line: #232c3b;
  --muted: #8b95a7; --text: #e6ebf2; --accent: #4f8cff;
  --pos: #22c55e; --neg: #f43f5e;
}
.block-container { padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1480px; }
header[data-testid="stHeader"] { background: transparent; }
footer, #MainMenu { visibility: hidden; }

/* Soft brand glow behind the page */
[data-testid="stAppViewContainer"] {
  background:
    radial-gradient(1100px 500px at 85% -10%, rgba(79,140,255,0.10), transparent 60%),
    radial-gradient(900px 420px at -10% 10%, rgba(34,195,166,0.07), transparent 60%),
    var(--bg);
}

@keyframes fadeUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(34,197,94,.55); } 70% { box-shadow: 0 0 0 8px rgba(34,197,94,0); } 100% { box-shadow: 0 0 0 0 rgba(34,197,94,0); } }

/* ---------- brand header ---------- */
.brand { display: flex; align-items: center; justify-content: space-between; gap: 16px;
  flex-wrap: wrap; margin: 4px 0 18px; animation: fadeUp .45s ease both; }
.brand-left { display: flex; align-items: center; gap: 14px; }
.brand-logo { width: 44px; height: 44px; border-radius: 12px; display: grid; place-items: center;
  background: linear-gradient(135deg, #4f8cff 0%, #22c3a6 100%);
  box-shadow: 0 8px 24px rgba(79,140,255,.28); }
.brand-logo svg { width: 24px; height: 24px; }
.brand-title { font-size: 1.45rem; font-weight: 700; letter-spacing: -0.02em; color: var(--text); line-height: 1.1; }
.brand-sub { color: var(--muted); font-size: .85rem; margin-top: 2px; }
.brand-right { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.chip { display: inline-flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 999px;
  background: var(--card); border: 1px solid var(--line); color: var(--muted); font-size: .8rem; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
.dot.live { background: var(--pos); animation: pulse 2s infinite; }

/* ---------- KPI cards ---------- */
.kpi-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; margin: 6px 0 18px; }
.kpi-card {
  position: relative; overflow: hidden;
  background: linear-gradient(160deg, var(--card-2) 0%, var(--card) 100%);
  border: 1px solid var(--line); border-radius: 16px; padding: 16px 18px;
  transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
  animation: fadeUp .5s ease both;
}
.kpi-card:hover { transform: translateY(-2px); border-color: #34425a; box-shadow: 0 10px 28px rgba(0,0,0,.35); }
.kpi-card::before { content: ""; position: absolute; inset: 0 0 auto 0; height: 2px; background: var(--line); }
.kpi-card.pos::before { background: linear-gradient(90deg, var(--pos), transparent); }
.kpi-card.neg::before { background: linear-gradient(90deg, var(--neg), transparent); }
.kpi-card.hero::before { background: linear-gradient(90deg, var(--accent), #22c3a6); }
.kpi-grid .kpi-card:nth-child(2) { animation-delay: .05s; }
.kpi-grid .kpi-card:nth-child(3) { animation-delay: .10s; }
.kpi-grid .kpi-card:nth-child(4) { animation-delay: .15s; }
.kpi-grid .kpi-card:nth-child(5) { animation-delay: .20s; }
.kpi-grid .kpi-card:nth-child(6) { animation-delay: .25s; }
.kpi-label { color: var(--muted); font-size: .72rem; font-weight: 600; text-transform: uppercase; letter-spacing: .07em; margin-bottom: 8px; }
.kpi-value { color: var(--text); font-size: clamp(1.1rem, 1.45vw, 1.6rem); font-weight: 700; line-height: 1.15;
  letter-spacing: -0.02em; font-variant-numeric: tabular-nums; white-space: nowrap; }
.kpi-card.hero .kpi-value { font-size: clamp(1.15rem, 1.6vw, 1.85rem); }
.kpi-sub { font-size: .82rem; margin-top: 6px; color: var(--muted); font-variant-numeric: tabular-nums; }
.kpi-pos { color: var(--pos); } .kpi-neg { color: var(--neg); }
.pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-weight: 600; font-size: .78rem; }
.pill.pos { background: rgba(34,197,94,.12); color: var(--pos); }
.pill.neg { background: rgba(244,63,94,.12); color: var(--neg); }

/* native st.metric, wherever still used, gets the same card look */
[data-testid="stMetric"] { background: linear-gradient(160deg, var(--card-2), var(--card));
  border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px; animation: fadeUp .5s ease both; }
[data-testid="stMetricLabel"] { color: var(--muted); }
[data-testid="stMetricValue"] { font-size: clamp(1.1rem, 1.7vw, 1.9rem) !important; }

/* ---------- period returns grid ---------- */
.period-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; margin: 8px 0 18px; }
.period-cell { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
  padding: 12px 14px; text-align: center; animation: fadeUp .45s ease both; }
.period-label { color: var(--muted); font-size: .7rem; font-weight: 600; letter-spacing: .07em; text-transform: uppercase; }
.period-value { font-size: 1.2rem; font-weight: 700; margin-top: 4px; font-variant-numeric: tabular-nums; }

/* ---------- typography ---------- */
h1, h2, h3 { font-weight: 650 !important; letter-spacing: -0.015em; }
h2 { font-size: 1.35rem !important; } h3 { font-size: 1.1rem !important; }
[data-testid="stCaptionContainer"] { color: var(--muted); }

/* ---------- tabs as scrollable pills ---------- */
[role="tablist"] { gap: 6px !important; overflow-x: auto; scrollbar-width: none; padding: 5px;
  background: var(--card); border: 1px solid var(--line); border-radius: 14px; }
[role="tablist"]::-webkit-scrollbar { display: none; }
[data-testid="stTab"] { padding: 7px 14px !important; border-radius: 10px; white-space: nowrap;
  color: var(--muted); transition: background .15s ease, color .15s ease; }
[data-testid="stTab"]:hover { background: rgba(255,255,255,.04); color: var(--text); }
[data-testid="stTab"][aria-selected="true"] { background: rgba(79,140,255,.18); color: var(--text); }
[data-testid="stTab"] p { font-size: .88rem; font-weight: 500; }
[role="tablist"] .react-aria-SelectionIndicator { display: none; }
[role="tabpanel"] { padding-top: 16px; animation: fadeUp .35s ease both; }

/* ---------- charts, tables, alerts ---------- */
[data-testid="stPlotlyChart"] { background: var(--card); border: 1px solid var(--line);
  border-radius: 16px; overflow: hidden; animation: fadeUp .5s ease both; }
[data-testid="stDataFrame"], [data-testid="stTable"] { border-radius: 12px; overflow: hidden; }
[data-testid="stAlert"] { border-radius: 12px; }
hr { border-color: var(--line) !important; opacity: .7; }

/* ---------- sidebar ---------- */
[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; align-items: center; gap: .5rem; }
[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { min-width: 0 !important; }
[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child { flex: 0 0 auto !important; width: auto !important; }
[data-testid="stSidebar"] .block-container, [data-testid="stSidebarUserContent"] { padding-top: 1rem; }
.side-brand { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.side-brand .brand-logo { width: 34px; height: 34px; border-radius: 10px; }
.side-brand .brand-logo svg { width: 18px; height: 18px; }
.side-brand b { font-size: 1rem; letter-spacing: -0.01em; }
.side-section { color: var(--muted); font-size: .72rem; font-weight: 600; letter-spacing: .08em;
  text-transform: uppercase; margin: 14px 0 6px; }
.file-card { display: flex; align-items: center; gap: 10px; }
.file-ico { width: 30px; height: 30px; border-radius: 8px; display: grid; place-items: center;
  font-size: .7rem; font-weight: 700; color: #fff; flex: none; }
.file-name { font-weight: 600; font-size: .92rem; line-height: 1.1; }
.file-meta { color: var(--muted); font-size: .74rem; line-height: 1.3; margin-top: 2px; }

/* ---------- earnings strip ---------- */
.earn { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 2px 0 14px; }
.earn-title { color: var(--muted); font-size: .72rem; font-weight: 600; letter-spacing: .08em;
  text-transform: uppercase; margin-right: 4px; }
.earn-chip { display: inline-flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 999px;
  background: var(--card); border: 1px solid var(--line); font-size: .84rem; animation: fadeUp .4s ease both; }
.earn-chip b { color: var(--text); }
.earn-tag { font-size: .72rem; font-weight: 600; padding: 2px 8px; border-radius: 999px; }
.earn-tag.pre { background: rgba(245,165,36,.16); color: #f5a524; }
.earn-tag.after { background: rgba(167,139,250,.18); color: #a78bfa; }
.earn-tag.mid, .earn-tag.na { background: rgba(148,163,184,.16); color: #94a3b8; }
.earn-sub { color: var(--muted); font-size: .78rem; }

/* ---------- mobile ---------- */
@media (max-width: 1100px) { .kpi-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 640px) {
  .block-container { padding-left: .9rem; padding-right: .9rem; }
  .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .kpi-card { padding: 12px 14px; border-radius: 14px; }
  .kpi-value, .kpi-card.hero .kpi-value { font-size: 1.25rem; }
  .period-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .brand-title { font-size: 1.2rem; }
  /* segmented controls (periods, classes) wrap instead of running off-screen */
  [data-testid="stButtonGroup"] > div { flex-wrap: wrap; row-gap: 6px; }
}
</style>
"""

_LOGO_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" '
             'stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l6-6 4 4 8-8"/>'
             '<path d="M15 7h6v6"/></svg>')

CLASS_ICON = {"stocks": ("ST", "#4f8cff"), "etf": ("ETF", "#22c3a6"),
              "crypto": ("CR", "#f5a524"), "bond": ("BTP", "#a78bfa")}


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$"}


def cur_code() -> str:
    """Base currency of the aggregate views, chosen per viewer in the sidebar."""
    return st.session_state.get("base_ccy") or "EUR"


def cur_sym() -> str:
    return CURRENCY_SYMBOLS[cur_code()]


def money(v: float | None, sym: str | None = None, decimals: int = 0) -> str:
    """'€12,345' / '−€12,345' — sign before the currency, true minus sign.

    Without `sym` the viewer's base currency is used.
    """
    if sym is None:
        sym = cur_sym()
    if v is None:
        return "—"
    sign = "−" if v < 0 else ""
    return f"{sign}{sym}{abs(v):,.{decimals}f}"


def pct(v: float | None, decimals: int = 2) -> str:
    if v is None:
        return "—"
    return f"{'+' if v >= 0 else '−'}{abs(v):.{decimals}f}%"


def kpi(label: str, value: str, sub: str = "", positive: bool | None = None,
        hero: bool = False) -> str:
    tone = "pos" if positive is True else "neg" if positive is False else ""
    cls = " ".join(c for c in ("kpi-card", tone, "hero" if hero else "") if c)
    sub_cls = f"kpi-{tone}" if tone else ""
    sub_html = f'<div class="kpi-sub {sub_cls}">{sub}</div>' if sub else ""
    return (f'<div class="{cls}"><div class="kpi-label">{escape(label)}</div>'
            f'<div class="kpi-value">{value}</div>{sub_html}</div>')


def kpi_grid(cards: list[str]) -> None:
    """Responsive card row: 6 across on desktop, 3 on tablet, 2 on phone."""
    st.markdown(f'<div class="kpi-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def header(subtitle: str, live: bool) -> None:
    ts = datetime.now().strftime("%d %b %Y · %H:%M")
    status = ('<span class="dot live"></span>Live' if live
              else '<span class="dot"></span>Prezzi offline')
    st.markdown(
        f'<div class="brand"><div class="brand-left"><div class="brand-logo">{_LOGO_SVG}</div>'
        f'<div><div class="brand-title">JBD Portfolio</div>'
        f'<div class="brand-sub">{escape(subtitle)}</div></div></div>'
        f'<div class="brand-right"><span class="chip">{status}</span>'
        f'<span class="chip">{ts}</span></div></div>',
        unsafe_allow_html=True)


def sidebar_brand() -> None:
    st.markdown(f'<div class="side-brand"><div class="brand-logo">{_LOGO_SVG}</div>'
                '<b>JBD Portfolio</b></div>', unsafe_allow_html=True)


def side_section(title: str) -> None:
    st.markdown(f'<div class="side-section">{escape(title)}</div>', unsafe_allow_html=True)


def file_card(cls: str, label: str, meta: str) -> str:
    code, color = CLASS_ICON.get(cls, (label[:2].upper(), ACCENT))
    return (f'<div class="file-card"><div class="file-ico" style="background:{color}">{code}</div>'
            f'<div><div class="file-name">{escape(label)}</div>'
            f'<div class="file-meta">{escape(meta)}</div></div></div>')


_EARN_TAG = {"Pre-market": "pre", "After-market": "after", "In seduta": "mid", "Orario n.d.": "na"}


def earnings_strip(items: list[dict], values: dict[str, float]) -> None:
    """Chips for holdings reporting today / next business day."""
    if not items:
        st.markdown('<div class="earn"><span class="earn-title">Trimestrali</span>'
                    '<span class="earn-sub">nessun titolo in portafoglio oggi o domani</span></div>',
                    unsafe_allow_html=True)
        return
    chips = []
    for e in items:
        v = values.get(e["symbol"])
        sub = f'<span class="earn-sub">{money(v)} in portafoglio</span>' if v else ""
        chips.append(f'<span class="earn-chip"><b>{escape(e["symbol"])}</b>'
                     f'<span class="earn-sub">{escape(e["day"])}</span>'
                     f'<span class="earn-tag {_EARN_TAG[e["session"]]}">{escape(e["session"])}</span>'
                     f'{sub}</span>')
    st.markdown('<div class="earn"><span class="earn-title">Trimestrali</span>'
                + "".join(chips) + "</div>", unsafe_allow_html=True)
