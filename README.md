# JBD Portfolio Monitor

Streamlit dashboard for tracking a personal stock portfolio exported from Yahoo Finance.
Live prices via `yfinance`; TWR / XIRR / simple-return analytics; allocation breakdowns;
per-holding charts with buy/sell markers; daily, weekly, and dividend logs.

## Features

- **TROIC (Total Return on Invested Capital)** — aggregate card in the Recap tab plus per-symbol `Total Cost`, `Total Value`, and `TROIC %` columns in Positions. Measures the multiplier on *all* capital ever deployed (including closed positions), not just net cash currently at risk.
- **Lifetime cost/value tracking** per symbol — a single source of truth shared by the Positions and Holdings tabs.
- **Post-tax simulator (Italian regime)** — 26% capital-gain rate on realized P&L with unlimited-life loss carryforward, a year-by-year table, and a dual pre-tax vs post-tax equity curve (tax applied as a step at each 31 Dec).
- Plus the existing TWR / XIRR / simple-return analytics, allocation breakdowns, per-holding charts with buy/sell markers, and daily/weekly/dividend logs.

## Run locally

```bash
cd portfolio-monitor
pip install -r requirements.txt
streamlit run app.py
```

Opens at <http://localhost:8501>. Default sample CSV is at `data/portfolio.csv` — upload your own from the sidebar.

### Development

```bash
pip install -r requirements-dev.txt   # runtime deps + pytest
python -m pytest                       # 19 tests
```

The suite (`test_portfolio.py`, `test_tax.py`) covers lifetime stats, FIFO realized events, and the post-tax computations.

## Deploy to Streamlit Community Cloud (free, works on iPhone)

1. **Push to GitHub**
   ```bash
   cd portfolio-monitor
   git init -b main
   git add .
   git commit -m "Initial commit"
   gh repo create jbd-portfolio-monitor --private --source=. --remote=origin --push
   ```
   Or create the repo on github.com and `git remote add origin … && git push -u origin main`.

2. **Deploy**
   - Go to <https://share.streamlit.io>, sign in with GitHub.
   - **New app** → pick your repo / `main` / `app.py` → **Deploy**.
   - After ~1 min you get a URL like `https://<your-app>.streamlit.app`. Open on iPhone Safari → Share → **Add to Home Screen** for an app-like icon.

3. **Cross-device CSV persistence (optional but recommended)**
   Streamlit Cloud containers are ephemeral, so without this the saved holdings are lost on restart.
   - Create a **private** GitHub repo for the data (the app repo is public — don't store holdings there).
   - Create a fine-grained Personal Access Token at <https://github.com/settings/tokens> with *Contents: read & write* on that repo.
   - In your Streamlit Cloud app: ⋯ → **Settings → Secrets**. Paste:
     ```toml
     github_token    = "github_pat_xxxxxxxxxxxx"
     github_repo     = "your-username/jbd-portfolio-data"   # private
     github_branch   = "main"
     github_data_dir = "data"   # files land at data/stocks.csv, data/etf.csv, data/crypto.csv
     ```

## Updating the holdings

The sidebar shows one saved file per class (Stocks / ETF / Crypto), loaded automatically on open.
To update one: press **✖** next to it, upload the new Yahoo export, done — it replaces the saved
file (in the data repo when configured, otherwise `data/<class>.csv`). **Annulla** keeps the old one.

The BTP is not loaded by default: press **🏛️ Carica BTP** in the sidebar to add it.

## Architecture

- `app.py` — Streamlit UI, all tabs.
- `portfolio.py` — CSV parsing (with column-name fallbacks), FIFO lot accounting, position aggregation, XIRR, `build_lifetime_stats`, and `realized_events` (FIFO realized P&L with sell dates).
- `metrics.py` — TWR curve, drawdown, volatility, Sharpe, daily returns.
- `tax.py` — Italian capital-gain tax simulator (26% rate, loss carryforward).
- `prices.py` — yfinance adapter: live quotes, history, metadata, dividends.
- `storage.py` — load/save of the per-class holdings CSVs (GitHub contents API or local `data/`).
- `bonds.py` — BTP valuation and JSON persistence.
- `test_*.py` — pytest suite.
- `data/<class>.csv` — saved Yahoo Finance exports (gitignored).

## Notes

- Foreign tickers (`.MI`, `.SG`, etc.) keep their native currency; FX conversion is not applied.
- yfinance metadata is cached 24 h. **🔄 Refresh prices** in the sidebar clears the cache.
- Bond ISINs (e.g. `DE000A0SMU87.SG`) fall back to the snapshot price from the CSV when yfinance has nothing.
- The **Post-tax** tab is a personal-use approximation, not a substitute for the *Quadro RT* tax declaration. Italy's 4-year loss-carryforward limit is intentionally ignored (losses carry forward indefinitely here).
