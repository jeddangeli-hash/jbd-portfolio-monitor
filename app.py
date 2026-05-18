"""Streamlit dashboard — portfolio monitor. Inspired by Portfolio Performance feature set."""
from __future__ import annotations

import base64
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

import portfolio as pf
import prices as pr
import metrics as mt

# ---------- Page config ------------------------------------------------------

st.set_page_config(
    page_title="JBD Portfolio Monitor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS = """
<style>
.block-container { padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1500px; }
[data-testid="stMetricValue"] { font-size: 1.6rem; font-weight: 600; }
[data-testid="stMetricLabel"] { font-size: 0.82rem; color: #7a8290; }
[data-testid="stMetricDelta"] { font-size: 0.92rem; }
.kpi-card {
    background: linear-gradient(135deg, #1a1d29 0%, #232838 100%);
    border: 1px solid #2c3142;
    border-radius: 14px;
    padding: 16px 20px;
    margin-bottom: 8px;
}
.kpi-label { color: #8a93a3; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px; }
.kpi-value { color: #f1f3f6; font-size: 1.7rem; font-weight: 600; line-height: 1.1; }
.kpi-sub { font-size: 0.85rem; margin-top: 4px; }
.kpi-pos { color: #3ddc97; }
.kpi-neg { color: #ff6b81; }
.period-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin: 8px 0 18px; }
.period-cell {
    background: #181b25; border: 1px solid #262a38; border-radius: 10px;
    padding: 12px 14px; text-align: center;
}
.period-label { color: #7a8290; font-size: 0.72rem; letter-spacing: 0.06em; text-transform: uppercase; }
.period-value { font-size: 1.25rem; font-weight: 600; margin-top: 4px; }
h1, h2, h3 { font-weight: 600; letter-spacing: -0.01em; }
.stTabs [data-baseweb="tab-list"] { gap: 4px; }
.stTabs [data-baseweb="tab"] { padding: 10px 18px; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ---------- Sidebar ----------------------------------------------------------

DEFAULT_CSV = Path(__file__).parent / "data" / "portfolio.csv"

with st.sidebar:
    st.markdown("### 📊 Portfolio Monitor")
    st.caption("Yahoo CSV → live analytics")
    st.divider()

    uploaded = st.file_uploader("Upload Yahoo Finance CSV", type=["csv"])

    # When deployed to Streamlit Cloud, allow saving the uploaded CSV back to
    # the GitHub repo so every device sees the latest version. Requires three
    # secrets configured in Streamlit Cloud (Settings → Secrets):
    #   github_token = "ghp_..."     # PAT with `repo` scope
    #   github_repo  = "owner/repo"
    #   github_path  = "data/portfolio.csv"
    if uploaded is not None:
        try:
            token = st.secrets.get("github_token")
            repo = st.secrets.get("github_repo")
            path = st.secrets.get("github_path", "data/portfolio.csv")
            branch = st.secrets.get("github_branch", "main")
        except Exception:
            token = repo = path = branch = None
        if token and repo:
            if st.button("💾 Save this CSV to GitHub", use_container_width=True,
                         help="Persists this upload so iPhone + PC + any browser see it on reload"):
                content = uploaded.getvalue()
                api = f"https://api.github.com/repos/{repo}/contents/{path}"
                headers = {"Authorization": f"Bearer {token}",
                           "Accept": "application/vnd.github+json"}
                # Fetch current SHA (if file exists) so we can update rather than fail
                sha = None
                try:
                    r = requests.get(api, headers=headers, params={"ref": branch}, timeout=15)
                    if r.status_code == 200:
                        sha = r.json().get("sha")
                except Exception:
                    pass
                payload = {
                    "message": f"Update {path} via app",
                    "content": base64.b64encode(content).decode(),
                    "branch": branch,
                }
                if sha:
                    payload["sha"] = sha
                try:
                    r = requests.put(api, headers=headers, json=payload, timeout=20)
                    if r.status_code in (200, 201):
                        st.success("Saved to GitHub. Reload from any device to see it.")
                        st.cache_data.clear()
                    else:
                        st.error(f"GitHub save failed ({r.status_code}): "
                                 f"{r.json().get('message', r.text)[:200]}")
                except Exception as e:
                    st.error(f"GitHub save error: {e}")
        elif token is None and repo is None:
            st.caption("ℹ️ Set `github_token` + `github_repo` in Streamlit secrets "
                       "to enable cross-device save.")
    use_live = st.toggle("Fetch live prices", value=True)
    benchmark = st.selectbox("Benchmark", ["SPY", "QQQ", "VTI", "ACWI", "URTH", "None"], index=0)
    period = st.selectbox("History period", ["1mo", "3mo", "6mo", "1y", "2y", "5y"], index=3)
    rf_rate = st.slider("Risk-free rate (Sharpe)", 0.0, 0.10, 0.04, 0.005)
    st.divider()
    st.caption(f"Valuation date: **{date.today().isoformat()}**")
    if st.button("🔄 Refresh prices", use_container_width=True):
        st.cache_data.clear()
        pr.fetch_history.cache_clear()
        pr.fetch_metadata.cache_clear()
        pr.fetch_dividends.cache_clear()
        st.rerun()

# ---------- Load data --------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_tx(path_or_buf) -> pd.DataFrame:
    return pf.load_transactions(path_or_buf)

csv_source = uploaded if uploaded is not None else (str(DEFAULT_CSV) if DEFAULT_CSV.exists() else None)
if csv_source is None:
    st.markdown("# 📈 JBD Portfolio Monitor")
    st.info(
        "👋 **Welcome!** Upload your Yahoo Finance portfolio CSV from the sidebar to get started.\n\n"
        "Export from Yahoo Finance → your portfolio → ⋯ menu → **Export Transactions**, "
        "then drag the file into the **Upload Yahoo Finance CSV** control on the left."
    )
    st.caption("Expected columns: Symbol · Trade Date · Purchase Price · Quantity · Transaction Type "
               "(+ optional Current Price). Common Yahoo column aliases are supported automatically.")
    st.stop()

tx = load_tx(csv_source)
all_positions = pf.build_positions(tx)
positions = all_positions[all_positions["qty"] > 1e-6].reset_index(drop=True)
all_symbols_ever = sorted(tx["symbol"].unique().tolist())

# ---------- Live prices ------------------------------------------------------

@st.cache_data(ttl=120, show_spinner="Fetching live prices…")
def get_quotes(symbols: tuple[str, ...]) -> dict[str, dict]:
    return pr.fetch_quotes(list(symbols))

@st.cache_data(ttl=3600, show_spinner="Fetching history…")
def get_history(symbols: tuple[str, ...], period: str) -> pd.DataFrame:
    return pr.fetch_history_bulk(list(symbols), period=period)

@st.cache_data(ttl=3600, show_spinner="Fetching benchmark…")
def get_benchmark(sym: str, period: str) -> pd.Series:
    return pr.fetch_benchmark(sym, period=period)

@st.cache_data(ttl=86400, show_spinner="Fetching metadata…")
def get_metadata(symbols: tuple[str, ...]) -> pd.DataFrame:
    return pr.fetch_metadata_bulk(list(symbols))

@st.cache_data(ttl=86400, show_spinner=False)
def get_dividends(symbol: str) -> pd.Series:
    return pr.fetch_dividends(symbol)

@st.cache_data(ttl=21600, show_spinner=False)
def get_key_stats(symbol: str) -> dict:
    return pr.fetch_key_stats(symbol)

@st.cache_data(ttl=86400, show_spinner=False)
def get_annual_financials(symbol: str) -> pd.DataFrame:
    return pr.fetch_annual_financials(symbol)

@st.cache_data(ttl=86400, show_spinner=False)
def get_quarterly_financials(symbol: str) -> pd.DataFrame:
    return pr.fetch_quarterly_financials(symbol)

symbols = tuple(positions["symbol"].tolist())
quotes = get_quotes(symbols) if use_live else {}
price_map = {s: q["price"] for s, q in quotes.items()}
prev_map = {s: q["prev_close"] for s, q in quotes.items()}

positions = pf.enrich_with_prices(positions, price_map)
positions["prev_close"] = positions["symbol"].map(prev_map).fillna(positions["snapshot_price"])
positions["day_change_$"] = (positions["current_price"] - positions["prev_close"]) * positions["qty"]
positions["day_change_%"] = ((positions["current_price"] - positions["prev_close"])
                              / positions["prev_close"] * 100.0)

# Enrich all_positions too (closed positions have qty=0 → mkt_value=0, unrealized=0).
all_positions = pf.enrich_with_prices(all_positions, price_map)

# ---------- Top KPIs ---------------------------------------------------------

today = date.today()
total_mv = float(positions["market_value"].sum())
total_invested = float(positions["invested"].sum())
total_unrealized = float(positions["unrealized_pnl"].sum())
# Realized P&L must include CLOSED positions too (qty=0), not just currently-open ones.
total_realized = float(all_positions["realized_pnl"].sum())
day_change_total = float(positions["day_change_$"].sum())
day_change_pct = (day_change_total / total_mv * 100.0) if total_mv else 0.0
port_xirr = pf.portfolio_xirr(tx, positions, today)

st.markdown("# 📈 JBD Portfolio Monitor")
ts = datetime.now().strftime("%Y-%m-%d %H:%M")
src = "live (yfinance)" if use_live and quotes else "snapshot"
st.caption(f"As of {ts} · prices: **{src}** · {len(positions)} open positions · benchmark: **{benchmark}**")

def kpi(label: str, value: str, sub: str = "", positive: bool | None = None):
    cls = "kpi-pos" if positive is True else "kpi-neg" if positive is False else ""
    sub_html = f'<div class="kpi-sub {cls}">{sub}</div>' if sub else ""
    return f'<div class="kpi-card"><div class="kpi-label">{label}</div><div class="kpi-value">{value}</div>{sub_html}</div>'

total_pnl_all = total_unrealized + total_realized
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.markdown(kpi("Market Value", f"${total_mv:,.0f}", f"{len(positions)} positions"), unsafe_allow_html=True)
c2.markdown(kpi("Day Change", f"${day_change_total:,.0f}", f"{day_change_pct:+.2f}%",
                positive=day_change_total >= 0), unsafe_allow_html=True)
c3.markdown(kpi("Unrealized P&L", f"${total_unrealized:,.0f}",
                f"{(total_unrealized/total_invested*100 if total_invested else 0):+.2f}% on cost",
                positive=total_unrealized >= 0), unsafe_allow_html=True)
c4.markdown(kpi("Realized P&L", f"${total_realized:,.0f}",
                "from closed lots", positive=total_realized >= 0), unsafe_allow_html=True)
c5.markdown(kpi("Total P&L", f"${total_pnl_all:,.0f}",
                "realized + unrealized", positive=total_pnl_all >= 0), unsafe_allow_html=True)
c6.markdown(kpi("XIRR (MWR)", f"{port_xirr*100:.2f}%" if port_xirr else "n/a",
                "money-weighted, ann.", positive=(port_xirr or 0) >= 0), unsafe_allow_html=True)

st.markdown("")

# ---------- Build TWR series (used by multiple tabs) -------------------------

# Use ALL symbols ever traded (not just open) so the curve correctly reflects:
#   - the value of closed positions during the time they were held
#   - the cash inflow/outflow when they were sold
# Otherwise the "Total P&L over time" chart misses every closed position's realized P&L.
hist = get_history(tuple(all_symbols_ever), period) if pr.HAS_YF else pd.DataFrame()
twr_growth = pd.Series(dtype=float)
bench_growth = pd.Series(dtype=float)
value_series = pd.Series(dtype=float)

if not hist.empty:
    value_series, cf_series = mt.build_value_series(tx, hist)
    if not value_series.empty and (value_series > 0).any():
        # Trim leading zeros (before first holding)
        first_idx = value_series[value_series > 0].index[0]
        value_series = value_series.loc[first_idx:]
        cf_series = cf_series.loc[first_idx:]
        # Pin today's bar to the live mark-to-market so the chart matches the
        # top KPI's "Day Change". yfinance historical Close for today can be
        # stale (ffilled), partial intraday, or missing for foreign/illiquid
        # tickers, while live last_price covers all open positions consistently.
        if price_map:
            live_mv = float(positions["market_value"].sum())
            if live_mv > 0:
                value_series.iloc[-1] = live_mv
        twr_growth = mt.twr_curve(value_series, cf_series)
    if benchmark != "None":
        b = get_benchmark(benchmark, period)
        if not b.empty and not twr_growth.empty:
            b = b.reindex(twr_growth.index, method="ffill").dropna()
            bench_growth = mt.benchmark_growth(b)

# ---------- Tabs -------------------------------------------------------------

(tab_overview, tab_recap, tab_today, tab_pos, tab_perf, tab_daily, tab_holdings,
 tab_alloc, tab_risk, tab_div, tab_weekly, tab_lots) = st.tabs([
    "🎯 Overview", "📑 Recap", "📈 Today", "📋 Positions", "📊 Performance",
    "📅 Daily", "🏷 Holdings", "🗂 Allocation", "⚠️ Risk", "💰 Dividends",
    "📆 Weekly", "🧾 Lots"
])

# ---------- Overview ---------------------------------------------------------

with tab_overview:
    # ----- Industry breakdown with click-to-drill ---------------------------
    if pr.HAS_YF:
        st.subheader("By industry / sector")
        meta_ov = get_metadata(symbols)
        merged_ov = positions.merge(meta_ov, on="symbol", how="left")
        merged_ov["sector"] = merged_ov["sector"].fillna("Unknown")
        merged_ov["industry"] = merged_ov["industry"].fillna("Unknown")

        grouping = st.radio(
            "Group by", ["Sector", "Industry"],
            horizontal=True, key="ov_grouping",
        )
        group_col = "sector" if grouping == "Sector" else "industry"
        agg_ind = (merged_ov.groupby(group_col)
                            .agg(market_value=("market_value", "sum"),
                                 unrealized_pnl=("unrealized_pnl", "sum"),
                                 invested=("invested", "sum"),
                                 holdings=("symbol", "count"))
                            .reset_index()
                            .sort_values("market_value", ascending=False))
        agg_ind["pct"] = agg_ind["market_value"] / agg_ind["market_value"].sum() * 100.0
        agg_ind["return_pct"] = (agg_ind["unrealized_pnl"] / agg_ind["invested"] * 100.0).fillna(0)

        col_pie, col_detail = st.columns([1.1, 1.2])
        with col_pie:
            fig = px.pie(
                agg_ind, values="market_value", names=group_col, hole=0.55,
                color_discrete_sequence=px.colors.sequential.Tealgrn_r,
                custom_data=["holdings", "return_pct", "pct"],
            )
            fig.update_traces(
                textposition="outside", textinfo="label+percent",
                marker=dict(line=dict(color="#0e1117", width=2)),
                hovertemplate=("<b>%{label}</b><br>$%{value:,.0f}"
                               "<br>%{customdata[0]} holdings"
                               "<br>Return %{customdata[1]:+.1f}%<extra></extra>"),
            )
            fig.update_layout(showlegend=False, height=440,
                              margin=dict(t=20, b=10, l=10, r=10),
                              paper_bgcolor="rgba(0,0,0,0)")
            event = st.plotly_chart(
                fig, use_container_width=True,
                on_select="rerun",
                key=f"industry_pie_{group_col}",
            )

        with col_detail:
            # Determine selected industry/sector from pie click, else default to largest
            selected_group = None
            try:
                sel = None
                if event is not None:
                    sel = getattr(event, "selection", None)
                    if sel is None and isinstance(event, dict):
                        sel = event.get("selection")
                pts = []
                if sel is not None:
                    if isinstance(sel, dict):
                        pts = sel.get("points") or sel.get("point_indices") or []
                    else:
                        pts = getattr(sel, "points", []) or []
                if pts:
                    pt = pts[0]
                    # Try label directly, then fall back to point index → row lookup
                    lbl = None
                    if isinstance(pt, dict):
                        lbl = pt.get("label")
                        if not lbl:
                            idx = pt.get("point_number")
                            if idx is None:
                                idx = pt.get("pointNumber")
                            if idx is None:
                                idx = pt.get("point_index")
                            if idx is not None and 0 <= idx < len(agg_ind):
                                lbl = agg_ind.iloc[int(idx)][group_col]
                    else:
                        lbl = getattr(pt, "label", None)
                    selected_group = lbl
            except Exception:
                selected_group = None

            # Remember the last clicked group across reruns
            state_key = f"selected_group_{group_col}"
            if selected_group:
                st.session_state[state_key] = selected_group
            else:
                selected_group = st.session_state.get(state_key)
            if not selected_group and len(agg_ind):
                selected_group = agg_ind.iloc[0][group_col]

            # Selectbox fallback / explicit picker — always works even when
            # the pie's click event isn't firing.
            group_options = agg_ind[group_col].tolist()
            try:
                default_idx = group_options.index(selected_group) if selected_group in group_options else 0
            except ValueError:
                default_idx = 0
            picked = st.selectbox(
                f"{grouping}",
                group_options,
                index=default_idx,
                key=f"picker_{group_col}",
            )
            if picked != selected_group:
                st.session_state[state_key] = picked
            selected_group = picked

            st.markdown(f"##### {selected_group}")
            st.caption("Click a slice on the pie to switch.")

            detail = merged_ov[merged_ov[group_col] == selected_group][
                ["symbol", "market_value", "return_pct", "unrealized_pnl", "industry", "sector"]
            ].sort_values("market_value", ascending=False)
            if detail.empty:
                st.info("No holdings.")
            else:
                detail_show = detail.rename(columns={
                    "symbol": "Symbol",
                    "market_value": "Mkt Value",
                    "return_pct": "Return %",
                    "unrealized_pnl": "Unrlzd P&L",
                    "industry": "Industry",
                    "sector": "Sector",
                })
                # Drop the column that matches the grouping (it's all the same value)
                drop_col = "Sector" if group_col == "sector" else "Industry"
                if drop_col in detail_show.columns:
                    detail_show = detail_show.drop(columns=[drop_col])
                st.dataframe(
                    detail_show, use_container_width=True, hide_index=True,
                    column_config={
                        "Mkt Value": st.column_config.NumberColumn(format="$%.0f"),
                        "Return %": st.column_config.NumberColumn(format="%.1f%%"),
                        "Unrlzd P&L": st.column_config.NumberColumn(format="$%.0f"),
                    },
                    height=min(420, 38 * (len(detail_show) + 1)),
                )
                sub_mv = float(detail["market_value"].sum())
                sub_pnl = float(detail["unrealized_pnl"].sum())
                sub_inv = float(detail["market_value"].sum() - detail["unrealized_pnl"].sum())
                sub_ret = (sub_pnl / sub_inv * 100.0) if sub_inv > 0 else 0.0
                dd1, dd2, dd3 = st.columns(3)
                dd1.metric("Holdings", len(detail))
                dd2.metric("Mkt value", f"${sub_mv:,.0f}")
                dd3.metric("Return %", f"{sub_ret:+.2f}%")

        st.markdown("---")

    col_a, col_b = st.columns([1.1, 1])

    with col_a:
        st.subheader("Allocation")
        alloc = positions[["symbol", "market_value"]].copy()
        alloc["pct"] = alloc["market_value"] / total_mv * 100.0
        alloc = alloc.sort_values("market_value", ascending=False)
        big = alloc[alloc["pct"] >= 1.5].copy()
        small = alloc[alloc["pct"] < 1.5]
        if len(small) > 0:
            big = pd.concat([big, pd.DataFrame([{
                "symbol": f"Other ({len(small)})",
                "market_value": small["market_value"].sum(),
                "pct": small["pct"].sum(),
            }])], ignore_index=True)
        fig = px.pie(big, values="market_value", names="symbol", hole=0.55,
                     color_discrete_sequence=px.colors.sequential.Tealgrn_r)
        fig.update_traces(textposition="outside", textinfo="label+percent",
                          marker=dict(line=dict(color="#0e1117", width=2)))
        fig.update_layout(showlegend=False, height=420, margin=dict(t=10, b=10, l=10, r=10),
                          paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.subheader("Top movers (today)")
        movers = positions.dropna(subset=["day_change_%"]).copy()
        movers = movers.reindex(movers["day_change_%"].abs().sort_values(ascending=False).index).head(10)
        fig2 = go.Figure(go.Bar(
            x=movers["day_change_%"], y=movers["symbol"], orientation="h",
            marker_color=["#3ddc97" if v >= 0 else "#ff6b81" for v in movers["day_change_%"]],
            text=[f"{v:+.2f}%" for v in movers["day_change_%"]], textposition="outside",
        ))
        fig2.update_layout(height=420, margin=dict(t=10, b=10, l=10, r=40),
                           paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           xaxis_title="% change", yaxis=dict(autorange="reversed"),
                           xaxis=dict(zerolinecolor="#444"))
        st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Performance attribution (top contributors to total P&L)")
    # Use all_positions so closed-position realized gains/losses show up too.
    contrib = mt.position_contribution(all_positions).head(15)
    fig3 = go.Figure(go.Bar(
        x=contrib["total_pnl"], y=contrib["symbol"], orientation="h",
        marker_color=["#3ddc97" if v >= 0 else "#ff6b81" for v in contrib["total_pnl"]],
        text=[f"${v:,.0f} ({p:.1f}%)" for v, p in zip(contrib["total_pnl"], contrib["contribution_pct"])],
        textposition="outside",
    ))
    fig3.update_layout(height=480, margin=dict(t=10, b=10, l=10, r=140),
                       paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                       xaxis_title="Total P&L (realized + unrealized)",
                       yaxis=dict(autorange="reversed"),
                       xaxis=dict(zerolinecolor="#666"))
    st.plotly_chart(fig3, use_container_width=True)

# ---------- Recap -----------------------------------------------------------

with tab_recap:
    buy_tx = tx[tx["side"] == "BUY"]
    sell_tx = tx[tx["side"] == "SELL"]
    total_deployed = float((buy_tx["qty"] * buy_tx["price"]).sum())
    total_returned = float((sell_tx["qty"] * sell_tx["price"]).sum())
    net_cash_in = total_deployed - total_returned
    current_invested = float(positions["invested"].sum())

    # Position-level bucketing of gains vs losses
    real_g = float(all_positions[all_positions["realized_pnl"] > 0]["realized_pnl"].sum())
    real_l = float(all_positions[all_positions["realized_pnl"] < 0]["realized_pnl"].sum())
    unr_g = float(positions[positions["unrealized_pnl"] > 0]["unrealized_pnl"].sum())
    unr_l = float(positions[positions["unrealized_pnl"] < 0]["unrealized_pnl"].sum())
    net_real = real_g + real_l
    net_unr = unr_g + unr_l
    total_pnl_recap = net_real + net_unr
    return_on_deployed = (total_pnl_recap / total_deployed * 100.0) if total_deployed else 0.0

    st.subheader("Capital flow")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Total capital deployed", f"${total_deployed:,.0f}",
              help="Cumulative $ spent on all BUYs across history")
    r2.metric("Total capital returned", f"${total_returned:,.0f}",
              help="Cumulative $ received from all SELLs")
    r3.metric("Net cash invested", f"${net_cash_in:,.0f}",
              help="Deployed − Returned (net money put into the portfolio)")
    r4.metric("Current capital invested", f"${current_invested:,.0f}",
              help="Cost basis of currently-open positions")

    st.markdown("---")

    col_r, col_u = st.columns(2)
    with col_r:
        st.subheader("💵 Realized")
        rg, rl, rn = st.columns(3)
        rg.metric("Gains", f"${real_g:,.0f}",
                  help=f"{(all_positions['realized_pnl'] > 0).sum()} winning closed/partial positions")
        rl.metric("Losses", f"${real_l:,.0f}",
                  help=f"{(all_positions['realized_pnl'] < 0).sum()} losing closed/partial positions")
        rn.metric("Net realized", f"${net_real:,.0f}")

    with col_u:
        st.subheader("📈 Unrealized")
        ug, ul, un = st.columns(3)
        ug.metric("Gains", f"${unr_g:,.0f}",
                  help=f"{(positions['unrealized_pnl'] > 0).sum()} winning open positions")
        ul.metric("Losses", f"${unr_l:,.0f}",
                  help=f"{(positions['unrealized_pnl'] < 0).sum()} losing open positions")
        un.metric("Net unrealized", f"${net_unr:,.0f}")

    st.markdown("---")
    t1, t2, t3 = st.columns(3)
    t1.metric("Total P&L", f"${total_pnl_recap:,.0f}",
              help="Net realized + Net unrealized")
    t2.metric("Return on deployed capital", f"{return_on_deployed:+.2f}%")
    t3.metric("Portfolio XIRR", f"{port_xirr*100:.2f}%" if port_xirr else "—",
              help="Money-weighted annualized return")

    st.subheader("Gain / loss breakdown (visual)")
    bd = pd.DataFrame({
        "category": ["Realized gains", "Realized losses", "Unrealized gains", "Unrealized losses"],
        "value": [real_g, real_l, unr_g, unr_l],
    })
    fig = go.Figure(go.Bar(
        x=bd["category"], y=bd["value"],
        marker_color=["#3ddc97", "#ff6b81", "#3ddc97", "#ff6b81"],
        text=[f"${v:,.0f}" for v in bd["value"]],
        textposition="outside",
    ))
    fig.update_layout(height=360, margin=dict(t=20, b=10, l=10, r=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      yaxis=dict(gridcolor="#222", zerolinecolor="#666"),
                      xaxis=dict(showgrid=False))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Top winners / losers (total P&L)")
    contrib = mt.position_contribution(all_positions).copy()
    cw, cl = st.columns(2)
    with cw:
        st.markdown("**Winners**")
        st.dataframe(
            contrib[contrib["total_pnl"] > 0].head(10)[["symbol", "unrealized_pnl", "realized_pnl", "total_pnl"]],
            use_container_width=True, hide_index=True,
            column_config={
                "unrealized_pnl": st.column_config.NumberColumn("Unrealized", format="$%.0f"),
                "realized_pnl": st.column_config.NumberColumn("Realized", format="$%.0f"),
                "total_pnl": st.column_config.NumberColumn("Total", format="$%.0f"),
            },
        )
    with cl:
        st.markdown("**Losers**")
        st.dataframe(
            contrib[contrib["total_pnl"] < 0].sort_values("total_pnl").head(10)[
                ["symbol", "unrealized_pnl", "realized_pnl", "total_pnl"]],
            use_container_width=True, hide_index=True,
            column_config={
                "unrealized_pnl": st.column_config.NumberColumn("Unrealized", format="$%.0f"),
                "realized_pnl": st.column_config.NumberColumn("Realized", format="$%.0f"),
                "total_pnl": st.column_config.NumberColumn("Total", format="$%.0f"),
            },
        )

# ---------- Today (per-stock day move) --------------------------------------

with tab_today:
    st.subheader("Per-stock performance today")
    td = positions[["symbol", "qty", "current_price", "prev_close",
                    "day_change_$", "day_change_%", "market_value"]].copy()
    td = td.dropna(subset=["day_change_%"]).sort_values("day_change_%", ascending=False).reset_index(drop=True)

    total_today_dollar = float(td["day_change_$"].sum())
    weighted_pct = (total_today_dollar / float(td["market_value"].sum()) * 100.0) if len(td) else 0.0
    n_up = int((td["day_change_$"] > 0).sum())
    n_dn = int((td["day_change_$"] < 0).sum())

    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Total $ change today", f"${total_today_dollar:,.0f}")
    t2.metric("Value-weighted %", f"{weighted_pct:+.2f}%")
    t3.metric("Up / Down", f"{n_up} / {n_dn}")
    if len(td):
        t4.metric("Best", f"{td['symbol'].iloc[0]}",
                  f"{td['day_change_%'].iloc[0]:+.2f}%")

    st.subheader("$ contribution to today's move")
    bars = td.copy()
    bars["sort_key"] = bars["day_change_$"].abs()
    bars = bars.sort_values("sort_key", ascending=True).tail(40)
    fig = go.Figure(go.Bar(
        x=bars["day_change_$"], y=bars["symbol"], orientation="h",
        marker_color=["#3ddc97" if v >= 0 else "#ff6b81" for v in bars["day_change_$"]],
        text=[f"${v:,.0f} ({p:+.2f}%)" for v, p in zip(bars["day_change_$"], bars["day_change_%"])],
        textposition="outside",
    ))
    fig.update_layout(height=max(420, len(bars) * 22), margin=dict(t=20, b=10, l=10, r=140),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis_title="$ change today",
                      xaxis=dict(zerolinecolor="#666"),
                      yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Detail")
    show_td = td.rename(columns={
        "symbol": "Symbol", "qty": "Qty",
        "current_price": "Price", "prev_close": "Prev Close",
        "day_change_$": "$ Change", "day_change_%": "% Change",
        "market_value": "Mkt Value",
    })
    st.dataframe(
        show_td, use_container_width=True, hide_index=True,
        column_config={
            "Qty": st.column_config.NumberColumn(format="%.2f"),
            "Price": st.column_config.NumberColumn(format="$%.2f"),
            "Prev Close": st.column_config.NumberColumn(format="$%.2f"),
            "$ Change": st.column_config.NumberColumn(format="$%.2f"),
            "% Change": st.column_config.NumberColumn(format="%.2f%%"),
            "Mkt Value": st.column_config.NumberColumn(format="$%.0f"),
        },
        height=min(700, 38 * (len(show_td) + 1)),
    )

# ---------- Positions -------------------------------------------------------

with tab_pos:
    n_open = int((all_positions["qty"] > 1e-6).sum())
    n_closed = int((all_positions["qty"] <= 1e-6).sum())

    pos_filter = st.radio(
        "Show",
        [f"All ({len(all_positions)})", f"Open ({n_open})", f"Closed ({n_closed})"],
        horizontal=True,
    )
    if pos_filter.startswith("Open"):
        base = all_positions[all_positions["qty"] > 1e-6].copy()
    elif pos_filter.startswith("Closed"):
        base = all_positions[all_positions["qty"] <= 1e-6].copy()
    else:
        base = all_positions.copy()

    if base.empty:
        st.info("No positions in this category.")
    else:
        # ----- Lifetime stats per symbol (for closed-position metrics & since-sale columns)
        lifetime = {}
        for sym, grp in tx.groupby("symbol"):
            buys = grp[grp["side"] == "BUY"]
            sells = grp[grp["side"] == "SELL"]
            tb_qty = float(buys["qty"].sum())
            ts_qty = float(sells["qty"].sum())
            lifetime[sym] = {
                "avg_buy": float((buys["qty"] * buys["price"]).sum() / tb_qty) if tb_qty > 0 else None,
                "avg_sell": float((sells["qty"] * sells["price"]).sum() / ts_qty) if ts_qty > 0 else None,
                "gross_buys": float((buys["qty"] * buys["price"]).sum()),
                "total_sell_qty": ts_qty,
            }

        base["status"] = base["qty"].apply(lambda q: "Open" if q > 1e-6 else "Closed")
        live_day = positions.set_index("symbol")["day_change_%"].to_dict()
        base["day_change_%"] = base["symbol"].map(live_day)

        base["avg_buy_lifetime"] = base["symbol"].map(lambda s: lifetime.get(s, {}).get("avg_buy"))
        base["avg_sale_price"] = base["symbol"].map(lambda s: lifetime.get(s, {}).get("avg_sell"))
        base["total_sell_qty"] = base["symbol"].map(lambda s: lifetime.get(s, {}).get("total_sell_qty") or 0.0)
        base["gross_buys"] = base["symbol"].map(lambda s: lifetime.get(s, {}).get("gross_buys") or 0.0)

        # Display: for closed positions, show lifetime avg buy as "Avg Cost" and
        # realized / gross_buys as "Return %". For open, keep existing semantics.
        base["avg_cost_display"] = base.apply(
            lambda r: r["avg_cost"] if r["qty"] > 1e-6 else r["avg_buy_lifetime"],
            axis=1,
        )
        # Return % = (exit price - avg buy) / avg buy × 100
        # exit price = avg sale price for positions with any sales (trade return on sold portion)
        #            = current price for purely open positions with no sales (paper return)
        def _return_pct(r):
            ab = r["avg_buy_lifetime"]
            if ab is None or ab <= 0:
                return 0.0
            if r["total_sell_qty"] > 1e-6 and r["avg_sale_price"] is not None:
                return (r["avg_sale_price"] - ab) / ab * 100.0
            cp = r["current_price"]
            if pd.notna(cp) and cp:
                return (cp - ab) / ab * 100.0
            return 0.0
        base["return_pct_display"] = base.apply(_return_pct, axis=1)

        # $ / % change since sale (any position that has sold something)
        # Convention: positive = price went UP after sale (missed gains)
        #             negative = price went DOWN after sale (sold well)
        def _since_sale_dollar(r):
            if r["avg_sale_price"] is None or pd.isna(r["current_price"]) or r["total_sell_qty"] <= 0:
                return None
            return (r["current_price"] - r["avg_sale_price"]) * r["total_sell_qty"]
        def _since_sale_pct(r):
            if r["avg_sale_price"] is None or pd.isna(r["current_price"]) or r["avg_sale_price"] <= 0:
                return None
            return (r["current_price"] - r["avg_sale_price"]) / r["avg_sale_price"] * 100.0
        base["dollar_since_sale"] = base.apply(_since_sale_dollar, axis=1)
        base["pct_since_sale"] = base.apply(_since_sale_pct, axis=1)

        # Per-position XIRR (works for both open and closed)
        base["xirr"] = base.apply(
            lambda r: pf.position_xirr(
                r["symbol"], tx,
                r["current_price"] if r["qty"] > 1e-6 else None,
                r["qty"], today,
            ),
            axis=1,
        )
        base["xirr_pct"] = base["xirr"].apply(lambda x: f"{x*100:.1f}%" if x is not None else "—")
        base["total_pnl"] = base["unrealized_pnl"] + base["realized_pnl"]
        base = base.sort_values(["status", "total_pnl"], ascending=[True, False])

        display = base[[
            "symbol", "status", "qty", "avg_cost_display", "current_price", "market_value",
            "day_change_%", "unrealized_pnl", "realized_pnl", "total_pnl",
            "return_pct_display", "avg_sale_price", "dollar_since_sale", "pct_since_sale",
            "xirr_pct", "first_buy"
        ]].rename(columns={
            "symbol": "Symbol", "status": "Status",
            "qty": "Qty", "avg_cost_display": "Avg Cost",
            "current_price": "Price", "market_value": "Mkt Value",
            "day_change_%": "Day %", "unrealized_pnl": "Unrlzd P&L",
            "realized_pnl": "Rlzd P&L", "total_pnl": "Total P&L",
            "return_pct_display": "Return %",
            "avg_sale_price": "Avg Sale Price",
            "dollar_since_sale": "$ Since Sale",
            "pct_since_sale": "% Since Sale",
            "xirr_pct": "XIRR",
            "first_buy": "First Buy",
        })

        st.dataframe(
            display, use_container_width=True, hide_index=True,
            column_config={
                "Qty": st.column_config.NumberColumn(format="%.2f"),
                "Avg Cost": st.column_config.NumberColumn(format="$%.2f"),
                "Price": st.column_config.NumberColumn(format="$%.2f"),
                "Mkt Value": st.column_config.NumberColumn(format="$%.0f"),
                "Day %": st.column_config.NumberColumn(format="%.2f%%"),
                "Unrlzd P&L": st.column_config.NumberColumn(format="$%.0f"),
                "Rlzd P&L": st.column_config.NumberColumn(format="$%.0f"),
                "Total P&L": st.column_config.NumberColumn(format="$%.0f"),
                "Return %": st.column_config.NumberColumn(format="%.1f%%"),
                "Avg Sale Price": st.column_config.NumberColumn(format="$%.2f"),
                "$ Since Sale": st.column_config.NumberColumn(
                    format="$%.0f",
                    help="Positive = price went up after sale (missed gains). "
                         "Negative = price went down after sale (sold well).",
                ),
                "% Since Sale": st.column_config.NumberColumn(
                    format="%.2f%%",
                    help="Same sign convention as $ Since Sale.",
                ),
                "First Buy": st.column_config.DateColumn(format="YYYY-MM-DD"),
            },
            height=min(800, 38 * (len(display) + 1)),
        )
        # ----- Total row -----------------------------------------------------
        tot_mv = float(base["market_value"].sum())
        tot_unr = float(base["unrealized_pnl"].sum())
        tot_real = float(base["realized_pnl"].sum())
        tot_pnl = tot_unr + tot_real
        # Cost basis: cost of currently-held shares (open) + gross deployed on closed
        cost_basis_total = float(
            base.apply(lambda r: r["invested"] if r["qty"] > 1e-6 else r["gross_buys"], axis=1).sum()
        )
        tot_return_pct = (tot_pnl / cost_basis_total * 100.0) if cost_basis_total > 0 else 0.0

        ss_dollar_total = float(base["dollar_since_sale"].dropna().sum())
        sale_value_total = float((base["avg_sale_price"].fillna(0) * base["total_sell_qty"]).sum())
        tot_pct_since_sale = (ss_dollar_total / sale_value_total * 100.0) if sale_value_total > 0 else None

        # XIRR over the visible subset
        visible_symbols = set(base["symbol"].tolist())
        visible_tx = tx[tx["symbol"].isin(visible_symbols)]
        visible_open = base[base["qty"] > 1e-6]
        subset_xirr = pf.portfolio_xirr(visible_tx, visible_open, today) if not visible_tx.empty else None

        total_row = pd.DataFrame([{
            "Metric": f"TOTAL ({len(base)} positions)",
            "Mkt Value": tot_mv,
            "Unrlzd P&L": tot_unr,
            "Rlzd P&L": tot_real,
            "Total P&L": tot_pnl,
            "Return %": tot_return_pct,
            "$ Since Sale": ss_dollar_total if sale_value_total > 0 else None,
            "% Since Sale": tot_pct_since_sale,
            "XIRR": f"{subset_xirr*100:.1f}%" if subset_xirr is not None else "—",
        }])
        st.markdown("##### Totals")
        st.dataframe(
            total_row, use_container_width=True, hide_index=True,
            column_config={
                "Mkt Value": st.column_config.NumberColumn(format="$%.0f"),
                "Unrlzd P&L": st.column_config.NumberColumn(format="$%.0f"),
                "Rlzd P&L": st.column_config.NumberColumn(format="$%.0f"),
                "Total P&L": st.column_config.NumberColumn(format="$%.0f"),
                "Return %": st.column_config.NumberColumn(format="%.2f%%"),
                "$ Since Sale": st.column_config.NumberColumn(format="$%.0f"),
                "% Since Sale": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )

        csv_out = display.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download CSV", csv_out, "positions.csv", "text/csv")

# ---------- Performance -----------------------------------------------------

with tab_perf:
    if twr_growth.empty:
        st.warning("Need yfinance + a non-empty history to compute TWR. Install yfinance and pick a longer period.")
    else:
        # ----- Return decomposition: TWR vs MWR vs Simple ---------------------
        st.subheader("Return decomposition")
        st.caption("Different methods answer different questions — they're all 'correct' but measure different things.")

        # Recompute the same Total P&L the top KPI uses, so this matches.
        twr_itd = float(twr_growth.iloc[-1] - 1) if len(twr_growth) >= 2 else 0.0
        buy_tx_p = tx[tx["side"] == "BUY"]
        sell_tx_p = tx[tx["side"] == "SELL"]
        total_deployed_p = float((buy_tx_p["qty"] * buy_tx_p["price"]).sum())
        total_returned_p = float((sell_tx_p["qty"] * sell_tx_p["price"]).sum())
        net_cash_in_p = total_deployed_p - total_returned_p
        total_pnl_p = total_unrealized + total_realized
        simple_on_net = (total_pnl_p / net_cash_in_p * 100.0) if net_cash_in_p > 0 else 0.0
        simple_on_deployed = (total_pnl_p / total_deployed_p * 100.0) if total_deployed_p > 0 else 0.0

        rd1, rd2, rd3, rd4 = st.columns(4)
        rd1.metric("TWR (time-weighted)",
                   f"{twr_itd*100:+.2f}%",
                   help="Chain-linked daily returns — measures price moves only, "
                        "ignores when you added/withdrew cash. This is what S&P 500 "
                        "and other indices report. Compare to the benchmark below.")
        rd2.metric("XIRR (money-weighted, ann.)",
                   f"{port_xirr*100:.2f}%" if port_xirr else "—",
                   help="Annualized return on your actual cashflows, time-discounted. "
                        "Reflects timing skill (or lack thereof).")
        rd3.metric("Simple return on net cash",
                   f"{simple_on_net:+.2f}%",
                   help="Total P&L ÷ net cash invested (deployed − returned). "
                        "This is what Yahoo Finance's portfolio page shows — your "
                        "bank-statement view of how much money you've actually made.")
        rd4.metric("Simple return on deployed",
                   f"{simple_on_deployed:+.2f}%",
                   help="Total P&L ÷ gross capital deployed (sum of all buys, ignoring sells).")

        st.markdown("---")

        # Period returns grid
        prets = mt.period_returns_table(twr_growth)
        cells = []
        for label, val in prets.items():
            txt = f"{val*100:+.2f}%" if val is not None else "—"
            color = "#3ddc97" if (val or 0) >= 0 else "#ff6b81"
            cells.append(
                f'<div class="period-cell"><div class="period-label">{label}</div>'
                f'<div class="period-value" style="color:{color}">{txt}</div></div>'
            )
        st.markdown(f'<div class="period-grid">{"".join(cells)}</div>', unsafe_allow_html=True)

        # Risk row
        ann = mt.annualized_return(twr_growth)
        vol = mt.volatility(twr_growth)
        sh = mt.sharpe(twr_growth, rf=rf_rate)
        mdd = mt.max_drawdown(twr_growth)
        rk1, rk2, rk3, rk4 = st.columns(4)
        rk1.metric("Annualized TWR", f"{ann*100:.2f}%" if ann is not None else "—")
        rk2.metric("Volatility (ann.)", f"{vol*100:.2f}%" if vol is not None else "—")
        rk3.metric("Sharpe ratio", f"{sh:.2f}" if sh is not None else "—",
                   help=f"rf = {rf_rate*100:.1f}%")
        rk4.metric("Max drawdown", f"{mdd*100:.2f}%")

        # Portfolio return curve vs benchmark — toggleable
        chart_mode = st.radio(
            "Return measure for chart",
            ["TWR (time-weighted)", "Simple return on net cash"],
            horizontal=True, key="perf_chart_mode",
        )

        # Simple-return curve: pnl_t / net_cash_invested_t
        cum_deposits_curve = cf_series.cumsum()
        with np.errstate(divide="ignore", invalid="ignore"):
            simple_curve = (value_series - cum_deposits_curve) / cum_deposits_curve
        # Mask days where net cash invested ≤ 0 (undefined simple return)
        simple_curve = simple_curve.where(cum_deposits_curve > 1e-6)

        if chart_mode.startswith("TWR"):
            port_y = (twr_growth - 1) * 100
            port_label = "Portfolio (TWR)"
            sub = f"TWR vs {benchmark}" if benchmark != "None" else "TWR"
        else:
            port_y = simple_curve * 100
            port_label = "Portfolio (simple return on net cash)"
            sub = f"Simple return vs {benchmark}" if benchmark != "None" else "Simple return"

        st.subheader(sub)
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=port_y.index, y=port_y.values, mode="lines",
            line=dict(color="#3ddc97", width=2.4),
            fill="tozeroy", fillcolor="rgba(61,220,151,0.08)",
            name=port_label,
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:+.2f}%<extra></extra>",
        ))
        if not bench_growth.empty:
            fig.add_trace(go.Scatter(
                x=bench_growth.index, y=(bench_growth - 1) * 100, mode="lines",
                line=dict(color="#7c8eff", width=2, dash="dot"),
                name=benchmark,
                hovertemplate="%{x|%Y-%m-%d}<br>%{y:+.2f}%<extra></extra>",
            ))
        fig.add_hline(y=0, line_dash="dash", line_color="#666")
        fig.update_layout(height=440, margin=dict(t=10, b=10, l=10, r=10),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          yaxis_title="% return", xaxis=dict(showgrid=False),
                          yaxis=dict(gridcolor="#222", zerolinecolor="#444"),
                          legend=dict(orientation="h", yanchor="bottom", y=1.02))
        st.plotly_chart(fig, use_container_width=True)

        # Equity curve ($) — market value vs net capital invested
        st.subheader("Equity curve ($)")
        st.caption("Blue = market value of holdings. Amber = cumulative net cash invested "
                   "(buys − sells). Gap between them = mark-to-market total P&L.")
        cum_capital_curve = cf_series.cumsum()
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=value_series.index, y=value_series.values, mode="lines",
            line=dict(color="#7c8eff", width=2),
            fill="tozeroy", fillcolor="rgba(124,142,255,0.08)",
            name="Market value",
            hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra>Market value</extra>",
        ))
        fig2.add_trace(go.Scatter(
            x=cum_capital_curve.index, y=cum_capital_curve.values, mode="lines",
            line=dict(color="#f4b942", width=2, dash="dot"),
            name="Net capital invested",
            hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra>Net capital</extra>",
        ))
        fig2.update_layout(height=360, margin=dict(t=10, b=10, l=10, r=10),
                           paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           yaxis_title="$", xaxis=dict(showgrid=False),
                           yaxis=dict(gridcolor="#222"),
                           legend=dict(orientation="h", yanchor="bottom", y=1.02))
        st.plotly_chart(fig2, use_container_width=True)

        # Cumulative absolute $ P&L over time
        st.subheader("Total P&L over time ($)")
        st.caption("Mark-to-market: portfolio value minus net cash invested. "
                   "Positive = winning overall, negative = losing.")
        cum_deposits = cf_series.cumsum()
        total_pnl_curve = value_series - cum_deposits

        # Split into positive and negative portions for two-tone fill
        pos = total_pnl_curve.where(total_pnl_curve >= 0)
        neg = total_pnl_curve.where(total_pnl_curve < 0)

        fig3 = go.Figure()
        # Positive (green) fill
        fig3.add_trace(go.Scatter(
            x=total_pnl_curve.index, y=pos.fillna(0).values,
            mode="lines", line=dict(color="rgba(0,0,0,0)"),
            fill="tozeroy", fillcolor="rgba(61,220,151,0.22)",
            name="Winning", showlegend=False, hoverinfo="skip",
        ))
        # Negative (red) fill
        fig3.add_trace(go.Scatter(
            x=total_pnl_curve.index, y=neg.fillna(0).values,
            mode="lines", line=dict(color="rgba(0,0,0,0)"),
            fill="tozeroy", fillcolor="rgba(255,107,129,0.22)",
            name="Losing", showlegend=False, hoverinfo="skip",
        ))
        # The actual line
        fig3.add_trace(go.Scatter(
            x=total_pnl_curve.index, y=total_pnl_curve.values,
            mode="lines", line=dict(color="#e8edf5", width=2),
            name="Total P&L",
            hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra></extra>",
        ))
        fig3.add_hline(y=0, line_dash="dash", line_color="#666")
        # Mark peak and trough
        peak_idx = total_pnl_curve.idxmax()
        trough_idx = total_pnl_curve.idxmin()
        fig3.add_trace(go.Scatter(
            x=[peak_idx, trough_idx],
            y=[total_pnl_curve.loc[peak_idx], total_pnl_curve.loc[trough_idx]],
            mode="markers+text",
            marker=dict(size=10, color=["#3ddc97", "#ff6b81"],
                        line=dict(color="#0e1117", width=2)),
            text=[f"Peak ${total_pnl_curve.loc[peak_idx]:,.0f}",
                  f"Trough ${total_pnl_curve.loc[trough_idx]:,.0f}"],
            textposition=["top center", "bottom center"],
            textfont=dict(color="#e8edf5"),
            showlegend=False, hoverinfo="skip",
        ))
        fig3.update_layout(height=380, margin=dict(t=20, b=10, l=10, r=10),
                           paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           yaxis_title="$ P&L", xaxis=dict(showgrid=False),
                           yaxis=dict(gridcolor="#222", zerolinecolor="#666"))
        st.plotly_chart(fig3, use_container_width=True)

        pk1, pk2, pk3, pk4 = st.columns(4)
        pk1.metric("Current P&L", f"${total_pnl_curve.iloc[-1]:,.0f}")
        pk2.metric("Peak P&L",
                   f"${total_pnl_curve.loc[peak_idx]:,.0f}",
                   help=f"on {peak_idx.date()}")
        pk3.metric("Trough P&L",
                   f"${total_pnl_curve.loc[trough_idx]:,.0f}",
                   help=f"on {trough_idx.date()}")
        pk4.metric("Days winning",
                   f"{int((total_pnl_curve >= 0).sum())} / {len(total_pnl_curve)}")

# ---------- Daily (last 30 trading days) ------------------------------------

with tab_daily:
    if value_series.empty:
        st.warning("Need history to compute daily returns.")
    else:
        daily_mode = st.radio(
            "Return measure",
            ["Simple return on net cash", "TWR (time-weighted)"],
            horizontal=True, key="daily_mode",
        )
        daily_dol = mt.daily_dollar_change(value_series, cf_series)
        daily_twr = mt.daily_pct_change(value_series, cf_series)
        # Simple-return daily %: today's market $ change ÷ net cash invested today.
        cum_dep_daily = cf_series.cumsum()
        with np.errstate(divide="ignore", invalid="ignore"):
            daily_simple = daily_dol / cum_dep_daily
        daily_simple = daily_simple.where(cum_dep_daily > 1e-6, 0.0).fillna(0.0)

        daily_pct = daily_simple if daily_mode.startswith("Simple") else daily_twr
        pct_label = "Simple % (on net cash)" if daily_mode.startswith("Simple") else "TWR %"

        n_days = st.slider("Show last N trading days", 5, 90, 30)
        idx = daily_pct.index[-n_days:]
        df_daily = pd.DataFrame({
            "date": idx,
            "pct": (daily_pct.loc[idx].values * 100),
            "dollar": daily_dol.loc[idx].values,
            "value": value_series.loc[idx].values,
        })
        df_daily = df_daily.iloc[::-1].reset_index(drop=True)

        # Summary row
        total_dollar = float(df_daily["dollar"].sum())
        if daily_mode.startswith("Simple"):
            # Δ in cumulative simple-return over the window
            cum_pnl = (value_series - cum_dep_daily)
            with np.errstate(divide="ignore", invalid="ignore"):
                cum_simple = (cum_pnl / cum_dep_daily).where(cum_dep_daily > 1e-6)
            window_growth = float(cum_simple.loc[idx[-1]] - cum_simple.loc[idx[0]])
            window_label = f"{n_days}d Δ simple return"
        else:
            window_growth = (1.0 + daily_twr.loc[idx]).prod() - 1.0
            window_label = f"{n_days}d TWR"
        best = df_daily.loc[df_daily["pct"].idxmax()]
        worst = df_daily.loc[df_daily["pct"].idxmin()]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric(f"{n_days}d $ change (market)", f"${total_dollar:,.0f}")
        m2.metric(window_label, f"{window_growth*100:+.2f}%")
        m3.metric("Best day",
                  f"{best['pct']:+.2f}%",
                  f"${best['dollar']:,.0f} · {best['date'].date()}")
        m4.metric("Worst day",
                  f"{worst['pct']:+.2f}%",
                  f"${worst['dollar']:,.0f} · {worst['date'].date()}")

        st.subheader(f"Daily {pct_label} — last {n_days} trading days")
        bars = df_daily.iloc[::-1]  # back to chronological for chart
        fig = go.Figure(go.Bar(
            x=bars["date"], y=bars["pct"],
            marker_color=["#3ddc97" if v >= 0 else "#ff6b81" for v in bars["pct"]],
            text=[f"{v:+.2f}%<br>${d:,.0f}" for v, d in zip(bars["pct"], bars["dollar"])],
            textposition="outside",
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:.2f}%<br>$%{customdata:,.0f}<extra></extra>",
            customdata=bars["dollar"],
        ))
        fig.update_layout(height=420, margin=dict(t=20, b=10, l=10, r=10),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          yaxis_title="% return", xaxis=dict(showgrid=False),
                          yaxis=dict(gridcolor="#222", zerolinecolor="#444"))
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Detail")
        df_show = df_daily.copy()
        df_show["date"] = pd.to_datetime(df_show["date"]).dt.date
        st.dataframe(
            df_show, use_container_width=True, hide_index=True,
            column_config={
                "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
                "pct": st.column_config.NumberColumn("Return %", format="%.2f%%"),
                "dollar": st.column_config.NumberColumn("$ change", format="$%.0f"),
                "value": st.column_config.NumberColumn("End-of-day value", format="$%.0f"),
            },
            height=min(700, 38 * (len(df_show) + 1)),
        )

# ---------- Holdings (per-symbol with buy/sell markers) ---------------------

with tab_holdings:
    if not pr.HAS_YF:
        st.warning("yfinance required.")
    else:
        col_pick, col_period = st.columns([3, 1])
        with col_pick:
            include_closed = st.checkbox("Include closed positions", value=True)
            options = all_symbols_ever if include_closed else list(positions["symbol"])
            selected = st.selectbox("Symbol", options, index=0 if options else None)
        with col_period:
            holding_period = st.selectbox("Period", ["6mo", "1y", "2y", "5y", "max"], index=2)

        if selected:
            with st.spinner(f"Loading {selected}…"):
                h = pr.fetch_history(selected, period=holding_period)

            sym_tx = tx[tx["symbol"] == selected].sort_values("trade_date").copy()
            buys = sym_tx[sym_tx["side"] == "BUY"]
            sells = sym_tx[sym_tx["side"] == "SELL"]

            # Position summary for this symbol
            pos_row = all_positions[all_positions["symbol"] == selected]
            cur_qty = float(pos_row["qty"].iloc[0]) if not pos_row.empty else 0.0
            cur_inv = float(pos_row["invested"].iloc[0]) if not pos_row.empty else 0.0
            cur_real = float(pos_row["realized_pnl"].iloc[0]) if not pos_row.empty else 0.0
            cur_price = price_map.get(selected) or (h["close"].iloc[-1] if not h.empty else None)
            mkt_value = cur_qty * cur_price if cur_price else 0.0
            unreal = mkt_value - cur_inv
            sym_xirr = pf.position_xirr(selected, tx, cur_price, cur_qty, today)

            gain_pct = (unreal / cur_inv * 100) if cur_inv > 1e-6 else 0.0
            total_pnl_sym = unreal + cur_real
            # Lifetime stats for this symbol
            sym_buys = sym_tx[sym_tx["side"] == "BUY"]
            sym_sells = sym_tx[sym_tx["side"] == "SELL"]
            total_buy_qty = float(sym_buys["qty"].sum())
            total_sell_qty = float(sym_sells["qty"].sum())
            avg_buy_lifetime = (float((sym_buys["qty"] * sym_buys["price"]).sum() / total_buy_qty)
                                if total_buy_qty > 0 else None)
            avg_sale_price = (float((sym_sells["qty"] * sym_sells["price"]).sum() / total_sell_qty)
                              if total_sell_qty > 0 else None)
            gross_buys = float((sym_buys["qty"] * sym_buys["price"]).sum())

            # If closed, override avg-cost display with lifetime avg buy
            avg_cost_show = (cur_inv / cur_qty) if cur_qty > 1e-6 else avg_buy_lifetime

            # Company description (yfinance fundamentals — same fetch reused below)
            key_top = get_key_stats(selected)
            company_name = key_top.get("long_name") or selected
            sector = key_top.get("sector") or "—"
            industry = key_top.get("industry") or "—"
            country = key_top.get("country") or "—"
            website = key_top.get("website")
            employees = key_top.get("employees")
            mcap = key_top.get("market_cap")
            summary = key_top.get("summary")

            def _fmt_mcap(m):
                if not m:
                    return None
                if m >= 1e12:
                    return f"${m/1e12:.2f}T"
                if m >= 1e9:
                    return f"${m/1e9:.2f}B"
                if m >= 1e6:
                    return f"${m/1e6:.1f}M"
                return f"${m:,.0f}"

            badge_parts = [f"**{sector}**"]
            if industry and industry != "—":
                badge_parts.append(industry)
            if country and country != "—":
                badge_parts.append(country)
            if employees:
                badge_parts.append(f"{int(employees):,} employees")
            mcap_str = _fmt_mcap(mcap)
            if mcap_str:
                badge_parts.append(f"mkt cap {mcap_str}")

            head_col1, head_col2 = st.columns([3, 1])
            with head_col1:
                st.markdown(f"### {company_name} ({selected})")
                st.caption(" · ".join(badge_parts))
            with head_col2:
                if website:
                    st.markdown(f"🔗 [Website]({website})")

            if summary:
                with st.expander("About the company", expanded=True):
                    st.write(summary)
            else:
                st.caption("ℹ️ No company description available for this ticker.")

            st.markdown("---")

            sk1, sk2, sk3, sk4, sk5, sk6, sk7 = st.columns(7)
            sk1.metric("Qty", f"{cur_qty:,.2f}")
            sk2.metric("Avg cost", f"${avg_cost_show:.2f}" if avg_cost_show is not None else "—")
            sk3.metric("Mkt value", f"${mkt_value:,.0f}")
            sk4.metric("Unrealized P&L", f"${unreal:,.0f}", f"{gain_pct:+.2f}%")
            sk5.metric("Realized P&L", f"${cur_real:,.0f}")
            sk6.metric("Total P&L", f"${total_pnl_sym:,.0f}")
            sk7.metric("XIRR", f"{sym_xirr*100:.2f}%" if sym_xirr is not None else "—",
                       help="Money-weighted annualized return")

            # Since-sale section — only meaningful if anything was sold
            if total_sell_qty > 0 and cur_price is not None:
                st.markdown("---")
                st.markdown("##### Since-sale outlook")
                ss_dollar = (cur_price - avg_sale_price) * total_sell_qty
                ss_pct = (cur_price - avg_sale_price) / avg_sale_price * 100.0 if avg_sale_price > 0 else 0.0

                # Counterfactual: had I never sold, what would I have now?
                hold_qty = total_buy_qty   # everything I ever bought
                hold_value_now = hold_qty * cur_price
                hold_pnl = hold_value_now - gross_buys
                actual_pnl = unreal + cur_real
                missed = hold_pnl - actual_pnl   # > 0 means holding would've been better

                ss1, ss2, ss3, ss4 = st.columns(4)
                ss1.metric("Avg sale price", f"${avg_sale_price:.2f}",
                           help=f"{total_sell_qty:,.0f} shares sold, weighted average")
                ss2.metric("$ since sale", f"${ss_dollar:,.0f}",
                           help="Positive = price went up since sale (missed gains). "
                                "Negative = price went down since (sold well).")
                ss3.metric("% since sale", f"{ss_pct:+.2f}%")
                ss4.metric("If you'd held all", f"${hold_value_now:,.0f}",
                           f"{missed:+,.0f} vs actual",
                           help=f"Value today if you'd never sold ({hold_qty:,.0f} shares × "
                                f"${cur_price:.2f}). The delta shows how much you missed "
                                f"(positive) or saved (negative) by selling.")

            # ----- Key data ----------------------------------------------------
            st.markdown("---")
            st.markdown("##### Key data")
            with st.spinner("Loading fundamentals…"):
                key = get_key_stats(selected)
                ann_fin = get_annual_financials(selected)
                qtr_fin = get_quarterly_financials(selected)

            def _fmt_num(n):
                if n is None or pd.isna(n):
                    return "—"
                return f"{n:.2f}"

            def _rec_label(key_val, mean_val):
                if not key_val:
                    if mean_val is None or pd.isna(mean_val):
                        return "—"
                    # Yahoo scale: 1=Strong Buy … 5=Strong Sell
                    if mean_val < 1.5:
                        return "Strong Buy"
                    if mean_val < 2.5:
                        return "Buy"
                    if mean_val < 3.5:
                        return "Hold"
                    if mean_val < 4.5:
                        return "Sell"
                    return "Strong Sell"
                return str(key_val).replace("_", " ").title()

            target = key.get("target_mean")
            upside = ((target - cur_price) / cur_price * 100) if (target and cur_price) else None

            k1, k2, k3, k4, k5, k6 = st.columns(6)
            k1.metric("Trailing P/E", _fmt_num(key.get("trailing_pe")))
            k2.metric("Forward P/E", _fmt_num(key.get("forward_pe")))
            k3.metric("PEG", _fmt_num(key.get("peg_ratio")))
            k4.metric("Analyst target",
                      f"${target:.2f}" if target else "—",
                      f"{upside:+.1f}% upside" if upside is not None else None)
            k5.metric("Recommendation",
                      _rec_label(key.get("recommendation_key"), key.get("recommendation_mean")),
                      help=f"Mean score: {key.get('recommendation_mean'):.2f}" if key.get("recommendation_mean") else None)
            k6.metric("# Analysts",
                      f"{int(key['n_analysts'])}" if key.get("n_analysts") else "—")

            # Analyst target range bar (low / mean / high vs current price)
            t_low = key.get("target_low")
            t_high = key.get("target_high")
            if all(v is not None and not pd.isna(v) for v in [t_low, target, t_high, cur_price]):
                fig_t = go.Figure()
                fig_t.add_trace(go.Scatter(
                    x=[t_low, t_high], y=[0, 0], mode="lines",
                    line=dict(color="#3a4258", width=10), name="Analyst range",
                    showlegend=False, hoverinfo="skip",
                ))
                fig_t.add_trace(go.Scatter(
                    x=[t_low, target, t_high], y=[0, 0, 0],
                    mode="markers+text",
                    marker=dict(size=[14, 18, 14],
                                color=["#7c8eff", "#3ddc97", "#7c8eff"],
                                line=dict(color="#0e1117", width=2)),
                    text=[f"Low ${t_low:.2f}", f"Mean ${target:.2f}", f"High ${t_high:.2f}"],
                    textposition=["bottom center", "top center", "bottom center"],
                    textfont=dict(color="#e8edf5"),
                    showlegend=False, hoverinfo="skip",
                ))
                fig_t.add_trace(go.Scatter(
                    x=[cur_price], y=[0], mode="markers+text",
                    marker=dict(size=16, color="#f4b942", symbol="diamond",
                                line=dict(color="#0e1117", width=2)),
                    text=[f"Now ${cur_price:.2f}"], textposition="top center",
                    textfont=dict(color="#f4b942"), name="Current",
                    showlegend=False, hoverinfo="skip",
                ))
                fig_t.update_layout(
                    height=130, margin=dict(t=30, b=30, l=30, r=30),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    yaxis=dict(visible=False, range=[-0.6, 0.6]),
                    xaxis=dict(showgrid=False, zeroline=False,
                               title="Analyst price targets vs current"),
                )
                st.plotly_chart(fig_t, use_container_width=True)

            # Annual & quarterly financials
            def _scale_axis(values):
                m = max(abs(v) for v in values if v is not None and not pd.isna(v)) if len(values) else 0
                if m >= 1e9:
                    return 1e9, "$B"
                if m >= 1e6:
                    return 1e6, "$M"
                return 1.0, "$"

            ff_col1, ff_col2 = st.columns(2)

            with ff_col1:
                st.markdown("**Annual revenue & EBITDA (last 5 years)**")
                if ann_fin.empty or "revenue" not in ann_fin.columns:
                    st.caption("No annual financial data available for this ticker.")
                else:
                    ann5 = ann_fin.tail(5).copy()
                    all_vals = list(ann5["revenue"].dropna())
                    if "ebitda" in ann5.columns:
                        all_vals += list(ann5["ebitda"].dropna())
                    scale, unit = _scale_axis(all_vals)
                    fig_a = go.Figure()
                    fig_a.add_trace(go.Bar(
                        name="Revenue",
                        x=[d.year if hasattr(d, "year") else str(d) for d in ann5.index],
                        y=(ann5["revenue"] / scale).values,
                        marker_color="#7c8eff",
                        text=[f"{v/scale:.1f}" for v in ann5["revenue"]],
                        textposition="outside",
                    ))
                    if "ebitda" in ann5.columns:
                        fig_a.add_trace(go.Bar(
                            name="EBITDA",
                            x=[d.year if hasattr(d, "year") else str(d) for d in ann5.index],
                            y=(ann5["ebitda"] / scale).values,
                            marker_color="#3ddc97",
                            text=[f"{v/scale:.1f}" if pd.notna(v) else "" for v in ann5["ebitda"]],
                            textposition="outside",
                        ))
                    fig_a.update_layout(
                        barmode="group", height=320,
                        margin=dict(t=30, b=10, l=10, r=10),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        yaxis_title=unit,
                        yaxis=dict(gridcolor="#222"), xaxis=dict(showgrid=False),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02),
                    )
                    st.plotly_chart(fig_a, use_container_width=True)

            with ff_col2:
                st.markdown("**Quarterly revenue & EBITDA (last 5 quarters)**")
                if qtr_fin.empty or "revenue" not in qtr_fin.columns:
                    st.caption("No quarterly financial data available for this ticker.")
                else:
                    q5 = qtr_fin.tail(5).copy()
                    all_vals = list(q5["revenue"].dropna())
                    if "ebitda" in q5.columns:
                        all_vals += list(q5["ebitda"].dropna())
                    scale, unit = _scale_axis(all_vals)
                    def _qlabel(d):
                        if hasattr(d, "year") and hasattr(d, "month"):
                            q = (d.month - 1) // 3 + 1
                            return f"Q{q} {d.year}"
                        return str(d)
                    labels = [_qlabel(d) for d in q5.index]
                    fig_q = go.Figure()
                    fig_q.add_trace(go.Bar(
                        name="Revenue", x=labels,
                        y=(q5["revenue"] / scale).values,
                        marker_color="#7c8eff",
                        text=[f"{v/scale:.1f}" if pd.notna(v) else "" for v in q5["revenue"]],
                        textposition="outside",
                    ))
                    if "ebitda" in q5.columns:
                        fig_q.add_trace(go.Bar(
                            name="EBITDA", x=labels,
                            y=(q5["ebitda"] / scale).values,
                            marker_color="#3ddc97",
                            text=[f"{v/scale:.1f}" if pd.notna(v) else "" for v in q5["ebitda"]],
                            textposition="outside",
                        ))
                    fig_q.update_layout(
                        barmode="group", height=320,
                        margin=dict(t=30, b=10, l=10, r=10),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        yaxis_title=unit,
                        yaxis=dict(gridcolor="#222"), xaxis=dict(showgrid=False),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02),
                    )
                    st.plotly_chart(fig_q, use_container_width=True)

            if h.empty:
                st.info(f"No price history available for {selected}.")
            else:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=h.index, y=h["close"], mode="lines",
                    line=dict(color="#7c8eff", width=2),
                    name="Price",
                    hovertemplate="%{x|%Y-%m-%d}<br>$%{y:.2f}<extra></extra>",
                ))

                def marker_size(qty_arr):
                    qmax = float(qty_arr.max()) if len(qty_arr) else 1.0
                    return [10 + 22 * (q / qmax) if qmax > 0 else 12 for q in qty_arr]

                if not buys.empty:
                    fig.add_trace(go.Scatter(
                        x=buys["trade_date"], y=buys["price"], mode="markers",
                        marker=dict(symbol="triangle-up", color="#3ddc97",
                                    size=marker_size(buys["qty"]),
                                    line=dict(color="#0e1117", width=1.5)),
                        name="Buy",
                        text=[f"BUY {q:,.0f} @ ${p:.2f}" for q, p in zip(buys["qty"], buys["price"])],
                        hovertemplate="%{text}<br>%{x|%Y-%m-%d}<extra></extra>",
                    ))
                if not sells.empty:
                    fig.add_trace(go.Scatter(
                        x=sells["trade_date"], y=sells["price"], mode="markers",
                        marker=dict(symbol="triangle-down", color="#ff6b81",
                                    size=marker_size(sells["qty"]),
                                    line=dict(color="#0e1117", width=1.5)),
                        name="Sell",
                        text=[f"SELL {q:,.0f} @ ${p:.2f}" for q, p in zip(sells["qty"], sells["price"])],
                        hovertemplate="%{text}<br>%{x|%Y-%m-%d}<extra></extra>",
                    ))
                # Avg cost reference line
                if cur_qty > 1e-6 and cur_inv > 0:
                    avg = cur_inv / cur_qty
                    fig.add_hline(y=avg, line_dash="dot", line_color="#aaa",
                                  annotation_text=f"Avg cost ${avg:.2f}",
                                  annotation_position="top right")

                fig.update_layout(
                    height=520, margin=dict(t=20, b=10, l=10, r=10),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    yaxis_title="$", xaxis=dict(showgrid=False),
                    yaxis=dict(gridcolor="#222"),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02),
                    title=f"{selected} — price + transactions",
                )
                st.plotly_chart(fig, use_container_width=True)

                # Per-trade table
                tt = sym_tx[["trade_date", "side", "qty", "price", "cashflow"]].copy()
                tt["trade_date"] = pd.to_datetime(tt["trade_date"]).dt.date
                tt["value"] = tt["qty"] * tt["price"]
                st.dataframe(
                    tt.sort_values("trade_date", ascending=False),
                    use_container_width=True, hide_index=True,
                    column_config={
                        "trade_date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
                        "side": "Side",
                        "qty": st.column_config.NumberColumn("Qty", format="%.2f"),
                        "price": st.column_config.NumberColumn("Price", format="$%.4f"),
                        "value": st.column_config.NumberColumn("$ value", format="$%.2f"),
                        "cashflow": st.column_config.NumberColumn("Cashflow", format="$%.2f"),
                    },
                )

