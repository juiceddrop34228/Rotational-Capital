# Sector Rotation Scanner

A dark-themed, full-fledged sector rotation analysis dashboard for swing traders. It ranks sectors by leadership, emerging momentum, fading strength, and lagging weakness using live market data from free sources.

## CCI-based sector ranking, one strategy engine

The app runs a single strategy engine — **Qullamaggie** — inside one shell; the **Markets layer is universal**. The **sector score is completely CCI-based**:

```
Final Score = 50% Performance + 50% CCI
```

- **Performance (50%)**: 15% 1-week + 50% 1-month + 35% 3-month performance, min-max **normalized to 0–100** across sectors before combining.
- **CCI (50%)**: the CCI(34) rating of the sector's proxy ETF (`SECTOR_ETF_MAP`, e.g. Energy Minerals → XLE), mapped to 0–100 (Bearish 0 / Neutral 50 / Bullish-Caution 75 / Bullish 100); sectors without an ETF CCI fall back to the market-wide CCI factor.

Stock ranking is unchanged: the shared composite factor framework (RS, momentum, proximity to highs, volume, trend alignment, breakout proximity) with **CCI as a compulsory input** (10% weight) in the stock composite (`STRATEGY_DEFS` / `score_and_rank` in `backend/engine.py`).

## ETF Hub: multi-factor leadership & opportunity ranking

The **ETFs** page ranks the ETF universe (~80 tickers across Broad / Sector / Thematic / Industry / Commodity-Macro) with a **percentile-based multi-factor model** (`backend/etf_scoring.py`) instead of raw returns. Every factor is scored 0–100 relative to the other ETFs currently scanned, so the same return means different things in different market environments; raw performance values are always shown alongside.

- **Leadership score** = 35% relative strength vs SPY (3M/6M RS + RS-ratio slope) + 15% momentum (1W/1M + acceleration) + 20% trend quality (price vs SMA10/20/50/200, MA slopes and alignment) + 10% volume confirmation (relative volume, 20d-vs-60d volume trend, up/down-day volume) + 20% consistency (% positive days/weeks, realized volatility, max drawdown).
- **Opportunity score** = leadership adjusted by an **extension penalty** (distance above the 10/20/50-day averages) plus bonuses for constructive pullbacks and early breakouts — strength without confusing it with a good entry. Leveraged/inverse ETFs are hard-capped and carry a risk warning; bond/international ETFs get relaxed volatility treatment.
- **Rotation score** highlights ETFs whose recent momentum is improving fastest vs their own longer trend; **Risk score** flags weakening momentum, poor trend, large drawdowns, and excessive volatility.
- Each ETF gets a **state** — Leading, Emerging, Fading, Recovering, Extended, Neutral, or Lagging — and a rank on all four boards (Leadership / Opportunity / Rotation / Risk), switchable above the master table.
- Clicking an ETF opens a **Score Breakdown** panel (`GET /api/etf-hub/{ticker}/breakdown`) showing every factor's score, weight, percentile, raw inputs, and a plain-language explanation of why it ranked where it did.
- If daily price history is unavailable, the hub falls back to the legacy performance+CCI score and hides the new columns.

## Charts

The **Charts** page (sidebar) → **Momentum** tab shows the selected sector name with its **proxy ETF chart** underneath (Energy Minerals → XLE) — every chart carries the **5 / 10 / 20 / 50 / 200 EMA** studies plus a numeric EMA readout strip below. In **Sector detail → Constituents**, turning the **Charts** toggle on renders **three charts per row** (timeframe set configurable) with the 5-EMA readout below each row. Chart layout is customizable (charts per row, size, timeframe set, EMA readout) and persists in the browser.

## Data sources (free, no API key required)

The app pulls entirely from **TradingView** (free, keyless):

