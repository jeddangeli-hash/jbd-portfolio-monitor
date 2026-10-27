"""Streamlit dashboard — portfolio monitor. Inspired by Portfolio Performance feature set."""
from __future__ import annotations

import io
import hmac
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import portfolio as pf
import prices as pr
import metrics as mt
import tax
import bonds
import storage
import trend
import ui

# ---------- Page config ------------------------------------------------------

st.set_page_config(
    page_title="JBD Portfolio",
    page_icon=str(Path(__file__).parent / "static" / "icon.png"),
    layout="wide",
    initial_sidebar_state="auto"  # collapsed on phones,
)
ui.inject_css()

# ---------- Auth gate --------------------------------------------------------

def _check_password() -> bool:
    """Return True once the visitor has entered the password from secrets.

    Fails closed: if `app_password` is missing the app renders nothing, so a
    typo'd or dropped secret can never silently publish the portfolio.
    """
    # st.secrets raises (not returns None) when no secrets file can be loaded,
    # so the whole read is guarded — a missing file must show the same friendly
    # message as a missing key, never a traceback.
    try:
        expected = st.secrets.get("app_password")
        visible = sorted(st.secrets.keys())
    except Exception:
        expected, visible = None, []

    if not expected:
        st.error(
            "🔒 `app_password` is not set. Add it in Streamlit Cloud → Settings → "
            "Secrets, or in `.streamlit/secrets.toml` when running locally."
        )
        # Key names only, never values: tells us typo vs. TOML-nesting vs.
        # secrets-not-loaded without exposing anything sensitive.
        st.caption(
            "Top-level keys Streamlit can currently see: "
            + (", ".join(f"`{k}`" for k in visible) if visible else "_none_")
        )
        return False

    if st.session_state.get("auth_ok"):
        return True

    def _submit() -> None:
        # The callback can fire twice for one entry (Enter, then blur — common on
        # iPhone). The first call already logged in and dropped the key, so the
        # second must neither crash on the missing key nor flip auth back off.
        if st.session_state.get("auth_ok"):
            return
        typed = str(st.session_state.get("auth_pw") or "")
        # compare_digest: constant-time, so timing can't leak the password.
        if hmac.compare_digest(typed, str(expected)):
            st.session_state["auth_ok"] = True
            st.session_state.pop("auth_pw", None)  # never keep the typed password
        else:
            st.session_state["auth_ok"] = False

    st.markdown("## 🔒 JBD Portfolio Monitor")
    st.text_input("Password", type="password", key="auth_pw", on_change=_submit)
    if st.session_state.get("auth_ok") is False:
        st.error("Wrong password.")
    return False


if not _check_password():
    st.stop()


# ---------- Sidebar ----------------------------------------------------------

ASSET_LABELS = {"stocks": "Stocks", "etf": "ETF", "crypto": "Crypto", "bond": "Bond"}


@st.cache_data(show_spinner=False)
def load_tx(content: bytes) -> pd.DataFrame:
    return pf.load_transactions(io.BytesIO(content))


def _holdings_summary(content: bytes) -> str:
    try:
        df = load_tx(content)
    except Exception as e:  # noqa: BLE001 — a bad saved file must not break the sidebar
        return f"⚠️ file non leggibile: {e}"
    last = df["trade_date"].max()
    last_txt = last.strftime("%d/%m/%Y") if pd.notna(last) else "—"
    return f"{df['symbol'].nunique()} titoli · ultima operazione {last_txt}"


# One saved CSV per class, loaded automatically (GitHub when configured, else
# data/<class>.csv). Cached in session_state so Streamlit's reruns don't hit
# GitHub on every click; a save updates the cache directly.
GH_CFG = storage.github_config(st.secrets)
saved_csv: dict[str, bytes | None] = st.session_state.setdefault("saved_csv", {})
for _cls in storage.CLASSES:
    if _cls not in saved_csv:
        try:
            saved_csv[_cls] = storage.load(_cls, GH_CFG)
        except Exception as e:  # noqa: BLE001 — not cached, so the next rerun retries
            st.sidebar.error(f"{ASSET_LABELS[_cls]}: {e}")


def _holdings_slot(cls: str) -> None:
    """Saved file with an ✖ to replace it; an uploader when empty or replacing.

    ✖ only opens the uploader — the saved file is overwritten when (and only
    when) a new, valid CSV is uploaded, so an accidental ✖ loses nothing.
    """
    label = ASSET_LABELS[cls]
    content = saved_csv.get(cls)
    replace_key = f"replace_{cls}"
    if content is not None and not st.session_state.get(replace_key):
        c1, c2 = st.columns([5, 1])
        c1.markdown(ui.file_card(cls, label, _holdings_summary(content)),
                    unsafe_allow_html=True)
        # Icon, not a "✖" glyph: the narrow column clips text labels.
        if c2.button("", icon=":material/close:", key=f"x_{cls}",
                     help=f"Sostituisci il file {label} con uno nuovo"):
            st.session_state[replace_key] = True
            st.rerun()
        return

    # Bumping the key after a save resets the uploader to empty.
    n_key = f"up_n_{cls}"
    up = st.file_uploader(f"{label} CSV", type=["csv"],
                          key=f"up_{cls}_{st.session_state.get(n_key, 0)}")
    if up is not None:
        data = up.getvalue()
        try:
            pf.load_transactions(io.BytesIO(data))  # validate before overwriting
        except Exception as e:  # noqa: BLE001
            st.error(f"File non valido: {e}")
        else:
            try:
                storage.save(cls, data, GH_CFG)
            except Exception as e:  # noqa: BLE001
                st.error(str(e))
            else:
                saved_csv[cls] = data
                st.session_state[replace_key] = False
                st.session_state[n_key] = st.session_state.get(n_key, 0) + 1
                st.session_state["flash"] = f"{label}: salvato «{up.name}»."
                st.rerun()
    if content is not None and st.button("Annulla", key=f"cancel_{cls}",
                                         use_container_width=True):
        st.session_state[replace_key] = False
        st.rerun()


with st.sidebar:
    ui.sidebar_brand()
    ui.side_section("Holdings")
    if msg := st.session_state.pop("flash", None):
        st.success(msg)
    for _cls in storage.CLASSES:
        _holdings_slot(_cls)
    if GH_CFG is None:
        st.caption("ℹ️ Salvataggio solo locale. Imposta `github_token` + `github_repo` "
                   "(repo **privato**) nei secrets per conservarli tra dispositivi.")
    ui.side_section("Impostazioni")
    st.segmented_control("Valuta", ["EUR", "USD"], default="EUR", key="base_ccy",
                         help="Valuta di Generale e Andamento (le viste per classe restano in valuta originale)")
    use_live = st.toggle("Fetch live prices", value=True)
    benchmark = st.selectbox("Benchmark", ["SPY", "QQQ", "VTI", "ACWI", "URTH", "None"], index=0)
    period = st.selectbox("History period", ["Dall'inizio", "1mo", "3mo", "6mo", "1y", "2y", "5y"],
                          index=0, help="Dall'inizio = dal primo trade della classe")
    rf_rate = st.slider("Risk-free rate (Sharpe)", 0.0, 0.10, 0.04, 0.005)

    # ----- Bond / BTP (manual, JSON-persisted) — loaded only on demand --------
    BOND_JSON = Path(__file__).parent / "data" / "bond.json"
    st.divider()
    ui.side_section("Bond / BTP")
    bond_list: list[bonds.Bond] = []
    inflation_assumed = 2.0
    if not st.session_state.get("bond_loaded"):
        if st.button("🏛️ Carica BTP", use_container_width=True,
                     help="Aggiunge i BTP al portafoglio (Generale + vista Bond)"):
            st.session_state["bond_loaded"] = True
            st.rerun()
    else:
        if st.button("Rimuovi BTP dalla vista", use_container_width=True):
            st.session_state["bond_loaded"] = False
            st.rerun()
        _bds = bonds.load_bonds_data(BOND_JSON)
        inflation_assumed = st.slider("Inflazione assunta (% per YTM nominale BTP reali)",
                                      0.0, 8.0, 2.0, 0.1, key="b_infl")
        _bond_inputs: list[dict] = []
        for _i, _bd in enumerate(_bds):
            with st.expander(f"Dati BTP · {_bd['isin']}", expanded=False):
                b_isin = st.text_input("ISIN", _bd["isin"], key=f"b_isin_{_i}")
                b_nominal = st.number_input("Nominale (EUR)", value=float(_bd["nominal"]),
                                            step=1000.0, key=f"b_nom_{_i}")
                b_load = st.number_input("Prezzo medio carico (base 100)",
                                         value=float(_bd["price_load"]),
                                         step=0.01, format="%.4f", key=f"b_load_{_i}")
                # Market price: live-fetchable. Use session_state so the Fetch button can
                # push a value into the widget without the value=/key= conflict.
                st.session_state.setdefault(f"b_market_{_i}", float(_bd["price_market"]))
                cpa, cpb = st.columns([2, 1])
                if cpb.button("Fetch live", help=f"yfinance ISIN {b_isin}", key=f"b_fetch_{_i}"):
                    _q = pr.fetch_quotes([b_isin])
                    _live = _q.get(b_isin, {}).get("price")
                    if _live:
                        st.session_state[f"b_market_{_i}"] = round(float(_live), 4)
                        st.success(f"Live {float(_live):.4f}")
                        st.rerun()
                    else:
                        st.warning("Prezzo live non trovato — uso il manuale.")
                b_market = cpa.number_input("Prezzo mercato (base 100)", step=0.01,
                                            format="%.4f", key=f"b_market_{_i}")
                b_real = st.checkbox("Cedola reale (indicizzato all'inflazione)",
                                     value=bool(_bd["coupon_real"]), key=f"b_real_{_i}")
                b_coupon = st.number_input("Cedola annua (%)", value=float(_bd["coupon_pct"]),
                                           step=0.05, key=f"b_coupon_{_i}")
                b_bullet = st.checkbox("Cedola unica a scadenza",
                                       value=bool(_bd["coupon_at_maturity"]),
                                       key=f"b_bullet_{_i}")
                b_lump = st.number_input("Cedola complessiva a scadenza (% nominale)",
                                         value=float(_bd["lump_coupon_pct"]), step=0.1,
                                         disabled=not b_bullet, key=f"b_lump_{_i}")
                b_freq = st.selectbox("Frequenza cedole/anno", [1, 2, 4],
                                      index=[1, 2, 4].index(int(_bd["frequency"])),
                                      key=f"b_freq_{_i}")
                b_accrued = st.number_input("Rateo in corso (EUR)", value=float(_bd["accrued"]),
                                            step=1.0, key=f"b_accr_{_i}")
                b_next = st.date_input("Prossima cedola",
                                       value=date.fromisoformat(str(_bd["next_coupon"])),
                                       key=f"b_next_{_i}")
                b_mat = st.date_input("Scadenza",
                                      value=date.fromisoformat(str(_bd["maturity"])),
                                      key=f"b_mat_{_i}")
            _bond_inputs.append({
                "isin": b_isin, "nominal": b_nominal, "price_load": b_load,
                "price_market": b_market, "coupon_pct": b_coupon, "frequency": b_freq,
                "accrued": b_accrued, "next_coupon": b_next, "maturity": b_mat,
                "currency": "EUR", "coupon_real": b_real, "coupon_at_maturity": b_bullet,
                "lump_coupon_pct": b_lump})
        if st.button("💾 Salva BTP", use_container_width=True):
            bonds.save_bonds_data(BOND_JSON, _bond_inputs)
            st.success("BTP salvati.")

        try:
            bond_list = [bonds.bond_from_dict(b) for b in _bond_inputs]
        except (ValueError, TypeError) as e:  # surface bad manual input, don't crash
            st.error(f"Bond input error: {e}")

    st.divider()
    st.caption(f"Valuation date: **{date.today().isoformat()}**")
    if st.button("🔄 Refresh prices", use_container_width=True):
        st.cache_data.clear()
        pr.fetch_history.cache_clear()
        pr.fetch_metadata.cache_clear()
        pr.fetch_dividends.cache_clear()
        st.session_state.pop("saved_csv", None)  # re-read the saved holdings too
        st.rerun()

# ---------- Load data --------------------------------------------------------

# Identity hues for the per-class breakdown lines, stepped for the dark chart
# surface (#0e1117) and checked with the dataviz all-pairs validator: every pair
# clears the CVD and normal-vision separation floors. Only the three CSV classes
# get a hue — the bond has no price history so it never draws a time series, and
# no fourth hue in this lightness band clears the all-pairs floor. Green and red
# stay reserved for win/loss polarity and are never identity colours.
CLASS_COLORS = {"stocks": "#3987e5", "etf": "#199e70", "crypto": "#d95926"}
# Benchmark line: fuchsia, far in hue from the class blues/teal/orange and from
# the green/red/white portfolio line; it is also dashed, so it never relies on
# colour alone.
BENCH_COLOR = "#e879f9"
# Streamlit picks light or dark from the viewer's browser and st.context.theme is
# documented as unreliable on first load, so this chart's non-data ink has to read
# on both surfaces. Both clear 3:1 against #ffffff and against #0e1117, unlike the
# app's usual #e8edf5 (1.18:1 on white — invisible in the light theme).
INK_NEUTRAL = "#6b7280"
GRID_NEUTRAL = "rgba(128,128,128,0.25)"
_sources: list[tuple[bytes, str]] = [
    (saved_csv[c], c) for c in storage.CLASSES if saved_csv.get(c) is not None]

if not _sources and not bond_list:
    ui.header("Benvenuto", live=False)
    st.info(
        "👋 **Welcome!** Upload a Yahoo Finance portfolio CSV from the sidebar to get started.\n\n"
        "Export from Yahoo Finance → your portfolio → ⋯ menu → **Export Transactions**, "
        "then drag the file into one of the **Stocks / ETF / Crypto CSV** controls on the left "
        "— it is saved and reloaded automatically next time."
    )
    st.caption("Expected columns: Symbol · Trade Date · Purchase Price · Quantity · Transaction Type "
               "(+ optional Current Price). Common Yahoo column aliases are supported automatically.")
    st.caption("…or press **🏛️ Carica BTP** in the sidebar to track the bond alone.")
    st.stop()

# Tag each frame with its asset class and concatenate into one master ledger.
# load_tx is cached and returns the cached object by reference, so copy before
# adding the tag to avoid mutating the cache. With only a bond (no CSV) tx_all is
# an empty ledger — the bond is handled outside the transaction pipeline.
_frames = []
for _buf, _cls in _sources:
    _df = load_tx(_buf).copy()
    _df["asset_class"] = _cls
    _frames.append(_df)
if _frames:
    tx_all = (pd.concat(_frames, ignore_index=True)
              .sort_values(["symbol", "trade_date"]).reset_index(drop=True))
else:
    tx_all = pd.DataFrame(columns=["symbol", "trade_date", "price", "qty", "side",
                                   "signed_qty", "cashflow", "snapshot_price", "asset_class"])

# Asset-class selector: only the classes actually loaded, ordered consistently.
# When >1 class is loaded, "Generale" (cross-asset aggregate) is the first option
# and the default. With a single class the radio is hidden, so a stocks-only load
# is identical to the previous single-file app.
present_classes = [c for c in ("stocks", "etf", "crypto") if c in set(tx_all["asset_class"])]
# The bond is not a CSV class — append it when the BTP is included in the sidebar.
if bond_list:
    present_classes = present_classes + ["bond"]

ui.header(" · ".join(ASSET_LABELS[c] for c in present_classes), live=use_live)
if len(present_classes) > 1:
    options = ["Generale"] + present_classes
    selected_class = st.segmented_control(
        "Asset class",
        options,
        default="Generale",
        format_func=lambda c: "Generale" if c == "Generale" else ASSET_LABELS[c],
        label_visibility="collapsed",
        key="asset_class",
    ) or "Generale"  # clicking the active segment deselects it