# ---------- Allocation ------------------------------------------------------

with tab_alloc:
    if not pr.HAS_YF:
        st.warning("yfinance required for sector/country/currency classification.")
    else:
        meta = get_metadata(symbols)
        merged = positions.merge(meta, on="symbol", how="left")
        merged["sector"] = merged["sector"].fillna("Unknown")
        merged["country"] = merged["country"].fillna("Unknown")
        merged["currency"] = merged["currency"].fillna("USD")
        merged["quoteType"] = merged["quoteType"].fillna("EQUITY")

        groups = [
            ("Sector", "sector"),
            ("Country", "country"),
            ("Currency", "currency"),
            ("Asset type", "quoteType"),
        ]
        cols = st.columns(2)
        for i, (label, col) in enumerate(groups):
            with cols[i % 2]:
                st.subheader(label)
                agg = merged.groupby(col)["market_value"].sum().reset_index().sort_values("market_value", ascending=False)
                agg["pct"] = agg["market_value"] / agg["market_value"].sum() * 100
                fig = px.pie(agg, values="market_value", names=col, hole=0.5,
                             color_discrete_sequence=px.colors.sequential.Tealgrn_r)
                fig.update_traces(textposition="outside", textinfo="label+percent",
                                  marker=dict(line=dict(color="#0e1117", width=2)))
                fig.update_layout(showlegend=False, height=320,
                                  margin=dict(t=10, b=10, l=10, r=10),
                                  paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)

        st.subheader("Treemap (sector → holding)")
        tm = merged.copy()
        tm["sector"] = tm["sector"].fillna("Unknown")
        fig = px.treemap(
            tm, path=[px.Constant("Portfolio"), "sector", "symbol"],
            values="market_value", color="return_pct",
            color_continuous_scale="RdYlGn", color_continuous_midpoint=0,
            hover_data={"market_value": ":,.0f", "return_pct": ":.1f"},
        )
        fig.update_traces(textinfo="label+value+percent parent")
        fig.update_layout(height=520, margin=dict(t=10, b=10, l=10, r=10),
                          paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

# ---------- Risk ------------------------------------------------------------

with tab_risk:
    if twr_growth.empty:
        st.warning("Need history to compute risk metrics.")
    else:
        ann = mt.annualized_return(twr_growth)
        vol = mt.volatility(twr_growth)
        sh = mt.sharpe(twr_growth, rf=rf_rate)
        mdd = mt.max_drawdown(twr_growth)
        dd = mt.drawdown_series(twr_growth)
        current_dd = float(dd.iloc[-1]) if not dd.empty else 0.0

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Annualized TWR", f"{ann*100:.2f}%" if ann is not None else "—")
        c2.metric("Volatility (ann.)", f"{vol*100:.2f}%" if vol is not None else "—")
        c3.metric("Sharpe", f"{sh:.2f}" if sh is not None else "—")
        c4.metric("Max drawdown", f"{mdd*100:.2f}%")
        c5.metric("Current drawdown", f"{current_dd*100:.2f}%")

        st.subheader("Drawdown")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=dd.index, y=dd.values * 100, mode="lines",
            line=dict(color="#ff6b81", width=1.5),
            fill="tozeroy", fillcolor="rgba(255,107,129,0.15)",
            name="Drawdown",
        ))
        fig.update_layout(height=360, margin=dict(t=10, b=10, l=10, r=10),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          yaxis_title="% from peak", xaxis=dict(showgrid=False),
                          yaxis=dict(gridcolor="#222"))
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Daily return distribution")
        rets = mt.daily_returns(twr_growth) * 100
        fig2 = px.histogram(rets, nbins=50, color_discrete_sequence=["#3ddc97"])
        fig2.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10),
                           paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           xaxis_title="daily % return", yaxis_title="days",
                           showlegend=False, yaxis=dict(gridcolor="#222"))
        st.plotly_chart(fig2, use_container_width=True)

        # Per-position volatility
        if not hist.empty:
            st.subheader("Per-position volatility (annualized)")
            pos_rets = hist.pct_change().dropna(how="all")
            pos_vol = (pos_rets.std() * np.sqrt(252) * 100).reset_index()
            pos_vol.columns = ["symbol", "vol_%"]
            pos_vol = pos_vol.merge(positions[["symbol", "market_value"]], on="symbol", how="inner")
            pos_vol = pos_vol.sort_values("vol_%", ascending=True)
            fig3 = go.Figure(go.Bar(
                x=pos_vol["vol_%"], y=pos_vol["symbol"], orientation="h",
                marker_color="#7c8eff",
                text=[f"{v:.0f}%" for v in pos_vol["vol_%"]], textposition="outside",
            ))
            fig3.update_layout(height=max(360, len(pos_vol) * 18),
                               margin=dict(t=10, b=10, l=10, r=60),
                               paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                               xaxis_title="annualized volatility %",
                               yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig3, use_container_width=True)