- **TradingView scanner API** — stock-level data: prices, performance, moving averages, 52w high/low, volume, sector/industry classification, ATR/volatility, analyst ratings.
- **TradingView market pages** (scraped verbatim from the website) — sector and industry performance: the [US sector page](https://www.tradingview.com/markets/stocks-usa/sectorandindustry-sector/) and each sector's industries page, so the dashboard's sector/industry numbers match the website exactly. The website publishes only the daily change; longer sector horizons (1W/1M/3M/6M) come from an unfiltered cap-weighted scanner scan.
- **Yahoo Finance** via `yfinance` — daily OHLC history for the SPY/QQQ/DJI/IWM CCI(34) oscillator panel only.

There is nowhere in the app to enter an API key, and none is required.

## Quick start

From the repo root, just double-click **`RUN.bat`** (Windows) or run **`./RUN.sh`** (Mac/Linux) — it launches everything below automatically.

To run manually instead:

**Mac/Linux**
```bash
cd theme-dashboard
chmod +x run.sh
./run.sh
```

**Windows**
```bash
cd theme-dashboard
run.bat
```

Then open **http://localhost:8420** in your browser. First run installs Python dependencies (`fastapi`, `uvicorn`, `yfinance`, etc.) which may take 1–3 minutes.

## What's included

- **Backend** (`backend/main.py`, `backend/engine.py`, `backend/live_data.py`): FastAPI app, SQLite storage, and the analytics engine.
- **Frontend** (`frontend/index.html`): Single-file React app with a dark UI, collapsible sidebar, dashboard, and sector drill-downs.
- **20 sectors**: TradingView's own sector classification (the same sectors shown on TradingView's US sector page), each with its industries from that page.
- **Universal filters** applied everywhere (from the TradingView scanner): market cap ≥ **$500M**, average 30-day volume > **1M shares**, price ≥ **$3**, and **ADR ≥ 2%**.
- **Rotation states**: Leader, Emerging, Fading, Lagging, and Neutral.
- **Trend model**: sector trend is judged by **10 EMA vs 20 EMA alignment** (uptrend when 10 > 20); the **overall trend** is price vs **50 EMA**. The market regime uses only the **CCI(34) oscillator** (HLC3 source, with a 13-period EMA of CCI as the blue signal line, computed on closed daily bars and rounded to the closest 10) on the major indices (SPY / QQQ / DJI / IWM): either line below 0 → Bearish; both above 100 → Bullish (Bullish ⚠ / Caution when the yellow line is above the blue line); otherwise Neutral. The four index ratings are averaged into the combined **Market (CCI)** rating (Bullish / Mixed / Bearish) and the 0–100 risk gauge.
- **Dashboard**: benchmark summary (SPY) with returns, a Market Environment strip (leaders vs laggards, average breadth/volume, per-index CCI ratings, a CCI-based combined market rating with a zone gauge and risk-on/off verdict), summary cards (Best Overall / Offensive / Defensive / Fastest Improving / Weakest), a Strongest Sector banner driven by a composite leadership score (score, RS, breadth, multi-timeframe performance, new highs, EMA alignment, extension penalty), Today's Movers grid, Rotation Quadrant, Score Ladder, and the sortable Sector Performance table.
- **All Sectors page**: sector command center — Leadership-vs-Extension scatter, 5-day score-delta bars, one-click filters (Leaders / Improving / Offensive / Defensive / Extended / Weak), and a rich sortable table (performance, breadth, RS, % from 52w high, EMA alignment, RS/score/rank deltas, style, trading tags).
- **Rotation page**: leadership workspace — Stalk Now / Improving Fastest / Weakening strips, rotation map, score ladder, RS-trend vs score-delta quadrant, and a sortable leadership table with MA alignment, deltas, and actionable tags (Tight near highs, Early leader, Improving, Extended, Weakening, Defensive strength, Avoid).
- **Momentum page**: timeframe momentum strips (1D/1W/1M/3M heatmap), RS vs SPY scatter (+ volume-bubble variant), 1W-vs-1M dumbbell chart, 10-day score slope chart, and Top-3 ranking tables (1M, 3M, blended 1M+3M).
- **Breadth & Risk page**: breadth distribution histogram with median marker, state-distribution donut, new-highs vs breadth quadrant scatter, volume-pressure bars, vs-SPY diverging bars, score-anatomy waterfall, and a sector treemap.
- **Playbook page**: Q-style hunting scores with badges (Prime breakout territory / Early expansion / Late trend / Avoid), holding-capacity meters, strategy filters (Breakout / Pullback), per-sector price-vs-20MA mini charts, a 10-snapshot rotation timeline, a top-sector watchlist exporter (copy/download), and a trade log with sector exposure tracking (warns when >50% of risk sits in fading/lagging sectors).
- **EPs page**: a fully independent Episodic Pivot workspace (own `/api/ep-dashboard` feed, own localStorage-persisted settings, filters, watchlist and alerts — nothing shared with the rest of the app). Six tabs: **Scanner** (EP candidate cards with gap / from-open / pre-market / relative volume / dollar volume / ADR / RS / EP score, sector leaders, rich filters), **Rankings** (15 sortable boards: biggest %/$ gain, gain from open, pre-market gain, gap-up, relative/total/pre-market/dollar volume, relative strength, intraday momentum, opening-range breakout, pre-market breakout, strongest sector, strongest industry group), **Charts** (per-stock TradingView charts with timeframe presets plus analytics: move/gap/relative-volume histograms, gap-vs-relative-volume scatter, sector & industry strength bars, candidates-by-sector donut), **Watchlist** (EP-only, local), **Alerts** (metric/threshold rules evaluated against the latest scan, triggered badges), and **Settings** (persisted thresholds, reset).
- **Sector detail**: 4 sections — Overview, Constituents, Industries, and Rotation — with line charts, radar fingerprint, contribution bars, volume expansion, RRG, and new-highs bars. The Constituents table lists **every stock in the sector passing the universal filters** (not just the top 10), ranked by score (stable 1..N), with 1D/1W/1M/3M/6M performance, click-to-sort headers, an optional **per-row charts mode** (three TradingView charts under each row with the 5/10/20/50/200 EMA readout below), and Google-style pagination — the same applies to industry drill-downs.
- **Industry benchmarks**: every industry charts a **dedicated industry ETF** when one closely represents it (`INDUSTRY_ETF_MAP` in `backend/engine.py` — SMH for Semiconductors, XBI for Biotechnology, KRE for Regional Banks, ...), otherwise an **equal-weight TradingView custom index** of its top-5 members by market cap (e.g. `SN/4+IMAX/4+WHR/4+SONO/4`). Broad sector ETFs (XLY, XLK, ...) are never used as industry benchmarks. The 5/10/20/50/200 EMA readout works for both: scanner values for ETFs, the equal-weight average of member EMAs for custom indices.
- **Screener page**: every stock passing the universal filters with 3M and 6M cross-market rankings, fully sortable columns, and Google-style pagination.
- **Live sync**: click **Sync Live Data** in the top bar to pull real Yahoo Finance prices and ETF holdings.

## Working with the source

The JSX source is in `frontend/src/app.jsx`. The compiled JavaScript is pre-embedded in `frontend/index.html` so no build step is required to run the app.

If you edit `app.jsx`, rebuild `index.html` with:

```bash
cd frontend/src
node build.js
```

This requires `@babel/core` and `@babel/preset-react`, installed by `npm install` in `frontend/src`.

## Daily workflow

1. Open the dashboard and check **Today's Movers** for leaders, emerging, fading, and lagging sectors.
2. Click a sector to drill into its Overview, Constituents, and Rotation tabs.
3. Use the **Sync Live Data** button before the trading day to refresh prices and holdings.
4. Focus swing setups on sectors with high scores, healthy breadth, and rising relative strength.

## Connectivity check

Before your first live sync, run:

```bash
cd backend
python ../test_connectivity.py
```

This confirms your network can reach Yahoo Finance and issuer file hosts.

## Tests

Offline logic tests for the data layer:

```bash
python test_live_data_logic.py
```

## Extending sectors

Edit `SECTOR_DEFS` at the top of `backend/engine.py` to add, remove, or change sector ETFs. Delete `backend/themes.db` and restart to regenerate data.