else:
    selected_class = present_classes[0]

IS_GENERAL = selected_class == "Generale"
IS_BOND = selected_class == "bond"

# Single filter point: every per-class global (positions, symbols, quotes, KPIs,
# TWR, all 13 tabs) derives from this subset. Skipped for the Generale and Bond
# views, which render their own dedicated pages below.
if not IS_GENERAL and not IS_BOND:
    tx = tx_all[tx_all["asset_class"] == selected_class].reset_index(drop=True)
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

@st.cache_data(ttl=3600, show_spinner=False)
def get_fx_rate(pair: str) -> float | None:
    """Spot rate for a Yahoo FX ticker, e.g. EURUSD=X → units of the quote
    currency per 1 EUR. FX pairs are ordinary Yahoo tickers, so this rides the
    quotes path and its offline fallback. Returns None on failure.
    """
    q = pr.fetch_quotes([pair])
    rate = q.get(pair, {}).get("price")
    return float(rate) if rate else None


def _stagger_labels(points: list[tuple[float, str]], y_span: float,
                    plot_px: int, min_gap_px: int = 15) -> list[tuple[float, str, int]]:
    """Greedy vertical de-collision for end-of-line direct labels.

    points: (y_value, text) in any order. Returns each with a pixel yshift that
    keeps labels at least min_gap_px apart, so two classes finishing at similar
    P&L don't stack their names on top of each other at the right edge.
    """
    if not points:
        return []
    if y_span <= 0:
        return [(y, t, 0) for y, t in points]
    px_per_unit = plot_px / y_span
    out: list[tuple[float, str, int]] = []
    last_final = None
    for y, t in sorted(points, key=lambda p: -p[0]):
        py = y * px_per_unit
        final = py if last_final is None else min(py, last_final - min_gap_px)
        out.append((y, t, int(round(final - py))))
        last_final = final
    return out


def _bond_position_row(bond, eur_div: float = 1.0) -> dict:
    """A static position row for the bond, shaped like an enriched all_pos row.

    qty·current_price == market_value (price expressed per unit nominal), EUR
    columns set directly (divisor 1.0), realized 0. Injected at the positions
    level so the bond flows into totals/allocation/holdings without any tx.
    """
    # qty in units of €100 face so qty·price == market_value while the displayed
    # price stays the recognizable base-100 bond quote (e.g. 102.37).
    return {
        "symbol": bond.isin, "qty": bond.nominal / 100.0, "avg_cost": bond.price_load,
        "invested": bond.load_value, "realized_pnl": 0.0, "first_buy": pd.NaT,
        "snapshot_price": float("nan"), "asset_class": "bond",
        "current_price": bond.price_market, "market_value": bond.market_value,
        "unrealized_pnl": bond.pnl, "total_pnl": bond.pnl, "return_pct": bond.return_pct,
        "currency": "EUR", "divisor": eur_div,
        "market_value_eur": bond.market_value / eur_div,
        "invested_eur": bond.load_value / eur_div,
        "unrealized_pnl_eur": bond.pnl / eur_div, "realized_pnl_eur": 0.0,
    }


@st.cache_data(ttl=300, show_spinner="Prezzi intraday…")
def get_intraday(symbols: tuple[str, ...]) -> pd.DataFrame:
    return pr.fetch_intraday_bulk(list(symbols))


@st.cache_data(ttl=6 * 3600, show_spinner="Calendario trimestrali…")
def get_earnings(symbols: tuple[str, ...]) -> dict:
    return pr.fetch_earnings_bulk(list(symbols))


@st.cache_data(ttl=120, show_spinner=False)
def get_extended(symbols: tuple[str, ...]) -> pd.DataFrame:
    """5-minute bars including pre/after-market, for the US listings only."""
    return pr.fetch_intraday_bulk(list(symbols), period="5d", interval="5m", prepost=True)


def _eur_prices(frame: pd.DataFrame, syms, sym_div: dict) -> pd.DataFrame:
    cols = [s for s in syms if s in frame.columns and sym_div.get(s)]
    return pd.DataFrame({s: frame[s] / sym_div[s] for s in cols}, index=frame.index)


def _daily_series(tx_c: pd.DataFrame, hist_eur: pd.DataFrame, live_mv: float):
    """(values, cashflows) for one set of transactions, pinned to the live value."""
    cols = [s for s in hist_eur.columns if s in set(tx_c["symbol"])]
    if tx_c.empty or not cols:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    v, cf = mt.build_value_series(tx_c, hist_eur[cols])
    if v.empty or not (v > 0).any():
        return pd.Series(dtype=float), pd.Series(dtype=float)
    v, cf = mt.trim_to_first_holding(v, cf)
    if live_mv > 0:
        v = v.copy()
        v.iloc[-1] = live_mv
    return v, cf


def _symbol_period_pnl(tx_s: pd.DataFrame, prices: pd.Series, qty: float,
                       base, intraday: bool) -> float | None:
    """One position's P&L over the window, in EUR (prices already in EUR)."""
    p = prices.ffill().dropna()
    if p.empty or base is None:
        return None
    if intraday:  # holdings as they are now
        before = p[p.index <= base]
        return qty * (float(p.iloc[-1]) - float(before.iloc[-1])) if len(before) else None
    v, cf = mt.build_value_series(tx_s, p.to_frame(prices.name))
    if v.empty:
        return None
    b = v.index[v.index <= base]
    return _period_pnl(v, cf, b[-1]) if len(b) else _period_pnl(v, cf, None)


def _period_pnl(values: pd.Series, cashflows: pd.Series, base) -> float:
    pnl = values - cashflows.cumsum()
    return float(pnl.iloc[-1] - (pnl.loc[base] if base is not None and base in pnl.index else 0.0))


def render_trend(tx_eur: pd.DataFrame, oc: pd.DataFrame, all_pos: pd.DataFrame,
                 quotes_g: dict, sym_div: dict, conv_syms: list, csv_classes: list) -> None:
    """Home 'Andamento': period simple return, per-class split and per-symbol table."""
    C, BASE = ui.cur_sym(), ui.cur_code()
    st.subheader("Andamento")
    f1, f2 = st.columns([3, 2])
    with f1:
        period = st.segmented_control(
            "Periodo", trend.PERIODS, default="1G", key="trend_period",
            format_func=lambda p: trend.PERIOD_LABELS[p], label_visibility="collapsed",
        ) or "1G"
    with f2:
        # Key carries the options so a change in the page-level filter can't leave
        # a stale selection behind.
        picked = st.pills(
            "Asset class", csv_classes, default=csv_classes, selection_mode="multi",
            format_func=lambda c: ASSET_LABELS[c], label_visibility="collapsed",
            key="trend_cls_" + "_".join(csv_classes),
        )
    if not picked:
        st.info("Seleziona almeno una asset class.")
        return
    picked = [c for c in csv_classes if c in picked]

    tx_f = tx_eur[tx_eur["asset_class"].isin(picked)]
    pos_f = oc[oc["asset_class"].isin(picked) & (oc["asset_class"] != "bond")]
    hist_all = get_history(tuple(conv_syms), "2y") if pr.HAS_YF else pd.DataFrame()
    if tx_f.empty or hist_all.empty:
        st.info("Servono i prezzi storici (Fetch live prices attivo) per l'andamento.")
        return
    hist_eur = _eur_prices(hist_all, sorted(set(tx_f["symbol"])), sym_div)
    mv_cls = pos_f.groupby("asset_class")["market_value_eur"].sum()

    # ---- curves: total + one per class ------------------------------------
    curves: dict[str, pd.Series] = {}
    pnl_by: dict[str, float] = {}
    base_ts = None
    sym_prices: pd.DataFrame = hist_eur          # per-symbol price source for the table
    intraday = period in trend.INTRADAY
    bench_px = pd.Series(dtype=float)
    if intraday:
        open_syms = tuple(sorted(pos_f["symbol"].unique()))
        raw = get_intraday(open_syms + (trend.BENCHMARK,)) if open_syms else pd.DataFrame()
        bars = _eur_prices(raw, open_syms, sym_div) if not raw.empty else pd.DataFrame()
        bench_px = raw[trend.BENCHMARK] if trend.BENCHMARK in raw.columns else pd.Series(dtype=float)
        if not bars.empty:
            sessions = sorted(pos_f.loc[pos_f["asset_class"] != "crypto", "symbol"].unique())
            start = trend.intraday_window(bars, period, sessions)
            qty_all = pos_f.groupby("symbol")["qty"].sum()
            total, base_ts = trend.intraday_curve(bars, qty_all, start)
            if not total.empty:
                curves["total"] = total
                v_all = (bars[[c for c in bars.columns if c in qty_all.index]].ffill()
                         * qty_all).sum(axis=1, min_count=1).dropna()
                pnl_by["total"] = float(v_all.iloc[-1] - v_all[v_all.index <= base_ts].iloc[-1])
                for cls in picked:
                    q = pos_f[pos_f["asset_class"] == cls].groupby("symbol")["qty"].sum()
                    c_curve, c_base = trend.intraday_curve(bars, q, start)
                    if not c_curve.empty:
                        curves[cls] = c_curve
                        v_c = (bars[[c for c in bars.columns if c in q.index]].ffill()
                               * q).sum(axis=1, min_count=1).dropna()
                        pnl_by[cls] = float(v_c.iloc[-1] - v_c[v_c.index <= c_base].iloc[-1])
                sym_prices = bars
        if "total" not in curves:
            intraday = False
            st.caption("Prezzi intraday non disponibili: uso le chiusure giornaliere.")
    if not intraday:
        values, cfs = _daily_series(tx_f, hist_eur, float(mv_cls.sum()))
        if values.empty:
            st.info("Nessuno storico per le classi selezionate.")
            return
        base_ts = trend.daily_base(period, values.index)
        curves["total"] = trend.period_curve(values, cfs, base_ts)
        bench_px = get_benchmark(trend.BENCHMARK, "2y") if pr.HAS_YF else pd.Series(dtype=float)
        pnl_by["total"] = _period_pnl(values, cfs, base_ts)
        for cls in picked:
            v_c, cf_c = _daily_series(tx_f[tx_f["asset_class"] == cls], hist_eur,
                                      float(mv_cls.get(cls, 0.0)))
            if v_c.empty:
                continue
            b_c = base_ts if base_ts is not None and base_ts in v_c.index else None
            curves[cls] = trend.period_curve(v_c, cf_c, b_c)
            pnl_by[cls] = _period_pnl(v_c, cf_c, b_c)
        # Today's live price as the last point of each symbol's daily series.
        sym_prices = hist_eur.copy()
        today_ts = pd.Timestamp(date.today())
        for s in sym_prices.columns:
            q = quotes_g.get(s)
            if q and sym_div.get(s):
                sym_prices.loc[today_ts, s] = q["price"] / sym_div[s]
        sym_prices = sym_prices.sort_index()

    # ---- pre/after-market moves (US listings) -----------------------------
    qty_now = pos_f.groupby("symbol")["qty"].sum()
    us_syms = tuple(sorted(s for s in qty_now.index if trend.is_us_listing(s)))
    ext_raw = get_extended(us_syms) if (us_syms and use_live) else pd.DataFrame()
    ext: dict[str, tuple[str, float, float]] = {}
    for s in us_syms:
        if s in ext_raw.columns:
            mv = trend.extended_move(ext_raw[s], (quotes_g.get(s) or {}).get("price"))
            if mv:
                ext[s] = mv
    ext_impact = {s: float(qty_now[s]) * (px - ref) / sym_div[s]
                  for s, (_, px, ref) in ext.items() if sym_div.get(s)}
    # All US listings share one session clock, so one label names the columns.
    ext_name = ("pre-market" if next(iter(ext.values()))[0] == "Pre" else "after-hours") if ext else None
    ext_pct_col, ext_eur_col = f"Δ {ext_name} %", f"Impatto {ext_name} {C}"

    total = curves["total"]
    ret = float(total.iloc[-1]) if len(total) else 0.0
    pnl = pnl_by.get("total", 0.0)
    # S&P 500 from the same base point (inception: the portfolio's first day).
    bench = trend.benchmark_curve(bench_px, base_ts if base_ts is not None
                                  else (total.index[0] if len(total) else None))
    bench_ret = float(bench.iloc[-1]) if len(bench) else None
    ui.kpi_grid([
        ui.kpi(f"Rendimento · {trend.PERIOD_LABELS[period]}", ui.pct(ret * 100),
               "simple return", positive=ret >= 0, hero=True),
        ui.kpi("P&L nel periodo", ui.money(pnl), f"in {BASE}", positive=pnl >= 0),
        ui.kpi("Valore attuale", ui.money(float(mv_cls.sum())),
               f"{pos_f['symbol'].nunique()} titoli"),
    ] + ([ui.kpi(f"{ext_name} · stima",
                 ui.money(sum(ext_impact.values())),
                 f"impatto sul P&L · {len(ext_impact)} titoli USA",
                 positive=sum(ext_impact.values()) >= 0)] if ext_impact else []) + (
        [ui.kpi("S&P 500", ui.pct(bench_ret * 100),
                 f"portafoglio {'+' if ret >= bench_ret else '−'}"
                 f"{abs(ret - bench_ret) * 100:.2f} pt vs indice",
                 positive=ret >= bench_ret)] if bench_ret is not None else []) + ([ui.kpi(ASSET_LABELS[c], ui.pct(float(curves[c].iloc[-1]) * 100),
                 ui.money(pnl_by.get(c, 0.0)) + " nel periodo",
                 positive=float(curves[c].iloc[-1]) >= 0)
          for c in picked if c in curves and len(curves[c])] if len(picked) > 1 else []))

    # ---- earnings today / next business day (stocks held) -----------------
    if "stocks" in picked and use_live:
        stock_pos = pos_f[pos_f["asset_class"] == "stocks"]
        stock_syms = tuple(sorted(stock_pos["symbol"].unique()))
        if stock_syms:
            soon = trend.earnings_soon(get_earnings(stock_syms), pd.Timestamp.now(tz="UTC"))
            ui.earnings_strip(soon, stock_pos.groupby("symbol")["market_value_eur"].sum().to_dict())

    # ---- chart ------------------------------------------------------------
    def _x(s: pd.Series):
        idx = s.index
        if intraday and getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert(trend.LOCAL_TZ).tz_localize(None)
        return idx

    fig = go.Figure()
    up = ret >= 0
    line_c = ui.POS if up else ui.NEG
    multi = len(picked) > 1
    if multi:
        for cls in picked:
            if cls in curves and len(curves[cls]):
                fig.add_trace(go.Scatter(
                    x=_x(curves[cls]), y=curves[cls].values * 100, mode="lines",
                    line=dict(color=CLASS_COLORS[cls], width=1.8), name=ASSET_LABELS[cls],
                    hovertemplate="%{y:+.2f}%<extra>" + ASSET_LABELS[cls] + "</extra>"))
    fig.add_trace(go.Scatter(
        x=_x(total), y=total.values * 100, mode="lines",
        line=dict(color=line_c if not multi else "#e6ebf2", width=2.6, shape="spline", smoothing=0.4),
        fill="tozeroy", fillcolor="rgba(34,197,94,0.10)" if up else "rgba(244,63,94,0.10)",
        name="Totale", hovertemplate="%{y:+.2f}%<extra>Totale</extra>"))
    if len(bench):
        fig.add_trace(go.Scatter(
            x=_x(bench), y=bench.values * 100, mode="lines",
            line=dict(color=BENCH_COLOR, width=2, dash="dash"), name="S&P 500",
            hovertemplate="%{y:+.2f}%<extra>S&P 500</extra>"))
    fig.add_hline(y=0, line_dash="dot", line_color="#4b5563")
    fig.update_layout(
        height=360, margin=dict(t=10, b=10, l=10, r=10), hovermode="x unified",
        yaxis=dict(ticksuffix="%", gridcolor=GRID_NEUTRAL, zeroline=False),
        xaxis=dict(showgrid=False, tickformat="%H:%M" if period == "1G" and intraday else None),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        showlegend=multi or bool(len(bench)),
        transition=dict(duration=400, easing="cubic-in-out"))
    st.plotly_chart(fig, use_container_width=True)

    # ---- per-symbol breakdown --------------------------------------------
    gross = (tx_eur[tx_eur["side"] == "BUY"].assign(_c=lambda d: d["qty"] * d["price"])
             .groupby(["symbol", "asset_class"])["_c"].sum())
    rows = []
    for r in pos_f.itertuples():
        s, cls = r.symbol, r.asset_class
        q = quotes_g.get(s) or {}
        day = (q["price"] / q["prev_close"] - 1) * 100 if q.get("prev_close") else None
        div = sym_div.get(s)
        day_pnl = (float(r.qty) * (q["price"] - q["prev_close"]) / div
                   if q.get("prev_close") and div else None)
        tot_pnl = float((r.unrealized_pnl_eur or 0) + (r.realized_pnl_eur or 0))
        cost = gross.get((s, cls))
        simple = tot_pnl / cost * 100 if cost else None
        prices_s = sym_prices[s] if s in sym_prices.columns else pd.Series(dtype=float)
        if (period == "Inizio" or base_ts is None) and not intraday:
            per = simple
            per_pnl = tot_pnl
            spark_base = prices_s.dropna().index.min() if len(prices_s.dropna()) else None
            first = tx_f[(tx_f["symbol"] == s)]["trade_date"].min()
            spark_base = pd.Timestamp(first) if pd.notna(first) else spark_base
        else:
            pr_ = trend.symbol_period_return(prices_s, base_ts)
            per = pr_ * 100 if pr_ is not None else None
            spark_base = base_ts
            per_pnl = _symbol_period_pnl(tx_f[(tx_f["symbol"] == s) & (tx_f["asset_class"] == cls)],
                                         prices_s, float(r.qty), base_ts, intraday)
        rsi = mt.compute_rsi(hist_all[s], 14) if s in hist_all.columns else None
        e = ext.get(s)
        row = {
            "Titolo": s, "Classe": ASSET_LABELS[cls],
            "Andamento": trend.sparkline(prices_s, spark_base),
            "Giorno %": day, f"P&L giorno {C}": day_pnl,
            "Periodo %": per, f"P&L periodo {C}": per_pnl,
            "Simple return %": simple, f"P&L totale {C}": tot_pnl,
            f"Valore {C}": float(r.market_value_eur), "RSI": rsi,
        }
        if ext:  # extra columns only while a US pre/after session has prices
            row[ext_pct_col] = (e[1] / e[2] - 1) * 100 if e else None
            row[ext_eur_col] = ext_impact.get(s) if e else None
        rows.append(row)
    if not rows:
        return
    table = pd.DataFrame(rows).sort_values(f"Valore {C}", ascending=False)
    # None → NaN so the Styler's na_rep shows "—" instead of the text "None".
    num_cols = [c for c in table.columns if c not in ("Titolo", "Classe", "Andamento")]
    table[num_cols] = table[num_cols].astype(float)

    def _tone(v):
        if v is None or pd.isna(v):
            return ""
        return f"color: {ui.POS}" if v >= 0 else f"color: {ui.NEG}"

    def _rsi_tone(v):
        if v is None or pd.isna(v):
            return ""
        return f"color: {ui.NEG}" if v >= 70 else f"color: {ui.POS}" if v <= 30 else ""

    signed = ["Giorno %", f"P&L giorno {C}", "Periodo %", f"P&L periodo {C}", "Simple return %",
              f"P&L totale {C}"] + ([ext_pct_col, ext_eur_col] if ext else [])
    pct = "{:+.2f}%".format
    fmt = {"Giorno %": pct, f"P&L giorno {C}": ui.money, "Periodo %": pct,
           f"P&L periodo {C}": ui.money, "Simple return %": pct, f"P&L totale {C}": ui.money,
           f"Valore {C}": ui.money, "RSI": "{:.0f}".format}
    if ext:
        fmt.update({ext_pct_col: pct, ext_eur_col: ui.money})
    # Streamlit draws empty cells as "None" whatever the Styler says, so columns
    # with gaps are turned into text here ("—" for a gap); colours are computed
    # from the numbers either way.
    disp = table.copy()
    as_text = [c for c in fmt if disp[c].isna().any()]
    for c in as_text:
        disp[c] = ["—" if pd.isna(v) else fmt[c](v) for v in table[c]]
    css = pd.DataFrame("", index=table.index, columns=table.columns)
    for c in signed:
        css[c] = table[c].map(_tone)
    css["RSI"] = table["RSI"].map(_rsi_tone)
    styled = (disp.style.apply(lambda _: css, axis=None)
              .format({c: f for c, f in fmt.items() if c not in as_text}))
    st.markdown(f"**Titoli · {trend.PERIOD_LABELS[period]}**")
    if ext_impact:
        movers = sorted(ext_impact.items(), key=lambda kv: abs(kv[1]), reverse=True)[:3]
        st.caption("Fuori orario si muovono di più: " + " · ".join(
            f"**{s}** {(ext[s][1] / ext[s][2] - 1) * 100:+.1f}% ({ui.money(v)})" for s, v in movers))
    st.dataframe(
        styled, hide_index=True, use_container_width=True,
        height=min(38 + 35 * len(table), 520),
        column_config={
            "Andamento": st.column_config.LineChartColumn(
                "Andamento", width="small", help="Prezzo nel periodo selezionato"),
            "Giorno %": st.column_config.Column(help="Prezzo attuale vs chiusura precedente"),
            "Periodo %": st.column_config.Column(
                help="Variazione di prezzo nel periodo (Dall'inizio = simple return della posizione)"),
            "Simple return %": st.column_config.Column(
                help="P&L totale (realizzato + non realizzato) ÷ costo di tutti gli acquisti"),
            "RSI": st.column_config.Column(help="RSI 14 giorni: >70 ipercomprato, <30 ipervenduto"),
            f"P&L giorno {C}": st.column_config.Column(help="Quantità × (prezzo attuale − chiusura precedente)"),
            f"P&L periodo {C}": st.column_config.Column(
                help="P&L della posizione nel periodo; acquisti e vendite nel periodo contano come cassa"),
            ext_pct_col: st.column_config.Column(
                help="Ultimo prezzo fuori orario vs ultima chiusura ufficiale (solo titoli USA)"),
            ext_eur_col: st.column_config.Column(
                help="Quantità × variazione fuori orario: quanto cambierebbe il P&L a quel prezzo"),
        },
    )
    st.caption(f"Importi in {BASE} al cambio di oggi. Il BTP non ha storico prezzi ed è escluso.")


