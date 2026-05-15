# JBD Portfolio Monitor

Streamlit dashboard for tracking a personal stock portfolio exported from Yahoo Finance.
Live prices via `yfinance`; TWR / XIRR / simple-return analytics; allocation breakdowns;
per-holding charts with buy/sell markers; daily, weekly, and dividend logs.

## Run locally

```bash
cd portfolio-monitor
pip install -r requirements.txt
streamlit run app.py
```

Opens at <http://localhost:8501>. Default sample CSV is at `data/portfolio.csv` — upload your own from the sidebar.

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
   Streamlit Cloud containers are ephemeral — file uploads don't persist between sessions. To make uploads from any device update the deployed app for everyone:
   - Create a GitHub Personal Access Token at <https://github.com/settings/tokens> with the `repo` scope.
   - In your Streamlit Cloud app: ⋯ → **Settings → Secrets**. Paste:
     ```toml
     github_token  = "ghp_xxxxxxxxxxxx"
     github_repo   = "your-username/jbd-portfolio-monitor"
     github_path   = "data/portfolio.csv"
     github_branch = "main"
     ```
   - Reload. After any upload a **💾 Save this CSV to GitHub** button appears in the sidebar — clicking it commits the file. Next time any device opens the app, the new CSV is the default.

## Updating the CSV

- **PC**: replace `data/portfolio.csv` and `git push` — Streamlit Cloud auto-redeploys.
- **PC or iPhone (browser)**: open the app → sidebar uploader → **💾 Save this CSV to GitHub**.

## Architecture

- `app.py` — Streamlit UI, all tabs.
- `portfolio.py` — CSV parsing (with column-name fallbacks), FIFO lot accounting, position aggregation, XIRR.
- `metrics.py` — TWR curve, drawdown, volatility, Sharpe, daily returns.
- `prices.py` — yfinance adapter: live quotes, history, metadata, dividends.
- `data/portfolio.csv` — current Yahoo Finance transactions export.

## Notes

- Foreign tickers (`.MI`, `.SG`, etc.) keep their native currency; FX conversion is not applied.
- yfinance metadata is cached 24 h. **🔄 Refresh prices** in the sidebar clears the cache.
- Bond ISINs (e.g. `DE000A0SMU87.SG`) fall back to the snapshot price from the CSV when yfinance has nothing.