# ---------- Dividends -------------------------------------------------------

with tab_div:
    if not pr.HAS_YF:
        st.warning("yfinance required.")
    else:
        st.caption("Dividends paid since first buy (per-share × qty held at ex-date).")
        rows = []
        for _, p in positions.iterrows():
            sym = p["symbol"]
            divs = get_dividends(sym)
            if divs.empty:
                continue
            first = pd.Timestamp(p["first_buy"])
            divs = divs[divs.index >= first]
            for ex_date, per_share in divs.items():
                rows.append({
                    "ex_date": ex_date.date() if hasattr(ex_date, "date") else ex_date,
                    "symbol": sym, "per_share": float(per_share),
                    "qty_held": float(p["qty"]),  # approx — uses current qty
                    "total": float(per_share) * float(p["qty"]),
                })
        if not rows:
            st.info("No dividend history found for current holdings.")
        else:
            div_df = pd.DataFrame(rows).sort_values("ex_date", ascending=False)
            total_div = div_df["total"].sum()
            yld = (total_div / total_mv * 100.0) if total_mv else 0.0

            d1, d2, d3 = st.columns(3)
            d1.metric("Total dividends (est.)", f"${total_div:,.0f}")
            d2.metric("Dividend yield (on MV)", f"{yld:.2f}%")
            d3.metric("Paying positions", f"{div_df['symbol'].nunique()}")

            by_sym = div_df.groupby("symbol")["total"].sum().reset_index().sort_values("total", ascending=False)
            fig = go.Figure(go.Bar(
                x=by_sym["total"], y=by_sym["symbol"], orientation="h",
                marker_color="#3ddc97",
                text=[f"${v:,.0f}" for v in by_sym["total"]], textposition="outside",
            ))
            fig.update_layout(height=max(300, len(by_sym) * 28),
                              margin=dict(t=10, b=10, l=10, r=60),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              xaxis_title="$ dividends", yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, use_container_width=True)

            st.dataframe(
                div_df, use_container_width=True, hide_index=True,
                column_config={
                    "ex_date": st.column_config.DateColumn("Ex-Date", format="YYYY-MM-DD"),
                    "per_share": st.column_config.NumberColumn("Per share", format="$%.4f"),
                    "qty_held": st.column_config.NumberColumn("Qty (current)", format="%.2f"),
                    "total": st.column_config.NumberColumn("Estimated $", format="$%.2f"),
                },
                height=400,
            )