def render_general(tx_all: pd.DataFrame, classes: list[str],
                   bond_list: list[bonds.Bond]) -> None:
    """Cross-asset aggregate view ('Generale').

    Positions are built per class and concatenated with the asset_class tag, so
    the grain stays (symbol, asset_class) and a ticker held in two classes never
    merges. Each position is converted to EUR using the live rate for its OWN
    native currency (detected from the quote), then aggregated — totals are
    homogeneous EUR. Positions whose currency or rate is unavailable are excluded
    from the EUR totals with an explicit warning, never summed across currencies.
    Conversion uses TODAY's rate even for realized/historical figures (accepted
    approximation).
    """
    today_ = date.today()
    # Base currency of every converted figure below. Columns keep their historic
    # *_eur names; they hold amounts in BASE.
    C, BASE = ui.cur_sym(), ui.cur_code()

    # 0) Asset-class filter for the aggregate. Deselecting a class removes it from
    #    EVERYTHING below (KPIs, allocation, value-by-class, holdings, Performance).
    sel = st.multiselect(
        "Asset classes in aggregate",
        options=classes, default=classes,
        format_func=lambda c: ASSET_LABELS[c],
        help="Include / exclude asset classes from the cross-asset aggregate.",
    )
    if not sel:
        st.info("Select at least one asset class to aggregate.")
        return
    classes = sel
    # The bond carries no transactions; the CSV machinery (positions/quotes/FX)
    # only runs over the CSV classes. The aggregate needs at least one CSV class.
    csv_classes = [c for c in classes if c != "bond"]
    if not csv_classes:
        st.info("Select at least one non-bond class for the aggregate "
                "(the bond on its own is shown in the **Bond** view).")
        return
    # tx restricted to the selected CSV classes — the single source for every
    # tx-wide computation below. Filtering by (asset_class, symbol) keeps a ticker
    # shared with a DESELECTED class from being double-counted.
    tx_sel = tx_all[tx_all["asset_class"].isin(csv_classes)]

    # 1) Build positions per CSV class (collision-safe), concat with the tag.
    built = []
    for cls in csv_classes:
        sub = tx_sel[tx_sel["asset_class"] == cls]
        ap = pf.build_positions(sub)
        ap["asset_class"] = cls
        built.append(ap)
    all_pos = pd.concat(built, ignore_index=True)

    # 2) Detect native currency per symbol from quotes. Fetch over ALL symbols
    #    (open + closed): closed lots' realized P&L also needs converting.
    all_syms = tuple(sorted(all_pos["symbol"].unique()))
    quotes_g = get_quotes(all_syms) if use_live else {}
    price_map_g = {s: q["price"] for s, q in quotes_g.items()}
    ccy_map = {s: q.get("currency") for s, q in quotes_g.items()}
    all_pos = pf.enrich_with_prices(all_pos, price_map_g)
    all_pos["currency"] = all_pos["symbol"].map(ccy_map)

    # 3) Resolve an EUR divisor per distinct currency present.
    #    EUR{CCY}=X = CCY per 1 EUR  ⇒  value_eur = value_native / rate. EUR → 1.0.
    currencies = sorted({c for c in all_pos["currency"].dropna().unique()}
                        | ({"EUR"} if bond_list and "bond" in classes else set()))
    divisor: dict[str, float] = {}
    for ccy in currencies:
        if ccy == BASE:
            divisor[ccy] = 1.0
            continue
        r = get_fx_rate(f"{BASE}{ccy}=X") if use_live else None
        if r:
            divisor[ccy] = r
    all_pos["divisor"] = all_pos["currency"].map(divisor)

    # 4) EUR columns (NaN where not convertible → naturally excluded from sums).
    for col in ("market_value", "invested", "unrealized_pnl", "realized_pnl"):
        all_pos[f"{col}_eur"] = all_pos[col] / all_pos["divisor"]

    # Inject the bond as a static EUR position (option b): it lands in the totals,
    # allocation, holdings and filter, but carries no transactions — so it is absent
    # from tx_sel/tx_eur and thus excluded from XIRR and the Performance series.
    bond_div = divisor.get("EUR")  # EUR → base; 1.0 when the base is EUR
    bond_in = bool(bond_list) and "bond" in classes and bond_div is not None
    if bond_in:
        all_pos = pd.concat(
            [all_pos, pd.DataFrame([_bond_position_row(b, bond_div) for b in bond_list])],
            ignore_index=True)

    convertible = all_pos["divisor"].notna()
    open_mask = all_pos["qty"] > 1e-6
    open_pos = all_pos[open_mask].copy()            # all open (incl. unconvertible)
    oc = all_pos[open_mask & convertible].copy()    # open AND convertible (EUR sums)

    total_mv_eur = float(oc["market_value_eur"].sum())
    total_unreal_eur = float(oc["unrealized_pnl_eur"].sum())
    total_real_eur = float(all_pos.loc[convertible, "realized_pnl_eur"].sum())
    total_pnl_eur = total_unreal_eur + total_real_eur
    # The bond is excluded from XIRR and the Performance time-series (it has no tx
    # history); those use the CSV-only market value for the terminal/pin.
    bond_mv_eur = sum(b.market_value for b in bond_list) / bond_div if bond_in else 0.0
    csv_mv_eur = total_mv_eur - bond_mv_eur

    # EUR cashflow basis — single source of truth for "simple return on net cash",
    # shared by the headline KPI (below) and the Return decomposition further down,
    # so they always tell the same story. tx prices scaled to EUR by each symbol's
    # divisor; tx in unconvertible currencies are excluded (consistent with totals).
    sym_div = {s: divisor.get(ccy_map.get(s)) for s in all_syms}
    conv_syms = [s for s in all_syms if sym_div.get(s)]
    tx_eur = tx_sel[tx_sel["symbol"].isin(conv_syms)].copy()
    # map, not row-wise apply: apply on an empty frame returns a DataFrame and crashes.
    tx_eur["price"] = tx_eur["price"] / tx_eur["symbol"].map(sym_div).astype(float)
    buy_eur = tx_eur[tx_eur["side"] == "BUY"]
    sell_eur = tx_eur[tx_eur["side"] == "SELL"]
    deployed_eur = float((buy_eur["qty"] * buy_eur["price"]).sum())
    returned_eur = float((sell_eur["qty"] * sell_eur["price"]).sum())
    if bond_in:
        deployed_eur += sum(b.load_value for b in bond_list) / bond_div  # single buys, no sells
    net_cash_in_eur = deployed_eur - returned_eur
    simple_on_net = (total_pnl_eur / net_cash_in_eur * 100.0) if net_cash_in_eur > 0 else 0.0

    # 5) EUR XIRR: convert each cashflow by its symbol's currency (today's rate),
    #    drop tx in unsupported currencies, pin the final EUR market value.
    cf = []
    for _, r in tx_sel.iterrows():
        d = divisor.get(ccy_map.get(r["symbol"]))
        if d:
            td = r["trade_date"].date() if hasattr(r["trade_date"], "date") else r["trade_date"]
            cf.append((td, float(r["cashflow"]) / d))
    if csv_mv_eur > 0:  # bond excluded from XIRR (no tx history)
        cf.append((today_, csv_mv_eur))
    agg_xirr = pf.xirr(cf) if cf else None

    # ---- header + warnings -------------------------------------------------
    ts_ = datetime.now().strftime("%Y-%m-%d %H:%M")
    label_list = ", ".join(ASSET_LABELS[c] for c in classes)
    st.caption(f"As of {ts_} · aggregate of **{label_list}** · "
               f"{int(open_mask.sum())} open positions · totals in **{BASE}** "
               f"(today's FX applied to realized/historical too)")

    if not use_live:
        st.warning(f"Live prices are off — {BASE} conversion needs live quotes/FX. "
                   f"Enable “Fetch live prices” in the sidebar to aggregate in {BASE}.")
    excluded = open_pos[~convertible[open_mask].values]
    if not excluded.empty:
        items = "; ".join(
            f"{row.symbol} ({row.currency if isinstance(row.currency, str) else 'unknown'})"
            for row in excluded.itertuples())
        st.warning(f"Excluded from {BASE} totals — no rate for their currency: {items}. "
                   "Native values still appear in the holdings table below.")

    # ---- KPIs (EUR primary) ------------------------------------------------
    ui.kpi_grid([
        ui.kpi("Market value", ui.money(total_mv_eur),
               f"{int(open_mask.sum())} posizioni aperte", hero=True),
        ui.kpi("Total P&L", ui.money(total_pnl_eur), ui.pct(simple_on_net) + " su capitale netto",
               positive=total_pnl_eur >= 0),
        ui.kpi("Unrealized P&L", ui.money(total_unreal_eur), "posizioni aperte",
               positive=total_unreal_eur >= 0),
        ui.kpi("Realized P&L", ui.money(total_real_eur), "posizioni chiuse",
               positive=total_real_eur >= 0),
        ui.kpi("Simple return", ui.pct(simple_on_net),
               "P&L ÷ capitale netto investito", positive=simple_on_net >= 0),
        ui.kpi("XIRR (MWR)", ui.pct(agg_xirr * 100) if agg_xirr else "n/a",
               "money-weighted, annuo",
               positive=(agg_xirr >= 0) if agg_xirr is not None else None),
    ])
    fx_txt = " · ".join(f"{BASE}{c}={divisor[c]:.4f}" for c in currencies
                        if c != BASE and c in divisor)
    if fx_txt:
        st.caption(f"💶 FX today: {fx_txt}")

    st.divider()

    render_trend(tx_eur, oc, all_pos, quotes_g, sym_div, conv_syms, csv_classes)

    st.divider()

    # ---- allocation (EUR) + per-class native breakdown --------------------
    left, right = st.columns(2)
    with left:
        st.subheader(f"Allocation by asset class ({BASE})")
        alloc = (oc.groupby("asset_class")["market_value_eur"].sum()
                 .reindex(classes).fillna(0.0).reset_index())
        alloc["label"] = alloc["asset_class"].map(ASSET_LABELS)
        if total_mv_eur > 0:
            fig = px.pie(alloc, names="label", values="market_value_eur", hole=0.55)
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(showlegend=True, margin=dict(t=10, b=10, l=10, r=10), height=300)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No convertible open positions to allocate.")
    with right:
        st.subheader(f"Value by class — {BASE} vs native")
        rows = []
        for cls in classes:
            eur_v = float(oc.loc[oc["asset_class"] == cls, "market_value_eur"].sum())
            natives = (open_pos[open_pos["asset_class"] == cls]
                       .dropna(subset=["currency"])
                       .groupby("currency")["market_value"].sum())
            nat_str = " · ".join(f"{cur} {v:,.0f}" for cur, v in natives.items()) or "—"
            # % return for the class = class total P&L EUR / class net cash invested EUR,
            # same simple-return formula as the headline KPI. The bond has no tx, so
            # its net cash is its load value (single buy, no sells).
            if cls == "bond" and bond_in:
                cls_net = sum(b.load_value for b in bond_list) / bond_div
            else:
                cls_tx = tx_eur[tx_eur["asset_class"] == cls]
                cls_buy = cls_tx[cls_tx["side"] == "BUY"]
                cls_sell = cls_tx[cls_tx["side"] == "SELL"]
                cls_net = (float((cls_buy["qty"] * cls_buy["price"]).sum())
                           - float((cls_sell["qty"] * cls_sell["price"]).sum()))
            cls_unreal = float(oc.loc[oc["asset_class"] == cls, "unrealized_pnl_eur"].sum())
            cls_real = float(all_pos.loc[convertible & (all_pos["asset_class"] == cls),
                                         "realized_pnl_eur"].sum())
            cls_ret = ((cls_unreal + cls_real) / cls_net * 100.0) if cls_net > 0 else None
            rows.append({"Class": ASSET_LABELS[cls], f"Market value ({C})": eur_v,
                         "% return": cls_ret, "Native": nat_str})
        st.dataframe(
            pd.DataFrame(rows), hide_index=True, use_container_width=True,
            column_config={
                f"Market value ({C})": st.column_config.NumberColumn(format=f"{C}%.0f"),
                "% return": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )

    st.divider()
    st.subheader("All holdings")
    show_closed = st.checkbox(
        "Mostra posizioni chiuse", value=False,
        help="Include closed positions (qty ≈ 0): market value 0, but realized P&L ≠ 0.")
    # all_pos = open + closed; open_pos = open only. Closed rows carry realized P&L.
    src = all_pos if show_closed else open_pos
    table = src.copy()
    table["Class"] = table["asset_class"].map(ASSET_LABELS)
    table["total_pnl_eur"] = table["unrealized_pnl_eur"] + table["realized_pnl_eur"]

    # Return % = Total P&L EUR ÷ gross buy cost EUR. Gross cost = Σ qty·price over
    # ALL buys of this (symbol, asset_class), from tx_eur (already EUR, class-scoped).
    # Stable denominator: unlike net cash it doesn't collapse to ~0 on closed
    # positions, so the % stays meaningful across the open→closed lifecycle.
    gross_cost = (tx_eur[tx_eur["side"] == "BUY"]
                  .assign(_c=lambda d: d["qty"] * d["price"])
                  .groupby(["symbol", "asset_class"])["_c"].sum())
    if bond_in:  # bond gross cost = its load value (single buy, no tx)
        for b in bond_list:
            gross_cost.loc[(b.isin, "bond")] = b.load_value / bond_div
    table["gross_cost_eur"] = [gross_cost.get((s, a))
                               for s, a in zip(table["symbol"], table["asset_class"])]
    table["return_pct"] = table["total_pnl_eur"] / table["gross_cost_eur"] * 100.0

    table = table[["Class", "symbol", "currency", "qty", "current_price",
                   "market_value", "market_value_eur", "unrealized_pnl_eur",
                   "realized_pnl_eur", "total_pnl_eur", "return_pct"]]
    table = table.sort_values("market_value_eur", ascending=False, na_position="last")
    st.dataframe(
        table, hide_index=True, use_container_width=True,
        column_config={
            "symbol": "Symbol",
            "currency": "Ccy",
            "qty": st.column_config.NumberColumn("Qty", format="%.4f"),
            "current_price": st.column_config.NumberColumn("Price (native)", format="%.2f"),
            "market_value": st.column_config.NumberColumn("MV (native)", format="%.0f"),
            "market_value_eur": st.column_config.NumberColumn(f"MV ({C})", format=f"{C}%.0f"),
            "unrealized_pnl_eur": st.column_config.NumberColumn(f"Unrealized ({C})", format=f"{C}%.0f"),
            "realized_pnl_eur": st.column_config.NumberColumn(f"Realized ({C})", format=f"{C}%.0f"),
            "total_pnl_eur": st.column_config.NumberColumn(f"Total P&L ({C})", format=f"{C}%.0f"),
            "return_pct": st.column_config.NumberColumn(
                "Return %", format="%.2f%%",
                help=f"Total P&L ÷ gross buy cost (Σ qty·price of all buys), in {BASE}."),
        },
    )

    # ===================================================================
    # Performance (aggregate · EUR) — mirror of the Stocks "Performance" tab,
    # computed on the selected classes (tx_sel/tx_eur) and converted to EUR.
    # ===================================================================
    st.divider()
    st.header(f"Performance (aggregate · {BASE})")
    st.caption("Same methodology as the per-class Performance tab, aggregated across "
               f"all classes. Historical prices and cashflows are converted to {BASE} at "
               "**today's** FX rate (an accepted approximation for past values).")
    if bond_in:
        st.caption(f"ℹ️ The bond ({C}{bond_mv_eur:,.0f}) is **excluded** from these time-series "
                   "(it has no price history) — these curves reflect the CSV classes only, so "
                   "they won't match the bond-inclusive KPIs above.")

    # ---- EUR history ingredient (tx_eur / conv_syms / sym_div built above) ----
    # Generale uses period="2y" (covers all post-2024 transactions with margin and
    # is lighter than "max"): build_value_series' leading-zero trim then starts the
    # series at the first day a position was held (= first trade_date). The sidebar
    # 'period' deliberately does NOT apply here — per-class tabs still use it. One
    # close-price column per convertible symbol, ÷ its rate.
    hist_eur = get_history(tuple(conv_syms), "2y") if pr.HAS_YF else pd.DataFrame()
    if not hist_eur.empty:
        hist_eur = hist_eur.copy()
        for s in hist_eur.columns:
            hist_eur[s] = hist_eur[s] / sym_div[s]

    value_series_g = pd.Series(dtype=float)
    cf_series_g = pd.Series(dtype=float)
    twr_g = pd.Series(dtype=float)
    bench_g = pd.Series(dtype=float)
    if not hist_eur.empty:
        value_series_g, cf_series_g = mt.build_value_series(tx_eur, hist_eur)
        if not value_series_g.empty and (value_series_g > 0).any():
            value_series_g, cf_series_g = mt.trim_to_first_holding(value_series_g, cf_series_g)
            # Pin the last point to the CSV-only EUR market value (bond excluded
            # from the series) so the curve matches the tradeable portfolio.
            if csv_mv_eur > 0:
                value_series_g.iloc[-1] = csv_mv_eur
            twr_g = mt.twr_curve(value_series_g, cf_series_g)
        if benchmark != "None":
            # "2y" so the benchmark spans the aggregate's inception window too (the
            # TWR index starts at the first trade, not the sidebar window).
            b = get_benchmark(benchmark, "2y")
            if not b.empty and not twr_g.empty:
                b = b.reindex(twr_g.index, method="ffill").dropna()
                bench_g = mt.benchmark_growth(b)

    if twr_g.empty:
        st.warning("Need yfinance + a non-empty history to compute aggregate TWR. "
                   "Pick a longer period, or check that holdings have convertible currencies.")
    else:
        # ----- Return decomposition (EUR) ----------------------------------
        st.subheader("Return decomposition")
        st.caption("Different methods answer different questions — all 'correct', "
                   "measuring different things.")
        twr_itd = float(twr_g.iloc[-1] - 1) if len(twr_g) >= 2 else 0.0
        # deployed_eur / returned_eur / net_cash_in_eur / simple_on_net are computed
        # once above (shared with the headline KPI). Only simple_on_deployed is local.
        simple_on_deployed = (total_pnl_eur / deployed_eur * 100.0) if deployed_eur > 0 else 0.0

        rd1, rd2, rd3, rd4 = st.columns(4)
        rd1.metric("TWR (time-weighted)", f"{twr_itd*100:+.2f}%",
                   help="Chain-linked daily returns — price moves only, ignores cash timing. "
                        "Compare to the benchmark below.")
        rd2.metric("XIRR (money-weighted, ann.)",
                   f"{agg_xirr*100:.2f}%" if agg_xirr else "—",
                   help=f"Annualized return on actual {BASE} cashflows, time-discounted.")
        rd3.metric("Simple return on net cash", f"{simple_on_net:+.2f}%",
                   help=f"Total P&L ÷ net cash invested (deployed − returned), in {BASE}.")
        rd4.metric("Simple return on deployed", f"{simple_on_deployed:+.2f}%",
                   help=f"Total P&L ÷ gross capital deployed (all buys), in {BASE}.")

        st.markdown("---")

        # Period returns grid
        prets = mt.period_returns_table(twr_g)
        cells = []
        for label, val in prets.items():
            txt = f"{val*100:+.2f}%" if val is not None else "—"
            color = ui.POS if (val or 0) >= 0 else ui.NEG
            cells.append(
                f'<div class="period-cell"><div class="period-label">{label}</div>'
                f'<div class="period-value" style="color:{color}">{txt}</div></div>'
            )
        st.markdown(f'<div class="period-grid">{"".join(cells)}</div>', unsafe_allow_html=True)

        # Risk row
        ann = mt.annualized_return(twr_g)
        vol = mt.volatility(twr_g)
        sh = mt.sharpe(twr_g, rf=rf_rate)
        mdd = mt.max_drawdown(twr_g)
        rk1, rk2, rk3, rk4 = st.columns(4)
        rk1.metric("Annualized TWR", f"{ann*100:.2f}%" if ann is not None else "—")
        rk2.metric("Volatility (ann.)", f"{vol*100:.2f}%" if vol is not None else "—")
        rk3.metric("Sharpe ratio", f"{sh:.2f}" if sh is not None else "—",
                   help=f"rf = {rf_rate*100:.1f}%")
        rk4.metric("Max drawdown", f"{mdd*100:.2f}%")

        # Portfolio return curve vs benchmark — toggleable (unique key!)
        chart_mode_g = st.radio(
            "Return measure for chart",
            ["Simple return on net cash", "TWR (time-weighted)"],
            horizontal=True, key="gen_chart_mode",
        )
        cum_deposits_curve = cf_series_g.cumsum()
        with np.errstate(divide="ignore", invalid="ignore"):
            simple_curve = (value_series_g - cum_deposits_curve) / cum_deposits_curve
        simple_curve = simple_curve.where(cum_deposits_curve > 1e-6)
        # Same rebase as the per-class tab when history starts after the first trade.
        if len(tx_eur) and tx_eur["trade_date"].min() < value_series_g.index[0]:
            simple_curve = trend.period_curve(value_series_g, cf_series_g, value_series_g.index[0])

        if chart_mode_g.startswith("TWR"):
            port_y = (twr_g - 1) * 100
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
            line=dict(color="#22c55e", width=2.4),
            fill="tozeroy", fillcolor="rgba(61,220,151,0.08)",
            name=port_label,
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:+.2f}%<extra></extra>",
        ))
        if not bench_g.empty:
            fig.add_trace(go.Scatter(
                x=bench_g.index, y=(bench_g - 1) * 100, mode="lines",
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

        # Equity curve (€)
        st.subheader(f"Equity curve ({C})")
        st.caption("Blue = market value of holdings. Amber = cumulative net cash invested "
                   f"(buys − sells). Gap = mark-to-market total P&L. All in {BASE}.")
        cum_capital_curve = cf_series_g.cumsum()
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=value_series_g.index, y=value_series_g.values, mode="lines",
            line=dict(color="#7c8eff", width=2),
            fill="tozeroy", fillcolor="rgba(124,142,255,0.08)",
            name="Market value",
            hovertemplate="%{x|%Y-%m-%d}<br>" + C + "%{y:,.0f}<extra>Market value</extra>",
        ))
        fig2.add_trace(go.Scatter(
            x=cum_capital_curve.index, y=cum_capital_curve.values, mode="lines",
            line=dict(color="#f4b942", width=2, dash="dot"),
            name="Net capital invested",
            hovertemplate="%{x|%Y-%m-%d}<br>" + C + "%{y:,.0f}<extra>Net capital</extra>",
        ))
        fig2.update_layout(height=360, margin=dict(t=10, b=10, l=10, r=10),
                           paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           yaxis_title=C, xaxis=dict(showgrid=False),
                           yaxis=dict(gridcolor="#222"),
                           legend=dict(orientation="h", yanchor="bottom", y=1.02))
        st.plotly_chart(fig2, use_container_width=True)

        # Total P&L over time (€) — aggregate plus one line per asset class.
        st.subheader(f"Total P&L over time ({C})")
        st.caption(f"Mark-to-market: portfolio value minus net cash invested, in {BASE}. "
                   "The grey line is the aggregate; coloured lines split it by asset "
                   "class and always sum back to it. Add or remove classes with the "
                   "**asset-class filter at the top of this page**.")
        cum_deposits = cf_series_g.cumsum()
        total_pnl_curve = value_series_g - cum_deposits

        # Per-class curves. Each class is rebuilt from its own transactions and its
        # own price columns over the FULL history index — the cumsum must span all
        # of history or a class silently loses the cash it spent before the window
        # (the same trap build_value_series' opening_cash closes for the aggregate).
        # Sliced to the aggregate's index only afterwards, so the parts sum to the
        # whole. A symbol held in two classes shares a price column but keeps its
        # own quantities, matching the (symbol, asset_class) grain used above.
        class_pnl: dict[str, pd.Series] = {}
        mv_by_class = oc.groupby("asset_class")["market_value_eur"].sum()
        for cls in csv_classes:
            cls_tx = tx_eur[tx_eur["asset_class"] == cls]
            cls_syms = [s for s in hist_eur.columns if s in set(cls_tx["symbol"])]
            if cls_tx.empty or not cls_syms:
                continue
            v_c, cf_c = mt.build_value_series(cls_tx, hist_eur[cls_syms])
            cum_c = cf_c.cumsum()
            pnl_c = (v_c - cum_c).reindex(total_pnl_curve.index)
            # Mirror the aggregate's terminal pin with this class's live EUR market
            # value, so the class endpoints still add up to the pinned total.
            mv_c = float(mv_by_class.get(cls, 0.0))
            if mv_c > 0:
                pnl_c.iloc[-1] = mv_c - float(cum_c.iloc[-1])
            class_pnl[cls] = pnl_c
        # With one class selected the breakdown would just redraw the total line.
        show_breakdown = len(class_pnl) > 1

        pos = total_pnl_curve.where(total_pnl_curve >= 0)
        neg = total_pnl_curve.where(total_pnl_curve < 0)
        # Lighten the polarity fill when class lines sit on top of it, so the
        # identity hues stay legible against it.
        fill_a = 0.10 if show_breakdown else 0.22

        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(
            x=total_pnl_curve.index, y=pos.fillna(0).values,
            mode="lines", line=dict(color="rgba(0,0,0,0)"),
            fill="tozeroy", fillcolor=f"rgba(61,220,151,{fill_a})",
            name="Winning", showlegend=False, hoverinfo="skip",
        ))
        fig3.add_trace(go.Scatter(
            x=total_pnl_curve.index, y=neg.fillna(0).values,
            mode="lines", line=dict(color="rgba(0,0,0,0)"),
            fill="tozeroy", fillcolor=f"rgba(255,107,129,{fill_a})",
            name="Losing", showlegend=False, hoverinfo="skip",
        ))
        if show_breakdown:
            for cls, s_cls in class_pnl.items():
                fig3.add_trace(go.Scatter(
                    x=s_cls.index, y=s_cls.values, mode="lines",
                    line=dict(color=CLASS_COLORS[cls], width=2),
                    name=ASSET_LABELS[cls],
                    hovertemplate=C + "%{y:,.0f}<extra>" + ASSET_LABELS[cls] + "</extra>",
                ))
        fig3.add_trace(go.Scatter(
            x=total_pnl_curve.index, y=total_pnl_curve.values,
            mode="lines", line=dict(color=INK_NEUTRAL, width=2.4),
            name="Total",
            hovertemplate=C + "%{y:,.0f}<extra>Total</extra>",
        ))
        fig3.add_hline(y=0, line_dash="dash", line_color="#888")
        peak_idx = total_pnl_curve.idxmax()
        trough_idx = total_pnl_curve.idxmin()
        fig3.add_trace(go.Scatter(
            x=[peak_idx, trough_idx],
            y=[total_pnl_curve.loc[peak_idx], total_pnl_curve.loc[trough_idx]],
            mode="markers+text",
            marker=dict(size=10, color=["#22c55e", "#f43f5e"],
                        line=dict(color="#0e1117", width=2)),
            text=["" if peak_idx == total_pnl_curve.index[-1]
                  else f"Peak {C}{total_pnl_curve.loc[peak_idx]:,.0f}",
                  "" if trough_idx == total_pnl_curve.index[-1]
                  else f"Trough {C}{total_pnl_curve.loc[trough_idx]:,.0f}"],
            textposition=["top center", "bottom center"],
            textfont=dict(color=INK_NEUTRAL),
            showlegend=False, hoverinfo="skip",
        ))
        # Direct end-labels so a series' identity never rests on colour alone,
        # staggered because two classes can finish at nearly the same P&L.
        if show_breakdown:
            ends = [(float(total_pnl_curve.iloc[-1]), "Total")]
            ends += [(float(s_cls.iloc[-1]), ASSET_LABELS[c])
                     for c, s_cls in class_pnl.items() if pd.notna(s_cls.iloc[-1])]
            stacked = pd.concat([total_pnl_curve] + list(class_pnl.values()))
            y_span = float(stacked.max() - stacked.min())
            for y_end, txt, shift in _stagger_labels(ends, y_span, plot_px=300):
                fig3.add_annotation(
                    x=total_pnl_curve.index[-1], y=y_end, yshift=shift,
                    text=txt, showarrow=False, xanchor="left", xshift=8,
                    font=dict(color="#e8edf5", size=11),
                    bgcolor="rgba(14,17,23,0.75)", borderpad=2,
                )
        fig3.update_layout(height=430, margin=dict(t=20, b=10, l=10, r=78),
                           paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           yaxis_title=f"{C} P&L", xaxis=dict(showgrid=False),
                           yaxis=dict(gridcolor=GRID_NEUTRAL, zerolinecolor="#888"),
                           hovermode="x unified",
                           legend=dict(orientation="h", yanchor="bottom", y=1.02))
        st.plotly_chart(fig3, use_container_width=True)

        pk1, pk2, pk3, pk4 = st.columns(4)
        pk1.metric("Current P&L", f"{C}{total_pnl_curve.iloc[-1]:,.0f}")
        pk2.metric("Peak P&L", f"{C}{total_pnl_curve.loc[peak_idx]:,.0f}",
                   help=f"on {peak_idx.date()}")
        pk3.metric("Trough P&L", f"{C}{total_pnl_curve.loc[trough_idx]:,.0f}",
                   help=f"on {trough_idx.date()}")
        pk4.metric("Days winning",
                   f"{int((total_pnl_curve >= 0).sum())} / {len(total_pnl_curve)}")

        # Table-view twin for the class lines (the metrics above cover the total).
        if show_breakdown:
            rows_p = []
            for cls, s_cls in class_pnl.items():
                sv = s_cls.dropna()
                if sv.empty:
                    continue
                rows_p.append({
                    "Class": ASSET_LABELS[cls],
                    f"Current ({C})": float(sv.iloc[-1]),
                    f"Peak ({C})": float(sv.max()),
                    f"Trough ({C})": float(sv.min()),
                    "Days winning": f"{int((sv >= 0).sum())} / {len(sv)}",
                })
            st.dataframe(
                pd.DataFrame(rows_p), hide_index=True, use_container_width=True,
                column_config={
                    f"Current ({C})": st.column_config.NumberColumn(format=f"{C}%.0f"),
                    f"Peak ({C})": st.column_config.NumberColumn(format=f"{C}%.0f"),
                    f"Trough ({C})": st.column_config.NumberColumn(format=f"{C}%.0f"),
                },
            )
            st.caption("Class lines sum to the aggregate. The bond is absent — it has "
                       "no price history, so it carries no time series.")


