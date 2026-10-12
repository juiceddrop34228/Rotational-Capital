# Rotational Capital

A sector rotation scanner that ranks market sectors by leadership, emerging momentum, fading strength, and lagging weakness using free, keyless data from TradingView.

## Run it

Download the ZIP, extract it, then:

- **Windows:** double-click **`RUN.bat`**
- **Mac/Linux:** run **`./RUN.sh`** in a terminal

The first run sets up a Python environment and installs dependencies (1–3 minutes). When it's ready, open **http://localhost:8420** in your browser.

## Repository layout

| Path | What's inside |
| --- | --- |
| `RUN.bat` / `RUN.sh` | One-click launchers — start here |
| `theme-dashboard/` | The app itself (backend, frontend, launchers, tests, full docs) |
| `screenshots/` | Screenshots of the dashboard |
| `samples/` | Saved TradingView pages and data snapshots used by the offline tests |

Full documentation (features, data sources, charts, workflow) is in [`theme-dashboard/README.md`](theme-dashboard/README.md).