# ---------- Weekly trade log ------------------------------------------------

with tab_weekly:
    st.subheader("Transactions by week")
    st.caption("For each trade: current price vs trade price, % move since, "
               "and whether the move went your way.")

    # Build the trade log with current prices and post-trade move
    tlog = tx.copy()
    tlog["trade_date"] = pd.to_datetime(tlog["trade_date"])
    # Current price priority: live quote → snapshot from CSV
    snapshot_price_map = (tx.dropna(subset=["snapshot_price"])
                            .sort_values("trade_date")
                            .drop_duplicates("symbol", keep="last")
                            .set_index("symbol")["snapshot_price"]
                            .to_dict())
    def _cur(sym: str) -> float | None:
        v = price_map.get(sym)
        if v is None or pd.isna(v):
            v = snapshot_price_map.get(sym)
        try:
            return float(v) if v is not None and not pd.isna(v) else None
        except (TypeError, ValueError):
            return None

    tlog["current_price"] = tlog["symbol"].map(_cur)
    tlog["move_pct"] = ((tlog["current_price"] - tlog["price"]) / tlog["price"]) * 100.0
    # "Worked out" = same direction as trade intent
    # BUY: good if price went up (move_pct > 0). SELL: good if price went down (move_pct < 0).
    tlog["worked_out"] = tlog.apply(
        lambda r: (r["move_pct"] >= 0) if r["side"] == "BUY"
                  else (r["move_pct"] <= 0) if pd.notna(r["move_pct"]) else None,
        axis=1,
    )
    # "Outcome $" — the post-trade $ benefit
    # BUY: qty × (current - price) — paper gain on the bought shares
    # SELL: qty × (price - current) — money saved by selling
    tlog["outcome_$"] = tlog.apply(
        lambda r: r["qty"] * (r["current_price"] - r["price"]) if r["side"] == "BUY"
                  else r["qty"] * (r["price"] - r["current_price"])
                  if pd.notna(r["current_price"]) else None,
        axis=1,
    )
    tlog["days_since"] = (pd.Timestamp(today) - tlog["trade_date"]).dt.days
    # Week starting Monday
    tlog["week_start"] = (tlog["trade_date"]
                          - pd.to_timedelta(tlog["trade_date"].dt.dayofweek, unit="d"))

    # Filter controls
    fc1, fc2, fc3 = st.columns([1.4, 1.2, 1.2])
    side_filter = fc1.radio("Side", ["All", "Buys only", "Sells only"], horizontal=True)
    worked_filter = fc2.radio("Outcome", ["All", "Worked out", "Didn't work"], horizontal=True)
    sort_order = fc3.radio("Sort", ["Newest first", "Oldest first"], horizontal=True)

    view = tlog.copy()
    if side_filter == "Buys only":
        view = view[view["side"] == "BUY"]
    elif side_filter == "Sells only":
        view = view[view["side"] == "SELL"]
    if worked_filter == "Worked out":
        view = view[view["worked_out"] == True]
    elif worked_filter == "Didn't work":
        view = view[view["worked_out"] == False]

    if view.empty:
        st.info("No transactions match the filter.")
    else:
        # Weekly summary block
        wk_summary = (view.groupby("week_start")
                          .agg(trades=("symbol", "count"),
                               buys=("side", lambda s: (s == "BUY").sum()),
                               sells=("side", lambda s: (s == "SELL").sum()),
                               deployed=("cashflow", lambda c: -c[c < 0].sum()),
                               returned=("cashflow", lambda c: c[c > 0].sum()),
                               outcome=("outcome_$", "sum"))
                          .reset_index())
        wk_summary["net_cash"] = wk_summary["deployed"] - wk_summary["returned"]

        st.markdown("##### Weekly summary")
        st.dataframe(
            wk_summary.sort_values("week_start", ascending=(sort_order == "Oldest first")),
            use_container_width=True, hide_index=True,
            column_config={
                "week_start": st.column_config.DateColumn("Week starting", format="YYYY-MM-DD"),
                "trades": st.column_config.NumberColumn("# Trades", format="%d"),
                "buys": st.column_config.NumberColumn("Buys", format="%d"),
                "sells": st.column_config.NumberColumn("Sells", format="%d"),
                "deployed": st.column_config.NumberColumn("$ Deployed", format="$%.0f"),
                "returned": st.column_config.NumberColumn("$ Returned", format="$%.0f"),
                "net_cash": st.column_config.NumberColumn("Net cash in", format="$%.0f"),
                "outcome": st.column_config.NumberColumn("Outcome since trade", format="$%.0f"),
            },
            height=min(420, 38 * (len(wk_summary) + 1)),
        )

        st.markdown("---")

        weeks = sorted(view["week_start"].unique(),
                       reverse=(sort_order == "Newest first"))
        for i, w in enumerate(weeks):
            wstart = pd.Timestamp(w)
            wend = wstart + pd.Timedelta(days=6)
            group = view[view["week_start"] == w].sort_values("trade_date")
            n = len(group)
            net = float(-group["cashflow"].sum())  # positive = net deployed
            net_str = f"deployed ${net:,.0f}" if net >= 0 else f"returned ${-net:,.0f}"
            outcome = float(group["outcome_$"].dropna().sum())
            outcome_arrow = "↑" if outcome >= 0 else "↓"
            header = (f"Week of {wstart.date()} → {wend.date()}  ·  "
                      f"{n} trade{'s' if n != 1 else ''}  ·  {net_str}  ·  "
                      f"outcome since: {outcome_arrow} ${outcome:,.0f}")

            with st.expander(header, expanded=(i < 3)):
                show = group[["trade_date", "symbol", "side", "qty", "price",
                              "current_price", "move_pct", "outcome_$",
                              "worked_out", "days_since"]].copy()
                show["trade_date"] = pd.to_datetime(show["trade_date"]).dt.date
                show["worked_out"] = show["worked_out"].map(
                    {True: "✅", False: "❌", None: "—"}
                ).fillna("—")
                show = show.rename(columns={
                    "trade_date": "Date", "symbol": "Symbol", "side": "Side",
                    "qty": "Qty", "price": "Trade Price",
                    "current_price": "Current", "move_pct": "% Move",
                    "outcome_$": "Outcome $", "worked_out": "Worked",
                    "days_since": "Days held",
                })
                st.dataframe(
                    show, use_container_width=True, hide_index=True,
                    column_config={
                        "Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                        "Qty": st.column_config.NumberColumn(format="%.2f"),
                        "Trade Price": st.column_config.NumberColumn(format="$%.4f"),
                        "Current": st.column_config.NumberColumn(format="$%.4f"),
                        "% Move": st.column_config.NumberColumn(format="%.2f%%"),
                        "Outcome $": st.column_config.NumberColumn(format="$%.0f"),
                        "Days held": st.column_config.NumberColumn(format="%d d"),
                    },
                )

# ---------- Lots ------------------------------------------------------------

with tab_lots:
    st.subheader("All transactions")
    raw = tx[["trade_date", "symbol", "side", "qty", "price", "cashflow"]].copy()
    raw["trade_date"] = pd.to_datetime(raw["trade_date"]).dt.date
    raw = raw.sort_values("trade_date", ascending=False).reset_index(drop=True)
    st.dataframe(
        raw, use_container_width=True, hide_index=True,
        column_config={
            "trade_date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
            "symbol": "Symbol", "side": "Side",
            "qty": st.column_config.NumberColumn("Qty", format="%.2f"),
            "price": st.column_config.NumberColumn("Price", format="$%.4f"),
            "cashflow": st.column_config.NumberColumn("Cashflow", format="$%.2f"),
        },
        height=600,
    )