def render_bond_view(bond_list: list[bonds.Bond], inflation_pct: float) -> None:
    """Dedicated per-class view for the bonds (no CSV tabs): one section each."""
    for i, bond in enumerate(bond_list):
        if i:
            st.divider()
        _render_one_bond(bond, inflation_pct)


def _render_one_bond(bond: bonds.Bond, inflation_pct: float) -> None:
    st.subheader(f"Bond — {bond.isin}")
    freq_txt = {1: "annual", 2: "semiannual", 4: "quarterly"}.get(bond.frequency, f"{bond.frequency}×/yr")
    kind = "real" if bond.coupon_real else "nominal, fixed"
    pay_txt = "paid once at maturity" if bond.coupon_at_maturity else freq_txt
    st.caption(f"Maturity {bond.maturity.isoformat()} · coupon {bond.coupon_pct:.2f}% "
               f"({pay_txt}, {kind}) · {bond.currency} · nominal €{bond.nominal:,.0f}")

    ytm_r = bond.ytm_real()
    ytm_n = bond.ytm_nominal(inflation_pct)

    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Load value (clean)", f"€{bond.load_value:,.0f}",
              help=f"nominal × {bond.price_load:.4f}/100")
    a2.metric("Market value (clean)", f"€{bond.market_value:,.0f}",
              help=f"nominal × {bond.price_market:.4f}/100")
    a3.metric("P&L (capital)", f"€{bond.pnl:,.0f}", f"{bond.return_pct:+.2f}%")
    a4.metric("Accrued (rateo)", f"€{bond.accrued:,.0f}",
              help="Shown separately — NOT in P&L or aggregate market value.")

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Current yield", f"{bond.current_yield:.2f}%", help="Annual coupon ÷ market price.")
    if bond.coupon_real:
        b2.metric("YTM real", f"{ytm_r*100:.2f}%" if ytm_r is not None else "—",
                  help="IRR of real coupons + redemption at 100, given the market price.")
        b3.metric(f"YTM nominal (@{inflation_pct:.1f}%)",
                  f"{ytm_n*100:.2f}%" if ytm_n is not None else "—",
                  help="Fisher approximation: real YTM + assumed inflation.")
    else:
        b2.metric("YTM nominal", f"{ytm_n*100:.2f}%" if ytm_n is not None else "—",
                  help="IRR of fixed coupons + redemption at 100, given the market price.")
        b3.metric("Years to maturity", f"{(bond.maturity - date.today()).days / 365.25:.1f}")
    b4.metric("Next coupon", bond.next_coupon.isoformat(),
              help=(f"{bond.maturity_coupon():.2f} per €100 face, paid with the redemption"
                    if bond.coupon_at_maturity
                    else f"{bond.coupon_pct / bond.frequency:.3f}% ({kind}) per period"))

    if bond.coupon_real:
        st.caption("Inflation-linked: coupons are quoted in **real** terms; principal is uplifted by "
                   "realized inflation at redemption. YTM real is the inflation-adjusted yield; "
                   "nominal ≈ real + assumed inflation (Fisher). Set the inflation assumption in the sidebar.")
    else:
        st.caption("Fixed-rate: coupons are **nominal**, so the YTM is already a nominal yield — "
                   "the inflation assumption does not apply.")

    coupon_col = "Coupon (real)" if bond.coupon_real else "Coupon"
    st.markdown(f"##### Coupon schedule ({'real, ' if bond.coupon_real else ''}per €100 face)")
    sched = pd.DataFrame({"Date": [d.isoformat() for d in bond.coupon_dates()]})
    sched[coupon_col] = (bond.maturity_coupon() if bond.coupon_at_maturity
                         else bond.coupon_pct / bond.frequency)
    sched.loc[sched.index[-1], "Redemption"] = 100.0
    st.dataframe(
        sched, hide_index=True, use_container_width=True,
        column_config={
            coupon_col: st.column_config.NumberColumn(format="%.3f"),
            "Redemption": st.column_config.NumberColumn(format="%.0f"),
        },
        height=min(500, 38 * (len(sched) + 1)),
    )


