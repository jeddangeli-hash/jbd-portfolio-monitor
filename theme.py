"""Visual layer: CSS, Plotly template and small HTML components.

Kept out of app.py so the analytics code stays readable and the look can be
changed in one place. Colours mirror .streamlit/config.toml.
"""
from __future__ import annotations

from html import escape

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# ---------- Palette ----------------------------------------------------------

BG = "#0a0d14"
CARD = "#10141e"          # chart/card surface; also the pie/marker outline colour
TEXT = "#e6e9f0"
MUTED = "#8a93a6"
ACCENT = "#7c8eff"
ACCENT_2 = "#4cc9f0"
POS = "#3ddc97"
NEG = "#ff6b81"
AMBER = "#f4b942"
GRID = "rgba(255,255,255,0.05)"

# Ordered ramp for part-of-whole charts (pies, treemaps): cool → warm, so
# neighbouring slices stay distinguishable without a rainbow look.
PIE_SEQ = ["#7c8eff", "#5fa8ff", "#4cc9f0", "#3dd6c4", "#3ddc97", "#9ad98a",
           "#f4b942", "#ff9f6b", "#ff7f9a", "#c084fc", "#9aa4b8"]
# Loss → neutral → gain, for colour-by-return charts (treemap). The neutral
# midpoint sits just above the card surface so flat tiles still read as tiles.
DIVERGING = [[0.0, "#e5485f"], [0.5, "#1e2433"], [1.0, "#2fc58a"]]

# ---------- Plotly template --------------------------------------------------
# Charts are rendered with theme=None (see chart()), so this template is the
# single source of defaults. Explicit per-figure settings in app.py still win.

_axis = dict(
    gridcolor=GRID, linecolor="rgba(255,255,255,0.08)",
    zerolinecolor="rgba(255,255,255,0.14)", tickfont=dict(color=MUTED, size=11),
    title=dict(font=dict(color=MUTED, size=12)),
    showspikes=True, spikemode="across", spikesnap="cursor",
    spikethickness=1, spikedash="dot", spikecolor="rgba(230,233,240,0.35)",
)

pio.templates["jbd"] = go.layout.Template(
    # Outside bar labels may extend past the plot area instead of being clipped.
    data=dict(bar=[go.Bar(cliponaxis=False, textfont=dict(color="#c4cad6"))]),
    layout=dict(
        font=dict(family="Inter, system-ui, sans-serif", color="#aab2c5", size=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=[ACCENT, POS, AMBER, ACCENT_2, "#c084fc", "#ff9f6b", NEG, "#9aa4b8"],
        hoverlabel=dict(bgcolor="#161c2a", bordercolor="#2a3245",
                        font=dict(family="Inter, sans-serif", color=TEXT, size=12)),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#c4cad6", size=12)),
        xaxis=_axis,
        yaxis={**_axis, "showspikes": False},
        barcornerradius=5,
        extendpiecolors=False,   # cycle PIE_SEQ instead of fading into pastels
        bargap=0.28,
        hovermode="closest",
        title=dict(font=dict(family="Plus Jakarta Sans, Inter, sans-serif",
                             color=TEXT, size=15)),
    ),
)
pio.templates.default = "plotly_dark+jbd"

_CHART_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d", "toggleSpikelines"],
}


def money(value: float, symbol: str = "$") -> str:
    """'-$1,234' rather than Python's '$-1,234'."""
    sign = "-" if value < 0 else ""
    return f"{sign}{symbol}{abs(value):,.0f}"


def donut_center(value: str, label: str) -> dict:
    """Plotly annotation that puts a headline number in a donut's hole."""
    return dict(
        text=(f"<span style='font-size:20px;color:{TEXT};font-weight:700'>{value}</span>"
              f"<br><span style='font-size:11px;color:{MUTED}'>{label}</span>"),
        x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False,
        font=dict(family="Plus Jakarta Sans, Inter, sans-serif"),
    )