if IS_GENERAL:
    render_general(tx_all, present_classes, bond_list)
    st.stop()

if IS_BOND:
    render_bond_view(bond_list, inflation_assumed)
    st.stop()

symbols = tuple(positions["symbol"].tolist())
quotes = get_quotes(symbols) if use_live else {}
price_map = {s: q["price"] for s, q in quotes.items()}
prev_map = {s: q["prev_close"] for s, q in quotes.items()}

# Display currency of this class view: the currency most of its market value is
# quoted in (Borsa Italiana ETFs → €). Positions quoted in another currency are
# converted into it below.
_pos_ccy = positions["symbol"].map(
    lambda s: (quotes.get(s) or {}).get("currency") or pr.guess_currency(s) or "USD")
_pos_mv = positions["qty"] * positions["symbol"].map(price_map).fillna(positions["snapshot_price"])
CLASS_CCY = str(_pos_mv.groupby(_pos_ccy).sum().idxmax()) if len(positions) else "USD"
CS = ui.CURRENCY_SYMBOLS.get(CLASS_CCY, CLASS_CCY + " ")
_other_ccy = sorted(positions.loc[_pos_ccy != CLASS_CCY, "symbol"])

# Convert every symbol quoted in another currency (e.g. RACE.MI in Stocks) into the
# class currency at today's rate, at the source — transactions, live quotes, and
# further down price history, dividends and fundamentals — so all tabs add up in
# one currency. FX_MULT: symbol → class-currency units per 1 unit of its currency.
FX_MULT: dict[str, float] = {}
for _s in sorted(set(tx["symbol"])):
    _c = (quotes.get(_s) or {}).get("currency") or pr.guess_currency(_s)
    if _c and _c != CLASS_CCY:
        _r = get_fx_rate(f"{_c}{CLASS_CCY}=X") if use_live else None
        if _r:
            FX_MULT[_s] = _r
if FX_MULT:
    _m = tx["symbol"].map(FX_MULT).fillna(1.0)
    tx = tx.assign(price=tx["price"] * _m, cashflow=tx["cashflow"] * _m,
                   snapshot_price=pd.to_numeric(tx["snapshot_price"], errors="coerce") * _m)
    all_positions = pf.build_positions(tx)
    positions = all_positions[all_positions["qty"] > 1e-6].reset_index(drop=True)
    price_map = {s: p * FX_MULT.get(s, 1.0) for s, p in price_map.items()}
    prev_map = {s: p * FX_MULT.get(s, 1.0) for s, p in prev_map.items()}
_fx_note = {s: FX_MULT[s] for s in _other_ccy if s in FX_MULT}
_other_ccy = [s for s in _other_ccy if s not in FX_MULT]


def _fx(sym: str) -> float:
    return FX_MULT.get(sym, 1.0)


def _fx_stats(sym: str, d: dict) -> dict:
    """Key stats with price-like fields in the class currency."""
    m = _fx(sym)
    if m == 1.0 or not d:
        return d
    out = dict(d)
    for k in ("target_mean", "target_low", "target_high", "market_cap"):
        if isinstance(out.get(k), (int, float)) and out[k] is not None:
            out[k] = out[k] * m
    return out


def _fx_frame(sym: str, df: pd.DataFrame) -> pd.DataFrame:
    m = _fx(sym)
    if m == 1.0 or df is None or df.empty:
        return df
    num = df.select_dtypes("number").columns
    return df.assign(**{c: df[c] * m for c in num})

positions = pf.enrich_with_prices(positions, price_map)
positions["prev_close"] = positions["symbol"].map(prev_map).fillna(positions["snapshot_price"])
positions["day_change_$"] = (positions["current_price"] - positions["prev_close"]) * positions["qty"]
positions["day_change_%"] = ((positions["current_price"] - positions["prev_close"])
                              / positions["prev_close"] * 100.0)

# Enrich all_positions too (closed positions have qty=0 → mkt_value=0, unrealized=0).
all_positions = pf.enrich_with_prices(all_positions, price_map)

# Lifetime cost/value stats — single source of truth for the Positions &
# Holdings tabs and the TROIC features. Built from all_positions (incl. closed)
# so every symbol ever traded is covered.
lifetime_stats = pf.build_lifetime_stats(all_positions, tx)

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

ts = datetime.now().strftime("%Y-%m-%d %H:%M")
src = "live (yfinance)" if use_live and quotes else "snapshot"
st.caption(f"As of {ts} · prices: **{src}** · {len(positions)} open positions · benchmark: **{benchmark}**")
if _fx_note:
    st.caption(f"💱 Convertiti in {CLASS_CCY} al cambio di oggi: " + " · ".join(
        f"{s} ({(quotes.get(s) or {}).get('currency') or pr.guess_currency(s)}→{CLASS_CCY} {r:.4f})"
        for s, r in _fx_note.items()))
if _other_ccy:
    st.caption(f"ℹ️ Importi in **{CLASS_CCY}**. {', '.join(_other_ccy)} "
               f"{'è quotato' if len(_other_ccy) == 1 else 'sono quotati'} in un'altra valuta "
               "e qui è sommato senza conversione (la vista Generale converte tutto).")

total_pnl_all = total_unrealized + total_realized

# Two extra return measures for the Total P&L card (per-class, native currency):
#  (a) Simple return on net cash — same formula as the per-class Performance tab.
#  (b) Realized return — realized P&L ÷ FIFO cost of the SOLD shares. For a
#      long-only book that cost equals (sell proceeds − realized), so no extra
#      lot-walking is needed. (Uncovered short sells would break this identity;
#      the app assumes long-only throughout.)
_buy_o = tx[tx["side"] == "BUY"]
_sell_o = tx[tx["side"] == "SELL"]
_deployed_o = float((_buy_o["qty"] * _buy_o["price"]).sum())
_returned_o = float((_sell_o["qty"] * _sell_o["price"]).sum())
_net_cash_o = _deployed_o - _returned_o
simple_on_net_o = (total_pnl_all / _net_cash_o * 100.0) if _net_cash_o > 1e-9 else None
_cost_of_sold_o = _returned_o - total_realized
realized_ret_o = (total_realized / _cost_of_sold_o * 100.0) if _cost_of_sold_o > 1e-9 else None
_son = f"{simple_on_net_o:+.2f}%" if simple_on_net_o is not None else "—"
_rr = f"{realized_ret_o:+.2f}%" if realized_ret_o is not None else "—"

ui.kpi_grid([
    ui.kpi("Market value", ui.money(total_mv, CS), f"{len(positions)} posizioni", hero=True),
    ui.kpi("Day change", ui.money(day_change_total, CS), ui.pct(day_change_pct),
           positive=day_change_total >= 0),
    ui.kpi("Unrealized P&L", ui.money(total_unrealized, CS),
           ui.pct(total_unrealized / total_invested * 100 if total_invested else 0) + " sul costo",
           positive=total_unrealized >= 0),
    ui.kpi("Realized P&L", ui.money(total_realized, CS),
           f"Realized {_rr}" if realized_ret_o is not None else "da lotti chiusi",
           positive=(realized_ret_o >= 0) if realized_ret_o is not None else None),
    ui.kpi("Total P&L", ui.money(total_pnl_all, CS), f"Simple/net cash {_son}",
           positive=(simple_on_net_o >= 0) if simple_on_net_o is not None else None),
    ui.kpi("XIRR (MWR)", ui.pct(port_xirr * 100) if port_xirr else "n/a",
           "money-weighted, annuo", positive=(port_xirr or 0) >= 0),
])

# ---------- Build TWR series (used by multiple tabs) -------------------------

# Use ALL symbols ever traded (not just open) so the curve correctly reflects:
#   - the value of closed positions during the time they were held
#   - the cash inflow/outflow when they were sold
# Otherwise the "Total P&L over time" chart misses every closed position's realized P&L.
# "Dall'inizio": the shortest Yahoo period that reaches back to this class's first
# trade, so the charts start on that day (trim_to_first_holding drops the rest).
if period == "Dall'inizio":
    _age_days = (pd.Timestamp(date.today()) - tx["trade_date"].min()).days
    period = next((p for p, d in (("1y", 360), ("2y", 725), ("5y", 1820), ("10y", 3645))
                   if _age_days <= d), "max")
hist = get_history(tuple(all_symbols_ever), period) if pr.HAS_YF else pd.DataFrame()
if FX_MULT and not hist.empty:
    hist = hist.assign(**{s: hist[s] * m for s, m in FX_MULT.items() if s in hist.columns})
twr_growth = pd.Series(dtype=float)
bench_growth = pd.Series(dtype=float)
value_series = pd.Series(dtype=float)

if not hist.empty:
    value_series, cf_series = mt.build_value_series(tx, hist)
    if not value_series.empty and (value_series > 0).any():
        # Trim leading zeros (before first holding); pre-window cash is carried
        # onto the new first bar so cf_series.cumsum() stays inception-to-date.
        value_series, cf_series = mt.trim_to_first_holding(value_series, cf_series)
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

# on_change="rerun" makes the tabs lazy: each tab exposes `.open` and only the
# selected one executes, instead of all 13 (with their Yahoo calls) on every rerun.
(tab_overview, tab_recap, tab_posttax, tab_today, tab_pos, tab_perf, tab_daily,
 tab_holdings, tab_alloc, tab_risk, tab_div, tab_weekly, tab_lots) = st.tabs([
    ":material/dashboard: Overview", ":material/summarize: Recap",
    ":material/calculate: Post-tax", ":material/today: Today",
    ":material/list_alt: Positions", ":material/show_chart: Performance",
    ":material/calendar_month: Daily", ":material/sell: Holdings",
    ":material/donut_large: Allocation", ":material/shield: Risk",
    ":material/payments: Dividends", ":material/date_range: Weekly",
    ":material/receipt_long: Lots"
], key="class_tab", on_change="rerun")

# ---------- Overview ---------------------------------------------------------

with tab_overview:
    if tab_overview.open:  # lazy: only the selected tab runs
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
                    color_discrete_sequence=ui.PALETTE,
                    custom_data=["holdings", "return_pct", "pct"],
                )
                fig.update_traces(
                    textposition="outside", textinfo="label+percent",
                    marker=dict(line=dict(color="#0e1117", width=2)),
                    hovertemplate=("<b>%{label}</b><br>" + CS + "%{value:,.0f}"
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
                            "Mkt Value": st.column_config.NumberColumn(format=f"{CS}%.0f"),
                            "Return %": st.column_config.NumberColumn(format="%.1f%%"),
                            "Unrlzd P&L": st.column_config.NumberColumn(format=f"{CS}%.0f"),
                        },
                        height=min(420, 38 * (len(detail_show) + 1)),
                    )
                    sub_mv = float(detail["market_value"].sum())
                    sub_pnl = float(detail["unrealized_pnl"].sum())
                    sub_inv = float(detail["market_value"].sum() - detail["unrealized_pnl"].sum())
                    sub_ret = (sub_pnl / sub_inv * 100.0) if sub_inv > 0 else 0.0
                    dd1, dd2, dd3 = st.columns(3)
                    dd1.metric("Holdings", len(detail))
                    dd2.metric("Mkt value", f"{CS}{sub_mv:,.0f}")
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
                         color_discrete_sequence=ui.PALETTE)
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
                marker_color=["#22c55e" if v >= 0 else "#f43f5e" for v in movers["day_change_%"]],
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
            marker_color=["#22c55e" if v >= 0 else "#f43f5e" for v in contrib["total_pnl"]],
            text=[f"{CS}{v:,.0f} ({p:.1f}%)" for v, p in zip(contrib["total_pnl"], contrib["contribution_pct"])],
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
    if tab_recap.open:  # lazy: only the selected tab runs
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
        r1.metric("Total capital deployed", f"{CS}{total_deployed:,.0f}",
                  help=f"Cumulative {CS} spent on all BUYs across history")
        r2.metric("Total capital returned", f"{CS}{total_returned:,.0f}",
                  help=f"Cumulative {CS} received from all SELLs")
        r3.metric("Net cash invested", f"{CS}{net_cash_in:,.0f}",
                  help="Deployed − Returned (net money put into the portfolio)")
        r4.metric("Current capital invested", f"{CS}{current_invested:,.0f}",
                  help="Cost basis of currently-open positions")

        st.markdown("---")

        col_r, col_u = st.columns(2)
        with col_r:
            st.subheader("💵 Realized")
            rg, rl, rn = st.columns(3)
            rg.metric("Gains", f"{CS}{real_g:,.0f}",
                      help=f"{(all_positions['realized_pnl'] > 0).sum()} winning closed/partial positions")
            rl.metric("Losses", f"{CS}{real_l:,.0f}",
                      help=f"{(all_positions['realized_pnl'] < 0).sum()} losing closed/partial positions")
            rn.metric("Net realized", f"{CS}{net_real:,.0f}")

        with col_u:
            st.subheader("📈 Unrealized")
            ug, ul, un = st.columns(3)
            ug.metric("Gains", f"{CS}{unr_g:,.0f}",
                      help=f"{(positions['unrealized_pnl'] > 0).sum()} winning open positions")
            ul.metric("Losses", f"{CS}{unr_l:,.0f}",
                      help=f"{(positions['unrealized_pnl'] < 0).sum()} losing open positions")
            un.metric("Net unrealized", f"{CS}{net_unr:,.0f}")

        # Aggregate TROIC = Σ lifetime value / Σ lifetime invested − 1 (across ALL
        # symbols ever traded, incl. closed). Single source of truth: lifetime_stats.
        if not lifetime_stats.empty:
            troic_value_total = float(lifetime_stats["total_value_lifetime"].sum())
            troic_cost_total = float(lifetime_stats["total_invested_lifetime"].sum())
            agg_troic = (troic_value_total / troic_cost_total - 1.0) if troic_cost_total > 0 else None
        else:
            agg_troic = None

        st.markdown("---")
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Total P&L", f"{CS}{total_pnl_recap:,.0f}",
                  help="Net realized + Net unrealized")
        t2.metric("Return on deployed capital", f"{return_on_deployed:+.2f}%")
        t3.metric("TROIC", f"{agg_troic*100:+.2f}%" if agg_troic is not None else "—",
                  help="Total Return on Invested Capital. Per ogni € speso comprando shares "
                       "nella vita del portfolio (anche su posizioni poi chiuse), quanto vale "
                       "oggi tra valore di mercato aperte + cassa rientrata dalle vendite. "
                       "Diverso da Return on Deployed: TROIC misura il moltiplicatore sui "
                       "soldi investiti TOTALI, non sul net cash attualmente esposto.")
        t4.metric("Portfolio XIRR", f"{port_xirr*100:.2f}%" if port_xirr else "—",
                  help="Money-weighted annualized return")

        st.subheader("Gain / loss breakdown (visual)")
        bd = pd.DataFrame({
            "category": ["Realized gains", "Realized losses", "Unrealized gains", "Unrealized losses"],
            "value": [real_g, real_l, unr_g, unr_l],
        })
        fig = go.Figure(go.Bar(
            x=bd["category"], y=bd["value"],
            marker_color=["#22c55e", "#f43f5e", "#22c55e", "#f43f5e"],
            text=[f"{CS}{v:,.0f}" for v in bd["value"]],
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
                    "unrealized_pnl": st.column_config.NumberColumn("Unrealized", format=f"{CS}%.0f"),
                    "realized_pnl": st.column_config.NumberColumn("Realized", format=f"{CS}%.0f"),
                    "total_pnl": st.column_config.NumberColumn("Total", format=f"{CS}%.0f"),
                },
            )
        with cl:
            st.markdown("**Losers**")
            st.dataframe(
                contrib[contrib["total_pnl"] < 0].sort_values("total_pnl").head(10)[
                    ["symbol", "unrealized_pnl", "realized_pnl", "total_pnl"]],
                use_container_width=True, hide_index=True,
                column_config={
                    "unrealized_pnl": st.column_config.NumberColumn("Unrealized", format=f"{CS}%.0f"),
                    "realized_pnl": st.column_config.NumberColumn("Realized", format=f"{CS}%.0f"),
                    "total_pnl": st.column_config.NumberColumn("Total", format=f"{CS}%.0f"),
                },
            )

# ---------- Post-tax (Italian capital-gain simulator) -----------------------

with tab_posttax:
    if tab_posttax.open:  # lazy: only the selected tab runs
        st.subheader("Italian capital-gain tax simulator")
        st.info(
            "⚠️ Simulatore semplificato per uso personale. Non sostituisce "
            "il Quadro RT della dichiarazione dei redditi.\n\n"
            "Aliquota: 26% sui capital gain non qualificati (regime ordinario).\n\n"
            "Compensazione minusvalenze: questo simulatore le riporta a vita; "
            "il regime italiano reale ha limite di 4 anni fiscali."
        )

        # Per-tab input (kept in the tab body, not the sidebar: Streamlit renders all
        # tabs together and does not expose the active tab to the sidebar).
        prior_loss = st.number_input(
            "Minusvalenze pregresse non riassorbite (€)",
            min_value=0.0, value=0.0, step=100.0,
            help="Inserisci eventuali minusvalenze realizzate in anni precedenti "
                 "non coperte dal CSV.",
        )

        realized_by_year = tax.compute_realized_pnl_by_year(tx)
        short_skipped = realized_by_year.attrs.get("short_skipped", {})
        post_tax = tax.compute_post_tax_table(realized_by_year, initial_carryforward=prior_loss)

        if short_skipped:
            detail = ", ".join(f"{s}: {q:,.0f} sh" for s, q in short_skipped.items())
            st.warning(
                f"⚠️ Short positions skipped in realized P&L (sells exceeding buys): {detail}. "
                "These shares have no cost basis and are excluded — same convention as the "
                "rest of the app."
            )

        if post_tax.empty:
            st.info("No realized sales found in the transactions — nothing to tax yet.")
        else:
            total_realized_net = float(post_tax["net"].sum())
            total_imposta = float(post_tax["imposta"].sum())
            total_post_tax = float(post_tax["net_post_tax"].sum())
            carry_residuo = float(post_tax["carryforward_uscente"].iloc[-1])

            pc1, pc2, pc3, pc4 = st.columns(4)
            pc1.metric("Realized lordo (pre-tax)", f"€{total_realized_net:,.0f}",
                       help="Somma dei net realizzati per anno (gain + loss), prima delle imposte.")
            pc2.metric("Imposta dovuta", f"€{total_imposta:,.0f}",
                       help="Somma delle imposte annue (26% sulla base imponibile dopo compensazione).")
            pc3.metric("Post-tax", f"€{total_post_tax:,.0f}",
                       help="Realized netto meno imposta.")
            pc4.metric("Carryforward residuo", f"€{carry_residuo:,.0f}",
                       help="Minusvalenze non ancora compensate, riportabili agli anni successivi "
                            "(valore ≤ 0).")

            st.markdown("##### Anno per anno")
            show_pt = post_tax.rename(columns={
                "year": "Anno", "gain_lordo": "Gain lordo", "loss_lordo": "Loss lordo",
                "net": "Net", "carryforward_entrante": "Carry entrante",
                "net_compensato": "Net compensato", "imposta": "Imposta",
                "net_post_tax": "Net post-tax", "carryforward_uscente": "Carry uscente",
            })
            st.dataframe(
                show_pt, use_container_width=True, hide_index=True,
                column_config={
                    "Anno": st.column_config.NumberColumn(format="%d"),
                    "Gain lordo": st.column_config.NumberColumn(format="€%.0f"),
                    "Loss lordo": st.column_config.NumberColumn(format="€%.0f"),
                    "Net": st.column_config.NumberColumn(format="€%.0f"),
                    "Carry entrante": st.column_config.NumberColumn(format="€%.0f"),
                    "Net compensato": st.column_config.NumberColumn(format="€%.0f"),
                    "Imposta": st.column_config.NumberColumn(format="€%.0f"),
                    "Net post-tax": st.column_config.NumberColumn(format="€%.0f"),
                    "Carry uscente": st.column_config.NumberColumn(format="€%.0f"),
                },
            )

            # ----- Dual equity curve: pre-tax (cumulative Total P&L) vs post-tax -----
            st.subheader("Equity curve: pre-tax vs post-tax")
            if value_series.empty:
                st.caption("⚠️ Need yfinance + price history to draw the equity curve. "
                           "The table above is independent of price history.")
            else:
                cum_dep = cf_series.cumsum()
                pretax_curve = value_series - cum_dep  # cumulative mark-to-market P&L

                # Cumulative tax as a step function: year Y's tax lands at Y-12-31.
                imposta_by_year = post_tax.set_index("year")["imposta"].to_dict()

                def _cum_tax_at(d):
                    total = 0.0
                    for y, imp in imposta_by_year.items():
                        if d.year > y or (d.year == y and (d.month, d.day) >= (12, 31)):
                            total += imp
                    return total

                cum_tax = pd.Series(
                    [_cum_tax_at(ts.date() if hasattr(ts, "date") else ts)
                     for ts in pretax_curve.index],
                    index=pretax_curve.index,
                )
                posttax_curve = pretax_curve - cum_tax

                fig_pt = go.Figure()
                fig_pt.add_trace(go.Scatter(
                    x=pretax_curve.index, y=pretax_curve.values, mode="lines",
                    line=dict(color="#7c8eff", width=2), name="Pre-tax",
                    hovertemplate="%{x|%Y-%m-%d}<br>€%{y:,.0f}<extra>Pre-tax</extra>",
                ))
                fig_pt.add_trace(go.Scatter(
                    x=posttax_curve.index, y=posttax_curve.values, mode="lines",
                    line=dict(color="#22c55e", width=2), name="Post-tax",
                    hovertemplate="%{x|%Y-%m-%d}<br>€%{y:,.0f}<extra>Post-tax</extra>",
                ))
                fig_pt.add_hline(y=0, line_dash="dash", line_color="#666")
                fig_pt.update_layout(height=380, margin=dict(t=10, b=10, l=10, r=10),
                                     paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                     yaxis_title="€ cumulative P&L", xaxis=dict(showgrid=False),
                                     yaxis=dict(gridcolor="#222", zerolinecolor="#666"),
                                     legend=dict(orientation="h", yanchor="bottom", y=1.02))
                st.plotly_chart(fig_pt, use_container_width=True)
                st.caption("Pre-tax = cumulative mark-to-market P&L (market value − net cash invested). "
                           "Post-tax subtracts cumulative tax as a step at each 31 Dec. "
                           "Approximation: the tax applies to realized gains only, here overlaid as an "
                           "annual step onto a mark-to-market curve.")