def chart(fig, **kwargs):
    """st.plotly_chart with the house style. Returns whatever Streamlit returns
    (the selection state when on_select is used)."""
    kwargs.pop("use_container_width", None)  # deprecated; width="stretch" instead
    kwargs.setdefault("width", "stretch")
    kwargs.setdefault("theme", None)          # let the jbd template apply, not Streamlit's
    kwargs.setdefault("config", _CHART_CONFIG)
    return st.plotly_chart(fig, **kwargs)


# ---------- CSS --------------------------------------------------------------

CSS = f"""
<style>
:root {{
  --bg: {BG}; --card: {CARD}; --text: {TEXT}; --muted: {MUTED};
  --accent: {ACCENT}; --accent2: {ACCENT_2}; --pos: {POS}; --neg: {NEG};
  --line: rgba(255,255,255,0.07); --line-strong: rgba(255,255,255,0.12);
}}

/* ---- canvas ---------------------------------------------------------- */
.stApp {{
  background:
    radial-gradient(900px 500px at 8% -10%, rgba(124,142,255,0.13), transparent 60%),
    radial-gradient(800px 480px at 100% 0%, rgba(76,201,240,0.08), transparent 60%),
    var(--bg);
  background-attachment: fixed;
}}
header[data-testid="stHeader"] {{
  background: rgba(10,13,20,0.55);
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
}}
.stAppDeployButton {{ display: none; }}
.block-container {{ padding-top: 4.2rem; padding-bottom: 3rem; max-width: 1560px; }}
.stMainBlockContainer {{ font-feature-settings: "cv11", "ss01"; }}

/* ---- motion ---------------------------------------------------------- */
@keyframes fadeUp {{ from {{ opacity: 0; transform: translateY(10px); }}
                     to   {{ opacity: 1; transform: none; }} }}
@keyframes pulse  {{ 0% {{ box-shadow: 0 0 0 0 rgba(61,220,151,0.55); }}
                     70% {{ box-shadow: 0 0 0 9px rgba(61,220,151,0); }}
                     100% {{ box-shadow: 0 0 0 0 rgba(61,220,151,0); }} }}
@keyframes drift  {{ 0% {{ background-position: 0% 50%; }}
                     50% {{ background-position: 100% 50%; }}
                     100% {{ background-position: 0% 50%; }} }}
.kpi-card, .period-cell, [data-testid="stMetric"],
[data-testid="stPlotlyChart"], .hero {{ animation: fadeUp .55s cubic-bezier(.2,.7,.2,1) both; }}
[data-testid="stColumn"]:nth-child(2) .kpi-card {{ animation-delay: .05s; }}
[data-testid="stColumn"]:nth-child(3) .kpi-card {{ animation-delay: .10s; }}
[data-testid="stColumn"]:nth-child(4) .kpi-card {{ animation-delay: .15s; }}
[data-testid="stColumn"]:nth-child(5) .kpi-card {{ animation-delay: .20s; }}
[data-testid="stColumn"]:nth-child(6) .kpi-card {{ animation-delay: .25s; }}
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ animation: none !important; transition: none !important; }}
}}

/* ---- hero ------------------------------------------------------------ */
.hero {{
  position: relative; overflow: hidden;
  display: flex; align-items: center; justify-content: space-between; gap: 24px;
  flex-wrap: wrap;
  padding: 22px 28px; margin: 0 0 16px;
  border-radius: 20px; border: 1px solid var(--line);
  background:
    linear-gradient(120deg, rgba(124,142,255,0.16), rgba(76,201,240,0.07) 45%,
                    rgba(61,220,151,0.06) 70%, rgba(124,142,255,0.12));
  background-size: 220% 220%;
  animation: fadeUp .55s ease both, drift 18s ease-in-out infinite;
}}
.hero::after {{
  content: ""; position: absolute; inset: 0; pointer-events: none;
  background: radial-gradient(500px 160px at 85% 0%, rgba(255,255,255,0.06), transparent 70%);
}}
.hero-eyebrow {{ color: var(--accent); font-size: .72rem; font-weight: 600;
  letter-spacing: .16em; text-transform: uppercase; margin-bottom: 6px; }}
.hero-title {{ font-family: 'Plus Jakarta Sans', Inter, sans-serif; font-weight: 800;
  font-size: 2.05rem; line-height: 1.1; letter-spacing: -0.025em; color: var(--text);
  margin: 0; padding: 0 !important; }}
.hero-title span {{ background: linear-gradient(90deg, var(--accent), var(--accent2));
  -webkit-background-clip: text; background-clip: text; color: transparent; }}
.hero-sub {{ color: var(--muted); font-size: .92rem; margin-top: 8px; }}
.hero-right {{ display: flex; flex-direction: column; align-items: flex-end; gap: 8px; z-index: 1; }}
.live-pill {{ display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 12px; border-radius: 999px; font-size: .78rem; font-weight: 600;
  color: var(--text); background: rgba(255,255,255,0.05); border: 1px solid var(--line-strong); }}
.live-dot {{ width: 8px; height: 8px; border-radius: 50%; background: var(--pos);
  animation: pulse 2s infinite; }}
.live-dot.off {{ background: var(--muted); animation: none; }}
.hero-date {{ color: var(--muted); font-size: .8rem; font-variant-numeric: tabular-nums; }}

/* ---- status chips ---------------------------------------------------- */
.chips {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 2px 0 16px; }}
.chip {{ display: inline-flex; align-items: center; gap: 6px; padding: 5px 11px;
  border-radius: 999px; font-size: .76rem; color: var(--muted);
  background: rgba(255,255,255,0.03); border: 1px solid var(--line); }}
.chip b {{ color: var(--text); font-weight: 600; }}

/* ---- KPI cards ------------------------------------------------------- */
.kpi-card {{
  position: relative; overflow: hidden;
  background: linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.015));
  border: 1px solid var(--line); border-radius: 16px;
  padding: 18px 20px 16px; margin-bottom: 10px; min-height: 124px;
  transition: transform .25s ease, border-color .25s ease, box-shadow .25s ease;
}}
.kpi-card::before {{
  content: ""; position: absolute; left: 0; right: 0; top: 0; height: 2px;
  background: linear-gradient(90deg, transparent, var(--kpi-accent, var(--accent)), transparent);
  opacity: .9;
}}
.kpi-card::after {{
  content: ""; position: absolute; width: 160px; height: 160px; right: -60px; top: -80px;
  background: radial-gradient(circle, var(--kpi-glow, rgba(124,142,255,0.16)), transparent 70%);
  pointer-events: none;
}}
.kpi-card:hover {{ transform: translateY(-3px); border-color: var(--line-strong);
  box-shadow: 0 14px 34px -14px rgba(0,0,0,0.65); }}
.kpi-card.pos {{ --kpi-accent: var(--pos); --kpi-glow: rgba(61,220,151,0.15); }}
.kpi-card.neg {{ --kpi-accent: var(--neg); --kpi-glow: rgba(255,107,129,0.15); }}
.kpi-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }}
.kpi-label {{ color: var(--muted); font-size: .72rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: .09em; }}
.kpi-icon {{ width: 30px; height: 30px; border-radius: 9px; display: grid; place-items: center;
  font-size: 15px; background: rgba(255,255,255,0.05); border: 1px solid var(--line); }}
.kpi-value {{ color: var(--text); font-family: 'Plus Jakarta Sans', Inter, sans-serif;
  font-size: 1.72rem; font-weight: 700; line-height: 1.1; letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums; white-space: nowrap; }}
.kpi-sub {{ display: inline-flex; align-items: center; gap: 5px; margin-top: 9px;
  font-size: .78rem; font-weight: 600; color: var(--muted); }}
.kpi-sub.kpi-pos, .kpi-sub.kpi-neg {{ padding: 3px 9px; border-radius: 999px; }}
.kpi-pos {{ color: var(--pos); }}
.kpi-neg {{ color: var(--neg); }}
.kpi-sub.kpi-pos {{ background: rgba(61,220,151,0.10); }}
.kpi-sub.kpi-neg {{ background: rgba(255,107,129,0.10); }}

/* ---- native st.metric as cards -------------------------------------- */
[data-testid="stMetric"] {{
  background: linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.012));
  border: 1px solid var(--line); border-radius: 14px; padding: 14px 18px;
  transition: border-color .25s ease, transform .25s ease;
}}
[data-testid="stMetric"]:hover {{ border-color: var(--line-strong); transform: translateY(-2px); }}
[data-testid="stMetricLabel"] p {{ color: var(--muted); font-size: .74rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: .08em; }}
[data-testid="stMetricValue"] {{ font-family: 'Plus Jakarta Sans', Inter, sans-serif;
  letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }}

/* ---- period grid ----------------------------------------------------- */
.period-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
  gap: 10px; margin: 8px 0 20px; }}
.period-cell {{ background: rgba(255,255,255,0.025); border: 1px solid var(--line);
  border-radius: 12px; padding: 13px 14px; text-align: center;
  transition: border-color .2s ease, background .2s ease; }}
.period-cell:hover {{ border-color: var(--line-strong); background: rgba(255,255,255,0.045); }}
.period-label {{ color: var(--muted); font-size: .68rem; font-weight: 600;
  letter-spacing: .1em; text-transform: uppercase; }}
.period-value {{ font-family: 'Plus Jakarta Sans', Inter, sans-serif; font-size: 1.22rem;
  font-weight: 700; margin-top: 4px; font-variant-numeric: tabular-nums; }}

/* ---- headings -------------------------------------------------------- */
.stMainBlockContainer h2 {{ letter-spacing: -0.02em; }}
.stMainBlockContainer h3 {{
  font-size: 1.05rem !important; letter-spacing: -0.01em; color: var(--text);
  display: flex; align-items: center; gap: 10px; padding-top: .9rem !important;
}}
.stMainBlockContainer h3::before {{
  content: ""; width: 4px; height: 1.05em; border-radius: 4px; flex: none;
  background: linear-gradient(180deg, var(--accent), var(--accent2));
}}
[data-testid="stCaptionContainer"] {{ color: var(--muted); }}
hr {{ border-color: var(--line) !important; margin: 1.4rem 0 !important; }}

/* ---- tabs → segmented pill bar -------------------------------------- */
.stTabs [data-baseweb="tab-list"] {{
  gap: 4px; padding: 5px; border-radius: 14px; overflow-x: auto; scrollbar-width: none;
  background: rgba(255,255,255,0.03); border: 1px solid var(--line);
}}
.stTabs [data-baseweb="tab-list"]::-webkit-scrollbar {{ display: none; }}
.stTabs [data-baseweb="tab"] {{
  height: auto; padding: 8px 15px; border-radius: 10px; white-space: nowrap;
  color: var(--muted); background: transparent; transition: all .2s ease;
}}
.stTabs [data-baseweb="tab"] p {{ font-size: .86rem; font-weight: 500; }}
.stTabs [data-baseweb="tab"]:hover {{ color: var(--text); background: rgba(255,255,255,0.05); }}
.stTabs [aria-selected="true"] {{
  color: var(--text) !important;
  background: linear-gradient(135deg, rgba(124,142,255,0.28), rgba(76,201,240,0.16)) !important;
  box-shadow: inset 0 0 0 1px rgba(124,142,255,0.35), 0 6px 18px -8px rgba(124,142,255,0.6);
}}
.stTabs [aria-selected="true"] p {{ font-weight: 600; }}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{ display: none; }}
.stTabs [data-baseweb="tab-panel"] {{ padding-top: 1.2rem; }}

/* ---- horizontal radios → pills -------------------------------------- */
div[role="radiogroup"][aria-orientation="horizontal"],
.stRadio div[role="radiogroup"]:has(> label + label) {{
  gap: 6px; flex-wrap: wrap;
}}
.stRadio div[role="radiogroup"] > label {{
  margin: 0 !important; padding: 6px 14px; border-radius: 999px;
  background: rgba(255,255,255,0.03); border: 1px solid var(--line);
  transition: all .2s ease; cursor: pointer;
}}
.stRadio div[role="radiogroup"] > label:hover {{ border-color: var(--line-strong); background: rgba(255,255,255,0.06); }}
.stRadio div[role="radiogroup"] > label > div:first-child {{ display: none; }}
.stRadio div[role="radiogroup"] > label p {{ font-size: .85rem; color: var(--muted); }}
.stRadio div[role="radiogroup"] > label:has(input:checked) {{
  background: linear-gradient(135deg, rgba(124,142,255,0.30), rgba(76,201,240,0.18));
  border-color: rgba(124,142,255,0.5);
}}
.stRadio div[role="radiogroup"] > label:has(input:checked) p {{ color: var(--text); font-weight: 600; }}

/* ---- charts, tables, expanders as cards ----------------------------- */
[data-testid="stPlotlyChart"] {{
  background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01)), {CARD};
  border: 1px solid var(--line); border-radius: 16px; padding: 10px 8px 4px;
  overflow: hidden; transition: border-color .25s ease;
}}
[data-testid="stPlotlyChart"]:hover {{ border-color: var(--line-strong); }}
.modebar {{ background: transparent !important; }}
[data-testid="stDataFrame"], [data-testid="stTable"] {{
  border: 1px solid var(--line); border-radius: 14px; overflow: hidden;
}}
[data-testid="stExpander"] details {{ border: 1px solid var(--line); border-radius: 14px;
  background: rgba(255,255,255,0.02); }}
[data-testid="stAlert"] {{ border-radius: 14px; border: 1px solid var(--line); }}

/* ---- buttons --------------------------------------------------------- */
.stButton > button, .stDownloadButton > button {{
  border: 1px solid var(--line-strong); background: rgba(255,255,255,0.04);
  font-weight: 600; transition: all .2s ease;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{
  border-color: var(--accent); color: var(--text);
  background: rgba(124,142,255,0.14); box-shadow: 0 6px 20px -10px rgba(124,142,255,0.8);
}}

/* ---- sidebar --------------------------------------------------------- */
section[data-testid="stSidebar"] .block-container {{ padding-top: 1.6rem; }}
section[data-testid="stSidebar"] h4 {{ font-size: .78rem !important; text-transform: uppercase;
  letter-spacing: .12em; color: var(--muted); font-weight: 700; }}
[data-testid="stFileUploaderDropzone"] {{ border-radius: 12px; border: 1px dashed var(--line-strong);
  background: rgba(255,255,255,0.02); padding: .6rem .8rem; }}
.brand {{ display: flex; align-items: center; gap: 12px; margin-bottom: 4px; }}
.brand-mark {{ width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center;
  font-family: 'Plus Jakarta Sans', sans-serif; font-weight: 800; font-size: .95rem; color: #0a0d14;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  box-shadow: 0 8px 24px -8px rgba(124,142,255,0.8); }}
.brand-name {{ font-family: 'Plus Jakarta Sans', sans-serif; font-weight: 700; font-size: 1.02rem;
  color: var(--text); line-height: 1.15; }}
.brand-tag {{ color: var(--muted); font-size: .76rem; }}

/* ---- login ----------------------------------------------------------- */
.login {{ max-width: 420px; margin: 9vh auto 18px; text-align: center; }}
.login .brand-mark {{ width: 56px; height: 56px; font-size: 1.2rem; margin: 0 auto 16px; border-radius: 16px; }}
.login h1 {{ font-size: 1.7rem; margin: 0 0 6px; letter-spacing: -0.02em; }}
.login p {{ color: var(--muted); margin: 0; }}

/* ---- small screens --------------------------------------------------- */
@media (max-width: 640px) {{
  .hero {{ padding: 20px; }}
  .hero-title {{ font-size: 1.55rem; }}
  .hero-right {{ align-items: flex-start; }}
  .kpi-value {{ font-size: 1.45rem; }}
}}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


# ---------- Icons ------------------------------------------------------------
# Lucide-style line icons (MIT), inlined so there is no extra network request.

def _svg(paths: str, color: str = ACCENT) -> str:
    return (f'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')


ICONS = {
    "wallet": _svg('<path d="M19 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0 0 4h14a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2"/><path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>'),
    "pulse": _svg('<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>', ACCENT_2),
    "trend": _svg('<path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/>', POS),
    "check": _svg('<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>', POS),
    "sigma": _svg('<path d="M18 7V4H6l6 8-6 8h12v-3"/>', AMBER),
    "gauge": _svg('<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>', "#c084fc"),
    "percent": _svg('<path d="M19 5 5 19"/><circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/>', ACCENT_2),
}


# ---------- Components -------------------------------------------------------
# Every helper returns or renders static HTML. Inputs are app-generated numbers
# and labels; they are escaped anyway because ticker names come from user CSVs.

def hero(title: str, accent: str, subtitle: str, live: bool, stamp: str) -> None:
    dot = "live-dot" if live else "live-dot off"
    status = "Live prices" if live else "Snapshot prices"
    st.markdown(
        f'<div class="hero"><div>'
        f'<div class="hero-eyebrow">Portfolio intelligence</div>'
        f'<h1 class="hero-title">{escape(title)} <span>{escape(accent)}</span></h1>'
        f'<div class="hero-sub">{escape(subtitle)}</div></div>'
        f'<div class="hero-right"><div class="live-pill"><span class="{dot}"></span>{status}</div>'
        f'<div class="hero-date">{escape(stamp)}</div></div></div>',
        unsafe_allow_html=True,
    )


def chips(items: list[tuple[str, str]]) -> None:
    """Row of 'label value' pills, e.g. [("Prices", "live"), ("Positions", "12")]."""
    html = "".join(f'<span class="chip">{escape(k)} <b>{escape(v)}</b></span>' for k, v in items)
    st.markdown(f'<div class="chips">{html}</div>', unsafe_allow_html=True)


def kpi(label: str, value: str, sub: str = "", positive: bool | None = None,
        icon: str = "", tooltip: str = "") -> str:
    """HTML for one KPI card. `positive` colours the accent line and delta pill."""
    tone = "pos" if positive is True else "neg" if positive is False else ""
    sub_html = ""
    if sub:
        arrow = "▲ " if positive is True else "▼ " if positive is False else ""
        sub_cls = f"kpi-{tone}" if tone else ""
        sub_html = f'<div class="kpi-sub {sub_cls}">{arrow}{escape(sub)}</div>'
    icon_html = f'<div class="kpi-icon">{icon}</div>' if icon else ""
    title = f' title="{escape(tooltip)}"' if tooltip else ""
    return (f'<div class="kpi-card {tone}"{title}><div class="kpi-top">'
            f'<div class="kpi-label">{escape(label)}</div>{icon_html}</div>'
            f'<div class="kpi-value">{escape(value)}</div>{sub_html}</div>')


def sidebar_brand() -> None:
    st.markdown(
        '<div class="brand"><div class="brand-mark">JBD</div><div>'
        '<div class="brand-name">Portfolio Monitor</div>'
        '<div class="brand-tag">Yahoo CSV → live analytics</div></div></div>',
        unsafe_allow_html=True,
    )


def login_header() -> None:
    st.markdown(
        '<div class="login"><div class="brand-mark">JBD</div>'
        '<h1>Portfolio Monitor</h1><p>Enter your password to continue</p></div>',
        unsafe_allow_html=True,
    )