# ---------- Today (per-stock day move) --------------------------------------

with tab_today:
    if tab_today.open:  # lazy: only the selected tab runs
        st.subheader("Per-stock performance today")
        td = positions[["symbol", "qty", "current_price", "prev_close",
                        "day_change_$", "day_change_%", "market_value"]].copy()
        td = td.dropna(subset=["day_change_%"]).sort_values("day_change_%", ascending=False).reset_index(drop=True)

        total_today_dollar = float(td["day_change_$"].sum())
        weighted_pct = (total_today_dollar / float(td["market_value"].sum()) * 100.0) if len(td) else 0.0
        n_up = int((td["day_change_$"] > 0).sum())
        n_dn = int((td["day_change_$"] < 0).sum())

        t1, t2, t3, t4 = st.columns(4)
        t1.metric(f"Total {CS} change today", f"{CS}{total_today_dollar:,.0f}")
        t2.metric("Value-weighted %", f"{weighted_pct:+.2f}%")
        t3.metric("Up / Down", f"{n_up} / {n_dn}")
        if len(td):
            t4.metric("Best", f"{td['symbol'].iloc[0]}",
                      f"{td['day_change_%'].iloc[0]:+.2f}%")

        st.subheader(f"{CS} contribution to today's move")
        bars = td.copy()
        bars["sort_key"] = bars["day_change_$"].abs()
        bars = bars.sort_values("sort_key", ascending=True).tail(40)
        fig = go.Figure(go.Bar(
            x=bars["day_change_$"], y=bars["symbol"], orientation="h",
            marker_color=["#22c55e" if v >= 0 else "#f43f5e" for v in bars["day_change_$"]],
            text=[f"{CS}{v:,.0f} ({p:+.2f}%)" for v, p in zip(bars["day_change_$"], bars["day_change_%"])],
            textposition="outside",
        ))
        fig.update_layout(height=max(420, len(bars) * 22), margin=dict(t=20, b=10, l=10, r=140),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          xaxis_title=f"{CS} change today",
                          xaxis=dict(zerolinecolor="#666"),
                          yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Detail")
        # RSI(14, Wilder) from the already-downloaded price history — no extra fetch.
        # "—" when the symbol is missing from hist or has < 15 days of data.
        def _rsi_str(sym: str) -> str:
            if not isinstance(hist, pd.DataFrame) or hist.empty or sym not in hist.columns:
                return "—"
            try:
                v = mt.compute_rsi(hist[sym], 14)
            except Exception:
                # One bad/odd-dtype symbol must not crash the whole Detail table.
                return "—"
            return f"{v:.0f}" if v is not None else "—"
        td = td.copy()
        td["RSI"] = td["symbol"].map(_rsi_str)
        show_td = td.rename(columns={
            "symbol": "Symbol", "qty": "Qty",
            "current_price": "Price", "prev_close": "Prev Close",
            "day_change_$": f"{CS} Change", "day_change_%": "% Change",
            "market_value": "Mkt Value",
        })
        st.dataframe(
            show_td, use_container_width=True, hide_index=True,
            column_config={
                "Qty": st.column_config.NumberColumn(format="%.2f"),
                "Price": st.column_config.NumberColumn(format=f"{CS}%.2f"),
                "Prev Close": st.column_config.NumberColumn(format=f"{CS}%.2f"),
                f"{CS} Change": st.column_config.NumberColumn(format=f"{CS}%.2f"),
                "% Change": st.column_config.NumberColumn(format="%.2f%%"),
                "Mkt Value": st.column_config.NumberColumn(format=f"{CS}%.0f"),
                "RSI": st.column_config.TextColumn("RSI", help="Relative Strength Index (14, Wilder). "
                                                   ">70 overbought · <30 oversold."),
            },
            height=min(700, 38 * (len(show_td) + 1)),
        )

# ---------- Positions -------------------------------------------------------

with tab_pos:
    if tab_pos.open:  # lazy: only the selected tab runs
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
            # ----- Lifetime stats per symbol (single source of truth: build_lifetime_stats)
            ls = lifetime_stats

            base["status"] = base["qty"].apply(lambda q: "Open" if q > 1e-6 else "Closed")
            live_day = positions.set_index("symbol")["day_change_%"].to_dict()
            base["day_change_%"] = base["symbol"].map(live_day)

            base["avg_buy_lifetime"] = base["symbol"].map(ls["avg_buy_lifetime"])
            base["avg_sale_price"] = base["symbol"].map(ls["avg_sale_lifetime"])
            base["total_sell_qty"] = base["symbol"].map(ls["gross_sells_qty"]).fillna(0.0)
            base["gross_buys"] = base["symbol"].map(ls["total_invested_lifetime"]).fillna(0.0)

            # Lifetime performance columns (Feature 2): Total Cost / Total Value / TROIC %
            base["total_cost"] = base["symbol"].map(ls["total_invested_lifetime"]).fillna(0.0)
            base["total_value"] = base["symbol"].map(ls["total_value_lifetime"]).fillna(0.0)
            base["troic_pct"] = base["symbol"].map(ls["troic"]) * 100.0

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
                "return_pct_display", "total_cost", "total_value", "troic_pct",
                "avg_sale_price", "dollar_since_sale", "pct_since_sale",
                "xirr_pct", "first_buy"
            ]].rename(columns={
                "symbol": "Symbol", "status": "Status",
                "qty": "Qty", "avg_cost_display": "Avg Cost",
                "current_price": "Price", "market_value": "Mkt Value",
                "day_change_%": "Day %", "unrealized_pnl": "Unrlzd P&L",
                "realized_pnl": "Rlzd P&L", "total_pnl": "Total P&L",
                "return_pct_display": "Return %",
                "total_cost": "Total Cost",
                "total_value": "Total Value",
                "troic_pct": "TROIC %",
                "avg_sale_price": "Avg Sale Price",
                "dollar_since_sale": f"{CS} Since Sale",
                "pct_since_sale": "% Since Sale",
                "xirr_pct": "XIRR",
                "first_buy": "First Buy",
            })

            st.dataframe(
                display, use_container_width=True, hide_index=True,
                column_config={
                    "Qty": st.column_config.NumberColumn(format="%.2f"),
                    "Avg Cost": st.column_config.NumberColumn(format=f"{CS}%.2f"),
                    "Price": st.column_config.NumberColumn(format=f"{CS}%.2f"),
                    "Mkt Value": st.column_config.NumberColumn(format=f"{CS}%.0f"),
                    "Day %": st.column_config.NumberColumn(format="%.2f%%"),
                    "Unrlzd P&L": st.column_config.NumberColumn(format=f"{CS}%.0f"),
                    "Rlzd P&L": st.column_config.NumberColumn(format=f"{CS}%.0f"),
                    "Total P&L": st.column_config.NumberColumn(format=f"{CS}%.0f"),
                    "Return %": st.column_config.NumberColumn(format="%.1f%%"),
                    "Total Cost": st.column_config.NumberColumn(
                        format=f"{CS}%.0f",
                        help="Lifetime invested capital: Σ (qty × price) over all BUYs for this symbol.",
                    ),
                    "Total Value": st.column_config.NumberColumn(
                        format=f"{CS}%.0f",
                        help="Lifetime value: current market value of open shares + cash returned from all SELLs.",
                    ),
                    "TROIC %": st.column_config.NumberColumn(
                        format="%.1f%%",
                        help="Total Return on Invested Capital: Total Value ÷ Total Cost − 1.",
                    ),
                    "Avg Sale Price": st.column_config.NumberColumn(format=f"{CS}%.2f"),
                    f"{CS} Since Sale": st.column_config.NumberColumn(
                        format=f"{CS}%.0f",
                        help="Positive = price went up after sale (missed gains). "
                             "Negative = price went down after sale (sold well).",
                    ),
                    "% Since Sale": st.column_config.NumberColumn(
                        format="%.2f%%",
                        help=f"Same sign convention as {CS} Since Sale.",
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

            # Lifetime TROIC over the visible subset: recompute from summed Cost/Value,
            # NOT the mean of per-row TROIC % (which would be wrong).
            tot_total_cost = float(base["total_cost"].sum())
            tot_total_value = float(base["total_value"].sum())
            tot_troic_pct = ((tot_total_value / tot_total_cost - 1.0) * 100.0
                             if tot_total_cost > 0 else None)

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
                "Total Cost": tot_total_cost,
                "Total Value": tot_total_value,
                "TROIC %": tot_troic_pct,
                f"{CS} Since Sale": ss_dollar_total if sale_value_total > 0 else None,
                "% Since Sale": tot_pct_since_sale,
                "XIRR": f"{subset_xirr*100:.1f}%" if subset_xirr is not None else "—",
            }])
            st.markdown("##### Totals")
            st.dataframe(
                total_row, use_container_width=True, hide_index=True,
                column_config={
                    "Mkt Value": st.column_config.NumberColumn(format=f"{CS}%.0f"),
                    "Unrlzd P&L": st.column_config.NumberColumn(format=f"{CS}%.0f"),
                    "Rlzd P&L": st.column_config.NumberColumn(format=f"{CS}%.0f"),
                    "Total P&L": st.column_config.NumberColumn(format=f"{CS}%.0f"),
                    "Return %": st.column_config.NumberColumn(format="%.2f%%"),
                    "Total Cost": st.column_config.NumberColumn(format=f"{CS}%.0f"),
                    "Total Value": st.column_config.NumberColumn(format=f"{CS}%.0f"),
                    "TROIC %": st.column_config.NumberColumn(format="%.1f%%"),
                    f"{CS} Since Sale": st.column_config.NumberColumn(format=f"{CS}%.0f"),
                    "% Since Sale": st.column_config.NumberColumn(format="%.2f%%"),
                },
            )

            csv_out = display.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Download CSV", csv_out, "positions.csv", "text/csv")

# ---------- Performance -----------------------------------------------------

with tab_perf:
    if tab_perf.open:  # lazy: only the selected tab runs
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
                color = ui.POS if (val or 0) >= 0 else ui.NEG
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
            # When the History period starts after the first trade, the line above
            # would open at the since-inception return (e.g. +37%) while the
            # benchmark opens at 0. Rebase it to the window's first day instead.
            win_start = value_series.index[0]
            rebased = tx["trade_date"].min() < win_start
            if rebased:
                simple_curve = trend.period_curve(value_series, cf_series, win_start)

            if chart_mode.startswith("TWR"):
                port_y = (twr_growth - 1) * 100
                port_label = "Portfolio (TWR)"
                sub = f"TWR vs {benchmark}" if benchmark != "None" else "TWR"
            else:
                port_y = simple_curve * 100
                port_label = "Portfolio (simple return on net cash)"
                sub = f"Simple return vs {benchmark}" if benchmark != "None" else "Simple return"

            st.subheader(sub)
            if rebased and not chart_mode.startswith("TWR"):
                st.caption(f"Parte da 0 il {win_start:%d/%m/%Y}, inizio del periodo scelto in "
                           f"*History period*, come {benchmark}. Il rendimento dall'inizio di "
                           "tutto è nei riquadri in alto.")
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=port_y.index, y=port_y.values, mode="lines",
                line=dict(color="#22c55e", width=2.4),
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
            st.subheader(f"Equity curve ({CS})")
            st.caption("Blue = market value of holdings. Amber = cumulative net cash invested "
                       "(buys − sells). Gap between them = mark-to-market total P&L.")
            cum_capital_curve = cf_series.cumsum()
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(
                x=value_series.index, y=value_series.values, mode="lines",
                line=dict(color="#7c8eff", width=2),
                fill="tozeroy", fillcolor="rgba(124,142,255,0.08)",
                name="Market value",
                hovertemplate="%{x|%Y-%m-%d}<br>" + CS + "%{y:,.0f}<extra>Market value</extra>",
            ))
            fig2.add_trace(go.Scatter(
                x=cum_capital_curve.index, y=cum_capital_curve.values, mode="lines",
                line=dict(color="#f4b942", width=2, dash="dot"),
                name="Net capital invested",
                hovertemplate="%{x|%Y-%m-%d}<br>" + CS + "%{y:,.0f}<extra>Net capital</extra>",
            ))
            fig2.update_layout(height=360, margin=dict(t=10, b=10, l=10, r=10),
                               paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                               yaxis_title=CS, xaxis=dict(showgrid=False),
                               yaxis=dict(gridcolor="#222"),
                               legend=dict(orientation="h", yanchor="bottom", y=1.02))
            st.plotly_chart(fig2, use_container_width=True)

            # Cumulative absolute $ P&L over time
            st.subheader(f"Total P&L over time ({CS})")
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
                hovertemplate="%{x|%Y-%m-%d}<br>" + CS + "%{y:,.0f}<extra></extra>",
            ))
            fig3.add_hline(y=0, line_dash="dash", line_color="#666")
            # Mark peak and trough
            peak_idx = total_pnl_curve.idxmax()
            trough_idx = total_pnl_curve.idxmin()
            fig3.add_trace(go.Scatter(
                x=[peak_idx, trough_idx],
                y=[total_pnl_curve.loc[peak_idx], total_pnl_curve.loc[trough_idx]],
                mode="markers+text",
                marker=dict(size=10, color=["#22c55e", "#f43f5e"],
                            line=dict(color="#0e1117", width=2)),
                text=[f"Peak {CS}{total_pnl_curve.loc[peak_idx]:,.0f}",
                      f"Trough {CS}{total_pnl_curve.loc[trough_idx]:,.0f}"],
                textposition=["top center", "bottom center"],
                textfont=dict(color="#e8edf5"),
                showlegend=False, hoverinfo="skip",
            ))
            fig3.update_layout(height=380, margin=dict(t=20, b=10, l=10, r=10),
                               paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                               yaxis_title=f"{CS} P&L", xaxis=dict(showgrid=False),
                               yaxis=dict(gridcolor="#222", zerolinecolor="#666"))
            st.plotly_chart(fig3, use_container_width=True)

            pk1, pk2, pk3, pk4 = st.columns(4)
            pk1.metric("Current P&L", f"{CS}{total_pnl_curve.iloc[-1]:,.0f}")
            pk2.metric("Peak P&L",
                       f"{CS}{total_pnl_curve.loc[peak_idx]:,.0f}",
                       help=f"on {peak_idx.date()}")
            pk3.metric("Trough P&L",
                       f"{CS}{total_pnl_curve.loc[trough_idx]:,.0f}",
                       help=f"on {trough_idx.date()}")
            pk4.metric("Days winning",
                       f"{int((total_pnl_curve >= 0).sum())} / {len(total_pnl_curve)}")

# ---------- Daily (last 30 trading days) ------------------------------------

with tab_daily:
    if tab_daily.open:  # lazy: only the selected tab runs
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
            m1.metric(f"{n_days}d {CS} change (market)", f"{CS}{total_dollar:,.0f}")
            m2.metric(window_label, f"{window_growth*100:+.2f}%")
            m3.metric("Best day",
                      f"{best['pct']:+.2f}%",
                      f"{CS}{best['dollar']:,.0f} · {best['date'].date()}")
            m4.metric("Worst day",
                      f"{worst['pct']:+.2f}%",
                      f"{CS}{worst['dollar']:,.0f} · {worst['date'].date()}")

            st.subheader(f"Daily {pct_label} — last {n_days} trading days")
            bars = df_daily.iloc[::-1]  # back to chronological for chart
            fig = go.Figure(go.Bar(
                x=bars["date"], y=bars["pct"],
                marker_color=["#22c55e" if v >= 0 else "#f43f5e" for v in bars["pct"]],
                text=[f"{v:+.2f}%<br>{CS}{d:,.0f}" for v, d in zip(bars["pct"], bars["dollar"])],
                textposition="outside",
                hovertemplate="%{x|%Y-%m-%d}<br>%{y:.2f}%<br>" + CS + "%{customdata:,.0f}<extra></extra>",
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
                    "dollar": st.column_config.NumberColumn(f"{CS} change", format=f"{CS}%.0f"),
                    "value": st.column_config.NumberColumn("End-of-day value", format=f"{CS}%.0f"),
                },
                height=min(700, 38 * (len(df_show) + 1)),
            )

# ---------- Holdings (per-symbol with buy/sell markers) ---------------------

with tab_holdings:
    if tab_holdings.open:  # lazy: only the selected tab runs
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
                    h = _fx_frame(selected, pr.fetch_history(selected, period=holding_period))

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
                # Lifetime stats for this symbol (single source of truth)
                _ls = lifetime_stats.loc[selected] if selected in lifetime_stats.index else None
                total_buy_qty = float(_ls["gross_buys_qty"]) if _ls is not None else 0.0
                total_sell_qty = float(_ls["gross_sells_qty"]) if _ls is not None else 0.0
                avg_buy_lifetime = (float(_ls["avg_buy_lifetime"])
                                    if _ls is not None and pd.notna(_ls["avg_buy_lifetime"]) else None)
                avg_sale_price = (float(_ls["avg_sale_lifetime"])
                                  if _ls is not None and pd.notna(_ls["avg_sale_lifetime"]) else None)
                gross_buys = float(_ls["total_invested_lifetime"]) if _ls is not None else 0.0

                # If closed, override avg-cost display with lifetime avg buy
                avg_cost_show = (cur_inv / cur_qty) if cur_qty > 1e-6 else avg_buy_lifetime

                # Company description (yfinance fundamentals — same fetch reused below)
                key_top = _fx_stats(selected, get_key_stats(selected))
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
                        return f"{CS}{m/1e12:.2f}T"
                    if m >= 1e9:
                        return f"{CS}{m/1e9:.2f}B"
                    if m >= 1e6:
                        return f"{CS}{m/1e6:.1f}M"
                    return f"{CS}{m:,.0f}"

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
                sk2.metric("Avg cost", f"{CS}{avg_cost_show:.2f}" if avg_cost_show is not None else "—")
                sk3.metric("Mkt value", f"{CS}{mkt_value:,.0f}")
                sk4.metric("Unrealized P&L", f"{CS}{unreal:,.0f}", f"{gain_pct:+.2f}%")
                sk5.metric("Realized P&L", f"{CS}{cur_real:,.0f}")
                sk6.metric("Total P&L", f"{CS}{total_pnl_sym:,.0f}")
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
                    ss1.metric("Avg sale price", f"{CS}{avg_sale_price:.2f}",
                               help=f"{total_sell_qty:,.0f} shares sold, weighted average")
                    ss2.metric(f"{CS} since sale", f"{CS}{ss_dollar:,.0f}",
                               help="Positive = price went up since sale (missed gains). "
                                    "Negative = price went down since (sold well).")
                    ss3.metric("% since sale", f"{ss_pct:+.2f}%")
                    ss4.metric("If you'd held all", f"{CS}{hold_value_now:,.0f}",
                               f"{missed:+,.0f} vs actual",
                               help=f"Value today if you'd never sold ({hold_qty:,.0f} shares × "
                                    f"{CS}{cur_price:.2f}). The delta shows how much you missed "
                                    f"(positive) or saved (negative) by selling.")

                # ----- Key data ----------------------------------------------------
                st.markdown("---")
                st.markdown("##### Key data")
                with st.spinner("Loading fundamentals…"):
                    key = _fx_stats(selected, get_key_stats(selected))
                    ann_fin = _fx_frame(selected, get_annual_financials(selected))
                    qtr_fin = _fx_frame(selected, get_quarterly_financials(selected))

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

                # Format earnings date with days-from-today
                ne_raw = key.get("next_earnings")
                ne_str = "—"
                ne_sub = None
                if ne_raw is not None:
                    try:
                        ne_ts = pd.Timestamp(ne_raw)
                        if hasattr(ne_ts, "tz") and ne_ts.tz is not None:
                            ne_ts = ne_ts.tz_localize(None)
                        ne_str = ne_ts.strftime("%Y-%m-%d")
                        days = (ne_ts.normalize() - pd.Timestamp(today).normalize()).days
                        if days > 0:
                            ne_sub = f"in {days}d"
                        elif days == 0:
                            ne_sub = "today"
                        else:
                            ne_sub = f"{-days}d ago"
                    except Exception:
                        pass

                k1, k2, k3, k4, k5, k6, k7 = st.columns(7)
                k1.metric("Next earnings", ne_str, ne_sub)
                k2.metric("Trailing P/E", _fmt_num(key.get("trailing_pe")))
                k3.metric("Forward P/E", _fmt_num(key.get("forward_pe")))
                k4.metric("PEG", _fmt_num(key.get("peg_ratio")))
                k5.metric("Analyst target",
                          f"{CS}{target:.2f}" if target else "—",
                          f"{upside:+.1f}% upside" if upside is not None else None)
                k6.metric("Recommendation",
                          _rec_label(key.get("recommendation_key"), key.get("recommendation_mean")),
                          help=f"Mean score: {key.get('recommendation_mean'):.2f}" if key.get("recommendation_mean") else None)
                k7.metric("# Analysts",
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
                                    color=["#7c8eff", "#22c55e", "#7c8eff"],
                                    line=dict(color="#0e1117", width=2)),
                        text=[f"Low {CS}{t_low:.2f}", f"Mean {CS}{target:.2f}", f"High {CS}{t_high:.2f}"],
                        textposition=["bottom center", "top center", "bottom center"],
                        textfont=dict(color="#e8edf5"),
                        showlegend=False, hoverinfo="skip",
                    ))
                    fig_t.add_trace(go.Scatter(
                        x=[cur_price], y=[0], mode="markers+text",
                        marker=dict(size=16, color="#f4b942", symbol="diamond",
                                    line=dict(color="#0e1117", width=2)),
                        text=[f"Now {CS}{cur_price:.2f}"], textposition="top center",
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
                        return 1e9, f"{CS}B"
                    if m >= 1e6:
                        return 1e6, f"{CS}M"
                    return 1.0, CS

                ff_col1, ff_col2 = st.columns(2)

                with ff_col1:
                    st.markdown("**Annual revenue & EBITDA (last 5 years)**")
                    if ann_fin.empty or "revenue" not in ann_fin.columns:
                        st.caption("No annual financial data available for this ticker.")
                    else:
                        ann5 = ann_fin.tail(5).copy()
                        all_vals = list(ann5["revenue"].dropna())
                        for col in ("ebitda", "net_income"):
                            if col in ann5.columns:
                                all_vals += list(ann5[col].dropna())
                        scale, unit = _scale_axis(all_vals)
                        years_x = [d.year if hasattr(d, "year") else str(d) for d in ann5.index]
                        fig_a = go.Figure()
                        fig_a.add_trace(go.Bar(
                            name="Revenue", x=years_x,
                            y=(ann5["revenue"] / scale).values,
                            marker_color="#7c8eff",
                            text=[f"{v/scale:.2f}" if pd.notna(v) else "" for v in ann5["revenue"]],
                            textposition="outside",
                        ))
                        if "ebitda" in ann5.columns:
                            fig_a.add_trace(go.Bar(
                                name="EBITDA", x=years_x,
                                y=(ann5["ebitda"] / scale).values,
                                marker_color="#22c55e",
                                text=[f"{v/scale:.2f}" if pd.notna(v) else "" for v in ann5["ebitda"]],
                                textposition="outside",
                            ))
                        if "net_income" in ann5.columns:
                            fig_a.add_trace(go.Bar(
                                name="Net Income", x=years_x,
                                y=(ann5["net_income"] / scale).values,
                                marker_color="#f4b942",
                                text=[f"{v/scale:.2f}" if pd.notna(v) else "" for v in ann5["net_income"]],
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
                        for col in ("ebitda", "net_income"):
                            if col in q5.columns:
                                all_vals += list(q5[col].dropna())
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
                            text=[f"{v/scale:.2f}" if pd.notna(v) else "" for v in q5["revenue"]],
                            textposition="outside",
                        ))
                        if "ebitda" in q5.columns:
                            fig_q.add_trace(go.Bar(
                                name="EBITDA", x=labels,
                                y=(q5["ebitda"] / scale).values,
                                marker_color="#22c55e",
                                text=[f"{v/scale:.2f}" if pd.notna(v) else "" for v in q5["ebitda"]],
                                textposition="outside",
                            ))
                        if "net_income" in q5.columns:
                            fig_q.add_trace(go.Bar(
                                name="Net Income", x=labels,
                                y=(q5["net_income"] / scale).values,
                                marker_color="#f4b942",
                                text=[f"{v/scale:.2f}" if pd.notna(v) else "" for v in q5["net_income"]],
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
                        hovertemplate="%{x|%Y-%m-%d}<br>" + CS + "%{y:.2f}<extra></extra>",
                    ))

                    def marker_size(qty_arr):
                        qmax = float(qty_arr.max()) if len(qty_arr) else 1.0
                        return [10 + 22 * (q / qmax) if qmax > 0 else 12 for q in qty_arr]

                    if not buys.empty:
                        fig.add_trace(go.Scatter(
                            x=buys["trade_date"], y=buys["price"], mode="markers",
                            marker=dict(symbol="triangle-up", color="#22c55e",
                                        size=marker_size(buys["qty"]),
                                        line=dict(color="#0e1117", width=1.5)),
                            name="Buy",
                            text=[f"BUY {q:,.0f} @ {CS}{p:.2f}" for q, p in zip(buys["qty"], buys["price"])],
                            hovertemplate="%{text}<br>%{x|%Y-%m-%d}<extra></extra>",
                        ))
                    if not sells.empty:
                        fig.add_trace(go.Scatter(
                            x=sells["trade_date"], y=sells["price"], mode="markers",
                            marker=dict(symbol="triangle-down", color="#f43f5e",
                                        size=marker_size(sells["qty"]),
                                        line=dict(color="#0e1117", width=1.5)),
                            name="Sell",
                            text=[f"SELL {q:,.0f} @ {CS}{p:.2f}" for q, p in zip(sells["qty"], sells["price"])],
                            hovertemplate="%{text}<br>%{x|%Y-%m-%d}<extra></extra>",
                        ))
                    # Avg cost reference line
                    if cur_qty > 1e-6 and cur_inv > 0:
                        avg = cur_inv / cur_qty
                        fig.add_hline(y=avg, line_dash="dot", line_color="#aaa",
                                      annotation_text=f"Avg cost {CS}{avg:.2f}",
                                      annotation_position="top right")

                    fig.update_layout(
                        height=520, margin=dict(t=20, b=10, l=10, r=10),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        yaxis_title=CS, xaxis=dict(showgrid=False),
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
                            "price": st.column_config.NumberColumn("Price", format=f"{CS}%.4f"),
                            "value": st.column_config.NumberColumn(f"{CS} value", format=f"{CS}%.2f"),
                            "cashflow": st.column_config.NumberColumn("Cashflow", format=f"{CS}%.2f"),
                        },
                    )

# ---------- Allocation ------------------------------------------------------

with tab_alloc:
    if tab_alloc.open:  # lazy: only the selected tab runs
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
                                 color_discrete_sequence=ui.PALETTE)
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
    if tab_risk.open:  # lazy: only the selected tab runs
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
                line=dict(color="#f43f5e", width=1.5),
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
            fig2 = px.histogram(rets, nbins=50, color_discrete_sequence=[ui.ACCENT])
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
    if tab_div.open:  # lazy: only the selected tab runs
        if not pr.HAS_YF:
            st.warning("yfinance required.")
        else:
            st.caption("Dividends paid since first buy (per-share × qty held at ex-date).")
            rows = []
            for _, p in positions.iterrows():
                sym = p["symbol"]
                divs = get_dividends(sym) * _fx(sym)
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
                d1.metric("Total dividends (est.)", f"{CS}{total_div:,.0f}")
                d2.metric("Dividend yield (on MV)", f"{yld:.2f}%")
                d3.metric("Paying positions", f"{div_df['symbol'].nunique()}")

                by_sym = div_df.groupby("symbol")["total"].sum().reset_index().sort_values("total", ascending=False)
                fig = go.Figure(go.Bar(
                    x=by_sym["total"], y=by_sym["symbol"], orientation="h",
                    marker_color="#22c55e",
                    text=[f"{CS}{v:,.0f}" for v in by_sym["total"]], textposition="outside",
                ))
                fig.update_layout(height=max(300, len(by_sym) * 28),
                                  margin=dict(t=10, b=10, l=10, r=60),
                                  paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                  xaxis_title=f"{CS} dividends", yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig, use_container_width=True)

                st.dataframe(
                    div_df, use_container_width=True, hide_index=True,
                    column_config={
                        "ex_date": st.column_config.DateColumn("Ex-Date", format="YYYY-MM-DD"),
                        "per_share": st.column_config.NumberColumn("Per share", format=f"{CS}%.4f"),
                        "qty_held": st.column_config.NumberColumn("Qty (current)", format="%.2f"),
                        "total": st.column_config.NumberColumn(f"Estimated {CS}", format=f"{CS}%.2f"),
                    },
                    height=400,
                )

# ---------- Weekly trade log ------------------------------------------------

with tab_weekly:
    if tab_weekly.open:  # lazy: only the selected tab runs
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
                    "deployed": st.column_config.NumberColumn(f"{CS} Deployed", format=f"{CS}%.0f"),
                    "returned": st.column_config.NumberColumn(f"{CS} Returned", format=f"{CS}%.0f"),
                    "net_cash": st.column_config.NumberColumn("Net cash in", format=f"{CS}%.0f"),
                    "outcome": st.column_config.NumberColumn("Outcome since trade", format=f"{CS}%.0f"),
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
                net_str = f"deployed {CS}{net:,.0f}" if net >= 0 else f"returned {CS}{-net:,.0f}"
                outcome = float(group["outcome_$"].dropna().sum())
                outcome_arrow = "↑" if outcome >= 0 else "↓"
                header = (f"Week of {wstart.date()} → {wend.date()}  ·  "
                          f"{n} trade{'s' if n != 1 else ''}  ·  {net_str}  ·  "
                          f"outcome since: {outcome_arrow} {CS}{outcome:,.0f}")

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
                        "outcome_$": f"Outcome {CS}", "worked_out": "Worked",
                        "days_since": "Days held",
                    })
                    st.dataframe(
                        show, use_container_width=True, hide_index=True,
                        column_config={
                            "Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                            "Qty": st.column_config.NumberColumn(format="%.2f"),
                            "Trade Price": st.column_config.NumberColumn(format=f"{CS}%.4f"),
                            "Current": st.column_config.NumberColumn(format=f"{CS}%.4f"),
                            "% Move": st.column_config.NumberColumn(format="%.2f%%"),
                            f"Outcome {CS}": st.column_config.NumberColumn(format=f"{CS}%.0f"),
                            "Days held": st.column_config.NumberColumn(format="%d d"),
                        },
                    )

# ---------- Lots ------------------------------------------------------------

with tab_lots:
    if tab_lots.open:  # lazy: only the selected tab runs
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
                "price": st.column_config.NumberColumn("Price", format=f"{CS}%.4f"),
                "cashflow": st.column_config.NumberColumn("Cashflow", format=f"{CS}%.2f"),
            },
            height=600,
        )
