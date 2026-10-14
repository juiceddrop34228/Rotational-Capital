"""
live_data.py
Live market data layer for the sector rotation scanner.

Single data source: the TradingView scanner API (free, no API key).
A whole-US-market scan (market cap >= $600M, avg 30d volume >= 1M,
price >= $3, ADR >= 3%) provides every metric used by the app:
prices, performance, moving averages, 52w high/low, volume, sector/industry
classification, ATR and volatility.

Sectors are TradingView's own "sector" classification; each sector's
displayed holdings are its top-10 3-month performers, while sector
scores/snapshots aggregate every filtered stock in the sector.

The displayed sector and industry performance is copied verbatim from
TradingView's own sector/industry symbols (SECTOR_US:* / INDUSTRY_US:* on
the scanner API) — the exact numbers shown on the website for every horizon
(1D / 1W / 1M / 3M / 6M). Breadth, scores and other derived metrics are
computed from the filtered stock universe in each sector/industry.
"""

import time
from datetime import datetime, date, timezone

import requests

from engine import (
    _mk_conn, init_db, SECTOR_DEFS, SECTOR_COLORS, BENCHMARK_TICKER, MIN_MARKET_CAP_MUSD,
    MIN_AVG_VOLUME, MIN_ADR_PCT, MIN_PRICE, classify_sector_state,
    concentration_index, INDEX_DEFS, CCI_LENGTH, CCI_EMA_LENGTH, cci_rating,
    qullamaggie_scan_scores, sector_performance_scores, cci_sector_scores,
    sector_cci_factors, SECTOR_ETF_MAP, INDUSTRY_ETF_MAP, compute_industry_snapshots,
    detect_ma_pullback_signal, PATTERN_BONUS,
)

REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SectorScanner/1.0)"}
REQUEST_TIMEOUT = 30


# ---------------------------------------------------------------------------
# TradingView scanner API (sole data source; keyless)
# ---------------------------------------------------------------------------

TV_SCAN_URL = "https://scanner.tradingview.com/america/scan"
TV_COLUMNS = [
    "close", "change", "Perf.W", "Perf.1M", "Perf.3M", "Perf.6M",
    "SMA20", "SMA50", "SMA200", "EMA5", "EMA10", "EMA20", "EMA50", "EMA100", "EMA200",
    "price_52_week_high", "price_52_week_low",
    "volume", "average_volume_10d_calc", "average_volume_30d_calc", "average_volume_60d_calc",
    "sector", "industry", "market_cap_basic",
    "relative_volume_10d_calc",
    "High.1M", "High.3M", "High.6M", "Low.1M",
    "Volatility.D", "ATR", "ADR", "Recommend.All",
    "Perf.YTD", "Perf.Y",
    "Recommend.MA", "Recommend.Other",
    "Recommend.All|1W", "Recommend.MA|1W", "Recommend.Other|1W",
    "Volatility.W", "Volatility.M",
    # EP extras: intraday range, gap, pre-market
    "open", "high", "low", "change_from_open", "gap",
    "premarket_change", "premarket_volume",
]

TOP_N_PER_SECTOR = 10

# Exact TradingView sector/industry performance. TradingView publishes its
# sector and industry aggregates as scannable symbols (SECTOR_US:* /
# INDUSTRY_US:*) on the same scanner endpoint — these are the exact numbers
# shown on the website's sector/industry pages and screener, so the dashboard
# copies them verbatim instead of recomputing them.
TV_GROUP_COLUMNS = ["description", "change", "Perf.W", "Perf.1M", "Perf.3M", "Perf.6M", "sector"]


def _tv_post(body, url=TV_SCAN_URL):
    resp = requests.post(url, json=body, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _tv_scan_chunk(symbols):
    """One POST to the TradingView scanner for explicit symbols."""
    body = {"symbols": {"tickers": symbols, "query": {"types": []}}, "columns": TV_COLUMNS}
    out = {}
    for row in (_tv_post(body).get("data") or []):
        vals = row.get("d") or []
        if len(vals) == len(TV_COLUMNS):
            out[row["s"]] = vals
    return out


def _tv_row_to_metrics(vals):
    """Map a TradingView column row to the metric dict shape used everywhere.
    Returns None when the row has no usable price."""
    d = dict(zip(TV_COLUMNS, vals))
    close = d.get("close")
    if close is None or close <= 0:
        return None

    hi_52w = d.get("price_52_week_high")
    lo_52w = d.get("price_52_week_low")
    sma20, sma50 = d.get("SMA20"), d.get("SMA50")
    ema10 = d.get("EMA10")
    ema100 = d.get("EMA100")
    ema200 = d.get("EMA200")
    avg_vol30 = d.get("average_volume_30d_calc")
    avg_vol10 = d.get("average_volume_10d_calc")
    avg_vol60 = d.get("average_volume_60d_calc") or avg_vol30 or avg_vol10
    rel_vol = d.get("relative_volume_10d_calc")
    vol = d.get("volume")
    adr = d.get("ADR")

    def dist_to(level):
        return round(float((close / level - 1) * 100), 1) if level else None

    is_new_high_today = bool(hi_52w and close >= hi_52w * 0.999)

    return {
        "price": round(float(close), 2),
        "chg_1d": round(float(d.get("change") or 0.0), 2),
        "chg_1w": round(float(d.get("Perf.W") or 0.0), 2),
        "chg_1m": round(float(d.get("Perf.1M") or 0.0), 2),
        "chg_3m": round(float(d.get("Perf.3M") or 0.0), 2),
        "chg_6m": round(float(d.get("Perf.6M") or 0.0), 2),
        "avg_volume": round(float(avg_vol30 or avg_vol60), 0) if (avg_vol30 or avg_vol60) else 0,
        "pct_from_52w_high": dist_to(hi_52w),
        "pct_from_52w_low": dist_to(lo_52w),
        "volume_ratio": round(float(rel_vol), 2) if rel_vol else (
            round(float(vol / avg_vol30), 2) if vol and avg_vol30 else 1.0),
        "above_20d": bool(close > sma20) if sma20 else False,
        "above_50d": bool(close > sma50) if sma50 else False,
        "above_200d": bool(close > ema200) if ema200 else False,
        "above_100ema": bool(close > ema100) if ema100 else None,
        "adr_pct": round(float(adr / close * 100), 2) if adr else None,
        "momentum_20d": round(float(d.get("Perf.1M") or 0.0), 2),
        "ema10": round(float(ema10), 2) if ema10 else None,
        "ema20": round(float(d["EMA20"]), 2) if d.get("EMA20") else None,
        "ema50": round(float(d["EMA50"]), 2) if d.get("EMA50") else None,
        "ema100": round(float(d["EMA100"]), 2) if d.get("EMA100") else None,
        "ema5": round(float(d["EMA5"]), 2) if d.get("EMA5") else None,
        "ema200": round(float(ema200), 2) if ema200 else None,
        "days_since_new_high": 0 if is_new_high_today else 90,
        "is_new_high_today": is_new_high_today,
        # Swing-trading extras
        "sector": d.get("sector"),
        "industry": d.get("industry"),
        "market_cap_musd": round(float(d["market_cap_basic"]) / 1_000_000, 1) if d.get("market_cap_basic") else None,
        "dist_high_1m": dist_to(d.get("High.1M")),
        "dist_high_3m": dist_to(d.get("High.3M")),
        "dist_high_6m": dist_to(d.get("High.6M")),
        "ext_ema10": round(float((close / ema10 - 1) * 100), 1) if ema10 else None,
        "volatility_d": round(float(d["Volatility.D"]), 2) if d.get("Volatility.D") is not None else None,
        "atr": round(float(d["ATR"]), 3) if d.get("ATR") is not None else None,
        "recommend_all": round(float(d["Recommend.All"]), 3) if d.get("Recommend.All") is not None else None,
        "chg_ytd": round(float(d["Perf.YTD"]), 2) if d.get("Perf.YTD") is not None else None,
        "chg_1y": round(float(d["Perf.Y"]), 2) if d.get("Perf.Y") is not None else None,
        "recommend_ma": round(float(d["Recommend.MA"]), 3) if d.get("Recommend.MA") is not None else None,
        "recommend_other": round(float(d["Recommend.Other"]), 3) if d.get("Recommend.Other") is not None else None,
        "recommend_all_1w": round(float(d["Recommend.All|1W"]), 3) if d.get("Recommend.All|1W") is not None else None,
        "recommend_ma_1w": round(float(d["Recommend.MA|1W"]), 3) if d.get("Recommend.MA|1W") is not None else None,
        "recommend_other_1w": round(float(d["Recommend.Other|1W"]), 3) if d.get("Recommend.Other|1W") is not None else None,
        "volatility_w": round(float(d["Volatility.W"]), 2) if d.get("Volatility.W") is not None else None,
        "volatility_m": round(float(d["Volatility.M"]), 2) if d.get("Volatility.M") is not None else None,
        # EP extras
        "open_price": round(float(d["open"]), 2) if d.get("open") else None,
        "day_high": round(float(d["high"]), 2) if d.get("high") else None,
        "day_low": round(float(d["low"]), 2) if d.get("low") else None,
        "chg_from_open": round(float(d["change_from_open"]), 2) if d.get("change_from_open") is not None else None,
        "gap_pct": round(float(d["gap"]), 2) if d.get("gap") is not None else _gap_fallback(close, d),
        "pm_chg": round(float(d["premarket_change"]), 2) if d.get("premarket_change") is not None else None,
        "pm_vol": round(float(d["premarket_volume"]), 0) if d.get("premarket_volume") is not None else None,
        "volume_today": round(float(vol), 0) if vol else None,
    }


def _gap_fallback(close, d):
    """Gap % from open vs previous close (derived from change) when the
    scanner's own gap column is unavailable."""
    o, chg = d.get("open"), d.get("change")
    if not o or chg is None:
        return None
    prev_close = close / (1 + chg / 100.0) if (1 + chg / 100.0) else None
    if not prev_close:
        return None
    return round(float((o / prev_close - 1) * 100), 2)


def fetch_tv_market_scan(progress_cb=None, stats_out=None):
    """Whole-US-market scan: every stock passing the universal filters
    (market cap >= $600M, avg 30d volume >= 1M, price >= $3, ADR >= 3%),
    sorted by ticker name ascending (a stable key — unlike market cap or
    performance, it does not move between page requests during live trading,
    so no stock can silently fall through a page boundary). The ADR filter
    cannot be expressed server-side (it compares two columns), so it is
    applied in Python below. Each page is retried on failure/empty responses
    so a single flaky request can no longer silently truncate the universe.

    Returns a list of metric dicts (with ticker). When `stats_out` (a dict)
    is given, it is filled with per-stage drop accounting:
    server_total (rows TradingView says match the server-side filters),
    downloaded, and how many rows were dropped at each client-side stage."""
    filters = [
        {"left": "market_cap_basic", "operation": "egreater", "right": MIN_MARKET_CAP_MUSD * 1_000_000},
        {"left": "average_volume_30d_calc", "operation": "egreater", "right": MIN_AVG_VOLUME},
        {"left": "close", "operation": "egreater", "right": MIN_PRICE},
        # US primary listings only — the america scanner also returns OTC
        # symbols (e.g. foreign ADRs like OTC:SFTBY), which we exclude.
        {"left": "exchange", "operation": "in_range", "right": ["NYSE", "NASDAQ", "AMEX"]},
    ]
    page = 1000
    out = []
    seen = set()
    offset = 0
    total = None
    stats = {"bad_rows": 0, "wrong_exchange": 0, "duplicates": 0,
             "no_price": 0, "adr_missing": 0, "adr_below_min": 0}

    def fetch_page(off, attempts=4):
        for attempt in range(attempts):
            try:
                body = {
                    "columns": TV_COLUMNS,
                    "filter": filters,
                    "range": [off, off + page],
                    "sort": {"sortBy": "name", "sortOrder": "asc"},
                }
                data = _tv_post(body)
                rows = data.get("data") or []
                if rows or (data.get("totalCount") or 0) <= off:
                    return data, rows
            except Exception:
                pass
            time.sleep(1.0 + attempt)
        return None, []

    while True:
        data, rows = fetch_page(offset)
        if total is None and data is not None:
            total = data.get("totalCount") or 0
            if progress_cb:
                progress_cb(f"TradingView market scan: {total} stocks pass the server-side filters "
                            f"(market cap / volume / price), downloading...")
        if not rows:
            if data is None and progress_cb:
                progress_cb(f"TradingView market scan: page at offset {offset} failed after retries — stopping with {len(out)} stocks.")
            break
        for row in rows:
            vals = row.get("d") or []
            if len(vals) != len(TV_COLUMNS):
                stats["bad_rows"] += 1
                continue
            if row["s"].split(":", 1)[0] not in ("NYSE", "NASDAQ", "AMEX"):
                stats["wrong_exchange"] += 1
                continue
            if row["s"] in seen:
                stats["duplicates"] += 1
                continue
            seen.add(row["s"])
            m = _tv_row_to_metrics(vals)
            if not m:
                stats["no_price"] += 1
                continue
            if m.get("adr_pct") is None:
                stats["adr_missing"] += 1
                continue
            if m["adr_pct"] < MIN_ADR_PCT:
                stats["adr_below_min"] += 1
                continue
            # "NASDAQ:AAPL" -> "AAPL"; TradingView uses BRK.B style dots
            m["ticker"] = row["s"].split(":", 1)[-1].replace(".", "-")
            out.append(m)
        offset += len(rows)
        if progress_cb:
            progress_cb(f"TradingView market scan: {offset}/{total} stocks downloaded...")
        if total is not None and offset >= total:
            break
        time.sleep(0.3)

    stats["server_total"] = total
    stats["downloaded"] = offset
    stats["kept"] = len(out)
    if stats_out is not None:
        stats_out.update(stats)
    if progress_cb:
        progress_cb(
            f"TradingView market scan complete: {len(out)} stocks pass ALL filters. "
            f"Excluded: {stats['adr_below_min']} below the ADR >= {MIN_ADR_PCT}% minimum, "
            f"{stats['adr_missing']} with no ADR data, {stats['no_price']} with no usable price, "
            f"{stats['wrong_exchange']} non-NYSE/NASDAQ/AMEX, {stats['duplicates']} duplicates, "
            f"{stats['bad_rows']} malformed rows."
        )
    if total and offset < total and progress_cb:
        progress_cb(f"WARNING: TradingView market scan incomplete — {offset}/{total} rows downloaded.")
    return out


def cap_weighted_average(rows, value_idx, weight_idx):
    """Market-cap weighted average of one column over scanner rows.

    rows: list of scanner value lists. Rows missing the value or the weight
    are skipped. Returns None when nothing is usable."""
    num = den = 0.0
    for vals in rows:
        v, w = vals[value_idx], vals[weight_idx]
        if isinstance(v, (int, float)) and isinstance(w, (int, float)) and w > 0:
            num += w * v
            den += w
    return num / den if den else None


def _tv_group_scan(group_type, progress_cb=None):
    """Scan TradingView's own sector or industry symbols (exact website values).

    group_type: "sector" or "industry". Returns a list of dicts:
    {symbol, name, chg_1d, chg_1w, chg_1m, chg_3m, chg_6m, sector}."""
    body = {
        "columns": TV_GROUP_COLUMNS,
        "range": [0, 1000],
        "symbols": {"query": {"types": [group_type]}},
        "sort": {"sortBy": "change", "sortOrder": "desc"},
    }
    data = _tv_post(body)
    out = []
    for row in data.get("data") or []:
        vals = row.get("d") or []
        if len(vals) != len(TV_GROUP_COLUMNS):
            continue
        d = dict(zip(TV_GROUP_COLUMNS, vals))

        def pct(key):
            v = d.get(key)
            return round(float(v), 2) if isinstance(v, (int, float)) else None

        out.append({
            "symbol": row["s"],
            "name": d.get("description") or d.get("name") or row["s"],
            "chg_1d": pct("change"),
            "chg_1w": pct("Perf.W"),
            "chg_1m": pct("Perf.1M"),
            "chg_3m": pct("Perf.3M"),
            "chg_6m": pct("Perf.6M"),
            "sector": d.get("sector"),  # parent sector name (industries only)
        })
    if progress_cb:
        progress_cb(f"TradingView {group_type} scan: {len(out)} {group_type}s with exact website performance.")
    return out


def fetch_tv_sector_performance(progress_cb=None):
    """Exact TradingView sector performance, keyed by sector name:
    {sector_name: {"chg_1d", "chg_1w", "chg_1m", "chg_3m", "chg_6m"}}.
    These are TradingView's own published sector aggregates (SECTOR_US:*
    symbols) — the same numbers shown on the website."""
    return {g["name"]: {k: g[k] for k in ("chg_1d", "chg_1w", "chg_1m", "chg_3m", "chg_6m")}
            for g in _tv_group_scan("sector", progress_cb)}


def fetch_tv_industry_performance(progress_cb=None):
    """Exact TradingView industry performance: a list of dicts with name,
    parent sector name and chg_1d/1w/1m/3m/6m — the same numbers shown on the
    website (INDUSTRY_US:* symbols)."""
    return _tv_group_scan("industry", progress_cb)


def fetch_benchmark_metrics():
    """SPY metrics for the market summary / rs_vs_spy baseline."""
    for symbol in ("AMEX:SPY", "NYSEARCA:SPY", "BATS:SPY"):
        try:
            rows = _tv_scan_chunk([symbol])
        except Exception:
            continue
        if rows:
            m = _tv_row_to_metrics(next(iter(rows.values())))
            if m:
                m["ticker"] = BENCHMARK_TICKER
                return m
    return None


# Live index quotes (SPY / QQQ / DJI / IWM) straight from the TradingView
# scanners. The index_cci table is only refreshed on a full sync (yfinance
# daily bars), so prices/returns read from it go stale between syncs; this
# feed is current to the latest TradingView tick and overlays the stale
# numbers in /api/dashboard. DJI is the index itself (TVC:DJI) on the global
# scanner — it is not listed on the america scanner.
INDEX_QUOTE_SYMBOLS = [
    ("SPY", "AMEX:SPY", TV_SCAN_URL),
    ("QQQ", "NASDAQ:QQQ", TV_SCAN_URL),
    ("IWM", "AMEX:IWM", TV_SCAN_URL),
    ("DJI", "TVC:DJI", "https://scanner.tradingview.com/global/scan"),
]
INDEX_QUOTE_COLUMNS = ["close", "change", "Perf.W", "Perf.1M", "Perf.3M", "Perf.YTD", "Perf.Y"]


def fetch_index_quotes(progress_cb=None):
    """Live price + multi-period returns for the major indexes.
    Returns {ticker: {price, chg_1d, chg_1w, chg_1m, chg_3m, chg_ytd, chg_1y}};
    indexes that fail to fetch are simply absent."""
    by_url = {}
    for ticker, symbol, url in INDEX_QUOTE_SYMBOLS:
        by_url.setdefault(url, []).append((ticker, symbol))
    out = {}
    for url, items in by_url.items():
        body = {"symbols": {"tickers": [s for _, s in items], "query": {"types": []}},
                "columns": INDEX_QUOTE_COLUMNS}
        try:
            data = _tv_post(body, url=url).get("data") or []
        except Exception as e:
            if progress_cb:
                progress_cb(f"Live index quotes failed ({url}): {e}")
            continue
        got = {row["s"]: row.get("d") or [] for row in data}
        for ticker, symbol in items:
            vals = got.get(symbol)
            if not vals or len(vals) != len(INDEX_QUOTE_COLUMNS):
                continue
            d = dict(zip(INDEX_QUOTE_COLUMNS, vals))
            if not d.get("close"):
                continue

            def r2(key):
                v = d.get(key)
                return round(float(v), 2) if isinstance(v, (int, float)) else None

            out[ticker] = {
                "price": r2("close"),
                "chg_1d": r2("change"),
                "chg_1w": r2("Perf.W"),
                "chg_1m": r2("Perf.1M"),
                "chg_3m": r2("Perf.3M"),
                "chg_ytd": r2("Perf.YTD"),
                "chg_1y": r2("Perf.Y"),
            }
    return out


# ---------------------------------------------------------------------------
# ETF hub: quotes for a curated universe of liquid US ETFs
# ---------------------------------------------------------------------------
ETF_HUB_COLUMNS = [
    "close", "change", "Perf.W", "Perf.1M", "Perf.3M", "Perf.6M", "Perf.YTD",
    "Perf.Y", "ADR", "volume", "average_volume_30d_calc",
    "relative_volume_10d_calc", "price_52_week_high", "price_52_week_low",
    "SMA20", "SMA50", "Volatility.D", "Volatility.W", "Volatility.M",
    "description", "aum",
]


def fetch_etf_hub_quotes(tickers):
    """One chunked scanner call for the ETF hub universe. Tries AMEX first
    (all hub ETFs are NYSE Arca/Nasdaq listed and AMEX resolves them), then
    retries any ticker that came back empty on NASDAQ and NYSE. Returns
    {ticker: {column: value}} raw dicts (SPY included)."""
    def scan(symbols):
        body = {"symbols": {"tickers": symbols, "query": {"types": []}},
                "columns": ETF_HUB_COLUMNS}
        out = {}
        for row in (_tv_post(body).get("data") or []):
            vals = row.get("d") or []
            if len(vals) == len(ETF_HUB_COLUMNS):
                out[row["s"]] = dict(zip(ETF_HUB_COLUMNS, vals))
        return out

    rows = scan(["AMEX:" + t for t in tickers])
    found = {s.split(":", 1)[1] for s in rows}
    missing = [t for t in tickers if t not in found]
    for exch in ("NASDAQ", "NYSE", "CBOE"):
        if not missing:
            break
        extra = scan([exch + ":" + t for t in missing])
        for s, vals in extra.items():
            rows[s] = vals
            found.add(s.split(":", 1)[1])
        missing = [t for t in missing if t not in found]

    out = {}
    for sym, vals in rows.items():
        if vals.get("close"):
            out[sym.split(":", 1)[1]] = vals
    return out


# ---------------------------------------------------------------------------
# Index CCI(34) oscillator ratings (SPY / QQQ / DJI / IWM) via yfinance
# ---------------------------------------------------------------------------

# Hard ceiling for the whole batched yfinance download — one stalled ticker
# must never wedge the sync forever.
YF_BATCH_TIMEOUT = 90


def _yf_download_batch(symbols, period="2y"):
    """Download daily OHLC for many symbols in ONE yfinance call (threaded
    internally), with a hard timeout. Returns {symbol: ohlc_dataframe}."""
    import pandas as pd
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

    def _dl():
        return yf.download(list(symbols), period=period, interval="1d",
                           progress=False, auto_adjust=True, group_by="ticker",
                           threads=True)
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            df = ex.submit(_dl).result(timeout=YF_BATCH_TIMEOUT)
    except FutTimeout:
        return {}
    except Exception:
        return {}
    out = {}
    if df is None or not len(df):
        return out
    for sym in symbols:
        try:
            sub = df[sym] if isinstance(df.columns, pd.MultiIndex) else df
            sub = sub.dropna(subset=["High", "Low", "Close"])
            if len(sub):
                out[sym] = sub
        except Exception:
            continue
    return out


def _round10(v):
    """Round to the closest 10 (CCI readout granularity requested by the user)."""
    return int(round(v / 10.0) * 10)


def _today_ny():
    """Today's date in America/New_York (fallback: local date)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).date()
    except Exception:
        return date.today()


def _closed_bars(df):
    """Drop the last bar when it is today's still-open session ("wait for
    timeframe closes", matching the TradingView CCI setting)."""
    if df is not None and len(df) and df.index[-1].date() >= _today_ny():
        return df.iloc[:-1]
    return df


def _cci_from_df(df):
    """CCI(34) on HLC3 + EMA(13) of CCI from a daily OHLC frame — the exact
    TradingView CCI settings (length 34, source (H+L+C)/3, EMA smoothing 13,
    "wait for timeframe closes"). Today's still-open bar is ignored so the
    value matches the closed-bar CCI on the chart.
    Returns (raw_cci, raw_ema, rounded_cci, rounded_ema) where the rounded
    pair is snapped to the closest 10, or None."""
    df = _closed_bars(df)
    if df is None:
        return None
    min_rows = CCI_LENGTH + CCI_EMA_LENGTH + 5
    if len(df) < min_rows:
        return None
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    sma = tp.rolling(CCI_LENGTH).mean()
    mad = tp.rolling(CCI_LENGTH).apply(lambda x: abs(x - x.mean()).mean(), raw=True)
    cci = ((tp - sma) / (0.015 * mad)).dropna()
    if len(cci) < CCI_EMA_LENGTH:
        return None
    cci_ema = cci.ewm(span=CCI_EMA_LENGTH, adjust=False).mean()
    raw_cci, raw_ema = float(cci.iloc[-1]), float(cci_ema.iloc[-1])
    return raw_cci, raw_ema, _round10(raw_cci), _round10(raw_ema)


def cci_zone(cci):
    """Zone classification for a (nearest-10) CCI value:
    bullish above 100, neutral between 0 and 100, bearish below 0."""
    if cci is None:
        return "unknown"
    if cci > 100:
        return "bullish"
    if cci >= 0:
        return "neutral"
    return "bearish"


# Hub-ETF daily bars cache — one batched yfinance download every 30 min at
# most. CCI is computed from these cached frames, and the ETF scoring model
# reuses the same frames, so neither triggers extra downloads.
_hub_etf_bars_cache = {"at": 0.0, "data": {}}
_HUB_ETF_BARS_TTL = 1800.0


def fetch_hub_etf_bars(tickers):
    """{ticker: daily OHLCV DataFrame} for the hub ETFs plus SPY (SPY is
    always included — the scoring model needs it as the RS benchmark). One
    batched yfinance download, cached for 30 min; per-ticker failures yield
    None and stale frames are kept if a refresh fails."""
    tickers = list(dict.fromkeys(list(tickers) + [BENCHMARK_TICKER]))
    now = time.time()
    data = _hub_etf_bars_cache["data"]
    if not data or now - _hub_etf_bars_cache["at"] >= _HUB_ETF_BARS_TTL:
        try:
            frames = _yf_download_batch(tickers, period="1y")
            if frames:
                data.update(frames)
        except Exception:
            pass  # keep serving whatever is cached
        _hub_etf_bars_cache["at"] = now
        _hub_etf_bars_cache["data"] = data
    return {t: data.get(t) for t in tickers}


def fetch_hub_etf_cci(tickers):
    """CCI(34) + EMA(13) for each hub ETF (values rounded to the nearest 10,
    matching the rest of the app), computed from the cached daily bars
    (fetch_hub_etf_bars) — no extra downloads. Per-ticker failures yield None."""
    frames = fetch_hub_etf_bars(tickers)
    out = {}
    for t in tickers:
        res = _cci_from_df(frames.get(t))
        out[t] = ({"cci": res[2], "cci_ema": res[3], "cci_zone": cci_zone(res[2])}
                  if res else None)
    return out


def cci_for_symbols(symbols):
    """One-shot CCI(34) classification for an arbitrary symbol list (e.g. ETF
    constituents). Returns {symbol: {"cci", "cci_ema", "cci_zone"}}; failed
    symbols are omitted."""
    out = {}
    try:
        frames = _yf_download_batch(symbols, period="1y")
    except Exception:
        return out
    for sym, df in frames.items():
        res = _cci_from_df(df)
        if res:
            out[sym] = {"cci": res[2], "cci_ema": res[3],
                        "cci_zone": cci_zone(res[2])}
    return out


def fetch_index_cci(progress_cb=None):
    """CCI(34) daily oscillator + its EMA(13) for each major index, classified
    with engine.cci_rating. Returns a list of dicts ready for the index_cci
    table. Indices that fail to download are skipped."""
    def log(msg):
        if progress_cb:
            progress_cb(msg)

    symbols = [idef["yf_symbol"] for idef in INDEX_DEFS]
    log("Downloading %d index histories in one batch..." % len(symbols))
    data = _yf_download_batch(symbols)

    out = []
    for idef in INDEX_DEFS:
        df = _closed_bars(data.get(idef["yf_symbol"]))
        cci_vals = _cci_from_df(df)
        if cci_vals is None:
            log("%s: no usable history, skipped." % idef["ticker"])
            continue
        raw_cci, raw_ema, last_cci, last_ema = cci_vals
        close = df["Close"]

        def _ret(days_back):
            if len(close) <= days_back:
                return None
            return round(float((close.iloc[-1] / close.iloc[-1 - days_back] - 1) * 100), 2)

        # YTD: last close vs the close of the final session before this year
        this_year = df.index[-1].year
        prev_year = close[close.index.year < this_year]
        chg_ytd = (round(float((close.iloc[-1] / prev_year.iloc[-1] - 1) * 100), 2)
                   if len(prev_year) else None)

        out.append({
            "ticker": idef["ticker"],
            "dt": str(df.index[-1].date()),
            "price": round(float(close.iloc[-1]), 2),
            "chg_1d": round(float((close.iloc[-1] / close.iloc[-2] - 1) * 100), 2),
            "chg_1w": _ret(5),
            "chg_1m": _ret(21),
            "chg_3m": _ret(63),
            "chg_ytd": chg_ytd,
            "chg_1y": _ret(252),
            "cci34": last_cci,
            "cci_ema": last_ema,
            "rating": cci_rating(raw_cci, raw_ema),
        })
    return out


def fetch_sector_etf_cci(progress_cb=None):
    """CCI(34) daily oscillator + its EMA(13) for every sector's proxy ETF
    (SECTOR_ETF_MAP). This is the "sector CCI" the strategy engines use —
    CCI of the representative ETF, not a custom sector index. Returns a list
    of dicts ready for the sector_etf_cci table; ETFs that fail to download
    are skipped."""
    def log(msg):
        if progress_cb:
            progress_cb(msg)

    etf_by_idx = {}
    for s_idx, sdef in enumerate(SECTOR_DEFS, start=1):
        etf = SECTOR_ETF_MAP.get(sdef["name"])
        if etf:
            etf_by_idx[s_idx] = etf
    log("Downloading %d sector ETF histories in one batch..." % len(etf_by_idx))
    data = _yf_download_batch(sorted(set(etf_by_idx.values())))

    out = []
    for s_idx, etf in etf_by_idx.items():
        df = _closed_bars(data.get(etf))
        cci_vals = _cci_from_df(df)
        if cci_vals is None:
            log("%s: no usable history, skipped." % etf)
            continue
        raw_cci, raw_ema, last_cci, last_ema = cci_vals
        out.append({
            "sector_id": s_idx,
            "etf": etf,
            "dt": str(df.index[-1].date()),
            "cci34": last_cci,
            "cci_ema": last_ema,
            "rating": cci_rating(raw_cci, raw_ema),
        })
    return out


def fetch_industry_etf_cci(progress_cb=None, frames=None):
    """CCI(34) daily oscillator + its EMA(13) for every mapped industry's
    benchmark ETF (INDUSTRY_ETF_MAP). This is the "industry CCI" the industry
    leadership score uses for industries with more than 25 stocks. Returns a
    list of dicts ready for the industry_etf_cci table; ETFs that fail to
    download are skipped. `frames` optionally supplies pre-downloaded OHLC
    data ({symbol: dataframe}) so one yfinance batch can feed both the CCI
    and the MA-pullback signal pass."""
    def log(msg):
        if progress_cb:
            progress_cb(msg)

    etfs = sorted(set(INDUSTRY_ETF_MAP.values()))
    if frames is None:
        log("Downloading %d industry benchmark ETF histories in one batch..." % len(etfs))
        frames = _yf_download_batch(etfs)
    data = frames
    cci_by_etf = {}
    for etf in etfs:
        df = _closed_bars(data.get(etf))
        cci_vals = _cci_from_df(df)
        if cci_vals is None:
            log("%s: no usable history, skipped." % etf)
            continue
        raw_cci, raw_ema, last_cci, last_ema = cci_vals
        cci_by_etf[etf] = {
            "dt": str(df.index[-1].date()),
            "cci34": last_cci, "cci_ema": last_ema,
            "rating": cci_rating(raw_cci, raw_ema),
        }

    out = []
    for industry, etf in INDUSTRY_ETF_MAP.items():
        vals = cci_by_etf.get(etf)
        if vals is None:
            continue
        out.append({"industry": industry, "etf": etf, **vals})
    return out


def fetch_industry_ma_signals(frames=None, progress_cb=None, lookback=5):
    """MA-pullback green-candle signal (engine.detect_ma_pullback_signal) for
    every mapped industry's benchmark ETF, run over each of the last
    `lookback` closed sessions. Returns rows for the industry_ma_signal
    table. `frames` optionally reuses the yfinance batch downloaded for the
    CCI pass ({symbol: dataframe}); otherwise one batch is downloaded here."""
    def log(msg):
        if progress_cb:
            progress_cb(msg)

    etfs = sorted(set(INDUSTRY_ETF_MAP.values()))
    if frames is None:
        log("Downloading industry ETF histories for MA-pullback signals...")
        frames = _yf_download_batch(etfs)

    bars_by_etf = {}
    for etf in etfs:
        df = _closed_bars(frames.get(etf))
        if df is None or not len(df):
            continue
        try:
            bars = []
            for ts, row in df.iterrows():
                vol = row["Volume"] if "Volume" in row and row["Volume"] == row["Volume"] else None
                bars.append({
                    "dt": str(ts.date()),
                    "open": float(row["Open"]), "high": float(row["High"]),
                    "low": float(row["Low"]), "close": float(row["Close"]),
                    "volume": float(vol) if vol else None,
                })
            bars_by_etf[etf] = bars
        except Exception:
            continue

    out = []
    for industry, etf in INDUSTRY_ETF_MAP.items():
        bars = bars_by_etf.get(etf)
        if not bars:
            continue
        for back in range(lookback, 0, -1):
            res = detect_ma_pullback_signal(bars[:-back + 1] if back > 1 else bars)
            if res is None:
                continue
            out.append({
                "dt": bars[-back]["dt"], "industry": industry, "etf": etf,
                "detected": int(res["detected"]), "body_ratio": res["body_ratio"],
                "close_pos": res["close_pos"], "vol_ratio": res["vol_ratio"],
            })
    log("MA-pullback signals: %d rows for %d industries." % (len(out), len(INDUSTRY_ETF_MAP)))
    return out


def compute_rs_ratings(stocks):
    """RS rating = percentile rank of 3-month performance across the universe."""
    vals = sorted(m["chg_3m"] for m in stocks)
    n = len(vals)
    for m in stocks:
        below = sum(1 for v in vals if v <= m["chg_3m"])
        m["rs_rating"] = round(max(1, min(99, below / n * 100)), 1) if n else 50.0
    return stocks


# ---------------------------------------------------------------------------
# Sync orchestration
# ---------------------------------------------------------------------------

STOCK_INSERT_SQL = """INSERT OR REPLACE INTO stock (ticker, market_cap_musd, price, avg_volume,
   chg_1d, chg_1w, chg_1m, chg_3m, chg_6m,
   rs_rating, rs_vs_spy_1m, pct_from_52w_high, pct_from_52w_low, volume_ratio,
   above_20d, above_50d, above_200d, momentum_20d, days_since_new_high, is_new_high_today, sector_id,
   ema10, ema20, ema50, ema5, ema200, dist_high_1m, dist_high_3m, ext_ema10, volatility_d, atr, industry, recommend_all,
   chg_ytd, chg_1y, recommend_ma, recommend_other, recommend_all_1w, recommend_ma_1w, recommend_other_1w, adr_pct,
   volatility_w, volatility_m,
   open_price, day_high, day_low, chg_from_open, gap_pct, pm_chg, pm_vol, volume_today, above_100ema)
   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""


def _stock_row(t, m, sector_id):
    return (
        t, m.get("market_cap_musd"), m["price"], m["avg_volume"],
        m["chg_1d"], m["chg_1w"], m["chg_1m"], m["chg_3m"], m["chg_6m"],
        m.get("rs_rating"), m.get("rs_vs_spy_1m"), m["pct_from_52w_high"], m["pct_from_52w_low"],
        m["volume_ratio"], int(m["above_20d"]), int(m["above_50d"]), int(m["above_200d"]),
        m["momentum_20d"], m["days_since_new_high"], int(m["is_new_high_today"]), sector_id,
        m.get("ema10"), m.get("ema20"), m.get("ema50"), m.get("ema5"), m.get("ema200"),
        m.get("dist_high_1m"), m.get("dist_high_3m"), m.get("ext_ema10"),
        m.get("volatility_d"), m.get("atr"), m.get("industry"), m.get("recommend_all"),
        m.get("chg_ytd"), m.get("chg_1y"), m.get("recommend_ma"), m.get("recommend_other"),
        m.get("recommend_all_1w"), m.get("recommend_ma_1w"), m.get("recommend_other_1w"),
        m.get("adr_pct"),
        m.get("volatility_w"), m.get("volatility_m"),
        m.get("open_price"), m.get("day_high"), m.get("day_low"), m.get("chg_from_open"),
        m.get("gap_pct"), m.get("pm_chg"), m.get("pm_vol"), m.get("volume_today"),
        int(m["above_100ema"]) if m.get("above_100ema") is not None else None,
    )


# ---------------------------------------------------------------------------
# TradingView news headlines (keyless) — EP catalyst verification
# ---------------------------------------------------------------------------

TV_NEWS_URL = "https://news-headlines.tradingview.com/v2/view/headlines/symbol"
TV_NEWS_TIMEOUT = 4
TV_NEWS_EXCHANGES = ("NASDAQ", "NYSE", "AMEX")
NEWS_CACHE_TTL = 600          # seconds; in-memory per-process cache
NEWS_MAX_WORKERS = 8
NEWS_CATALYST_MAX_AGE_H = 72.0

# (catalyst type, keywords) — first match wins, order = priority
CATALYST_KEYWORDS = [
    ("earnings", ["earnings", "eps", "quarterly results", "q1 results", "q2 results",
                  "q3 results", "q4 results", "profit beats", "revenue beats", "beats estimates"]),
    ("guidance", ["guidance", "outlook", "forecast", "raises full-year", "cuts full-year",
                  "raises fy", "lowers fy"]),
    ("fda", ["fda", "clinical", "trial results", "phase 1", "phase 2", "phase 3",
             "approval", "pdufa", "breakthrough therapy"]),
    ("mna", ["acquire", "acquisition", "merger", "takeover", "buyout", "to buy",
             "bid for", "stake in"]),
    ("contract", ["contract", "order worth", "deal worth", "partnership", "agreement",
                  "wins award", "collaboration"]),
    ("offering", ["offering", "secondary", "share sale", "dilution", "stock sale",
                  "at-the-market", "atm program", "warrant exercise", "private placement"]),
    ("analyst", ["upgrade", "downgrade", "price target", "initiated", "rating",
                 "overweight", "underweight", "buy rating", "sell rating"]),
    ("legal", ["lawsuit", "settlement", "sec probe", "investigation", "subpoena",
               "indicted", "fraud charges"]),
    ("macro", ["fed ", "interest rate", "inflation", "tariff", "jobs report", "cpi",
               "treasury", "recession"]),
]
PROMO_KEYWORDS = ["stock alert", "stock pick", "penny stock", "hot stock", "must buy",
                  "next big", "breakout alert"]

_news_cache = {}  # ticker -> (fetched_at_epoch, item dict or None)


def classify_catalyst(title):
    """Map a headline to a catalyst type via keywords (see CATALYST_KEYWORDS)."""
    t = (title or "").lower()
    for ctype, kws in CATALYST_KEYWORDS:
        if any(k in t for k in kws):
            return ctype
    return "other"


def _is_promotional(title, source):
    t = ("%s %s" % (title or "", source or "")).lower()
    return any(k in t for k in PROMO_KEYWORDS)


def fetch_tv_news_headlines(symbol):
    """Raw headline items for an exchange-prefixed symbol (e.g. 'NASDAQ:AAPL').
    Returns the items list, or None on any error."""
    try:
        resp = requests.get(
            TV_NEWS_URL,
            params={"client": "web", "lang": "en", "symbol": symbol},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/120.0 Safari/537.36"},
            timeout=TV_NEWS_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        return (resp.json() or {}).get("items") or []
    except Exception:
        return None


def fetch_ticker_news(ticker):
    """Best (most recent) news catalyst for a bare ticker, trying the major
    US exchanges. Returns {headline, source, ctype, age_h, status, promo} or
    None when no news exists / every fetch failed. Cached ~10 min in-memory."""
    now = time.time()
    hit = _news_cache.get(ticker)
    if hit and now - hit[0] < NEWS_CACHE_TTL:
        return hit[1]
    item = None
    for exch in TV_NEWS_EXCHANGES:
        items = fetch_tv_news_headlines("%s:%s" % (exch, ticker.replace("-", ".")))
        if items:
            items.sort(key=lambda it: it.get("published") or 0, reverse=True)
            top = items[0]
            age_h = round(max(0.0, (now - (top.get("published") or 0)) / 3600.0), 1)
            source = top.get("source") or top.get("provider") or ""
            title = top.get("title") or ""
            promo = _is_promotional(title, source)
            fresh = age_h <= NEWS_CATALYST_MAX_AGE_H
            status = ("verified" if (fresh and source and not promo)
                      else "unverified")
            item = {"headline": title, "source": source,
                    "ctype": classify_catalyst(title), "age_h": age_h,
                    "status": status, "promo": promo}
            break
    _news_cache[ticker] = (now, item)
    return item


def fetch_tv_news_batch(tickers, max_workers=NEWS_MAX_WORKERS):
    """News catalysts for many tickers at once (bounded thread pool).
    Returns {ticker: catalyst dict or None}."""
    from concurrent.futures import ThreadPoolExecutor
    out = {}
    tickers = [t for t in tickers if t]
    if not tickers:
        return out
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for ticker, item in zip(tickers, ex.map(fetch_ticker_news, tickers)):
            out[ticker] = item
    return out


def fetch_symbol_emas(symbol):
    """EMA readout (5/10/20/50/200) + price for one symbol (e.g. a sector proxy
    ETF) from the TradingView scanner. Returns None when unavailable."""
    cols = ["close", "EMA5", "EMA10", "EMA20", "EMA50", "EMA200"]
    for exchange in ("AMEX", "NASDAQ", "NYSE"):
        try:
            body = {"symbols": {"tickers": [f"{exchange}:{symbol}"], "query": {"types": []}},
                    "columns": cols}
            data = _tv_post(body).get("data") or []
        except Exception:
            continue
        if not data:
            continue
        d = dict(zip(cols, data[0].get("d") or []))
        if not d.get("close"):
            continue
        def f(key):
            return round(float(d[key]), 2) if d.get(key) is not None else None
        return {
            "symbol": symbol,
            "price": round(float(d["close"]), 2),
            "ema5": f("EMA5"), "ema10": f("EMA10"), "ema20": f("EMA20"),
            "ema50": f("EMA50"), "ema200": f("EMA200"),
        }
    return None


def sync_all(progress_cb=None):
    """Full live sync: one TradingView whole-market scan -> group by TradingView
    sector -> top-10 3M performers per sector for holdings -> RS ratings -> DB.
    Sector scores/breadth aggregate ALL filtered stocks in the sector; the
    displayed sector performance comes from a second, unfiltered scan of
    every TradingView constituent, market-cap weighted (matches TradingView)."""
    init_db()  # idempotent: applies schema migrations before we write new columns
    conn = _mk_conn()
    c = conn.cursor()
    report = {"synced_at": datetime.now(timezone.utc).isoformat(), "sectors": {}, "errors": []}

    def log(msg):
        if progress_cb:
            progress_cb(msg)

    # 1. whole-market scan (server-side mcap/volume/price filters + client-side
    # ADR filter, with per-stage drop accounting in scan_stats)
    scan_stats = {}
    stocks = fetch_tv_market_scan(progress_cb=log, stats_out=scan_stats)
    if not stocks:
        conn.close()
        return {"ok": False, "error": "TradingView scan returned no stocks", "synced_at": report["synced_at"]}
    report["market_screen_count"] = len(stocks)
    report["filter_breakdown"] = scan_stats
    # Basic completeness check: the scan must have downloaded every row
    # TradingView says matches the server-side filters.
    if scan_stats.get("server_total") and scan_stats.get("downloaded", 0) < scan_stats["server_total"]:
        report["errors"].append(
            f"TradingView scan incomplete: {scan_stats['downloaded']}/{scan_stats['server_total']} "
            "rows downloaded — some stocks are missing from this sync")
    log("Filter breakdown: %d rows from TradingView -> %d kept "
        "(%d below ADR >= %s%%, %d no ADR, %d no price, %d duplicates, %d non-US-exchange, %d malformed)."
        % (scan_stats.get("downloaded", 0), len(stocks),
           scan_stats.get("adr_below_min", 0), MIN_ADR_PCT,
           scan_stats.get("adr_missing", 0), scan_stats.get("no_price", 0),
           scan_stats.get("duplicates", 0), scan_stats.get("wrong_exchange", 0),
           scan_stats.get("bad_rows", 0)))

    # 2. benchmark for the rs_vs_spy baseline
    log("Fetching SPY benchmark metrics...")
    bench = fetch_benchmark_metrics()
    spy_1m = bench["chg_1m"] if bench else 0.0
    if not bench:
        report["errors"].append("SPY benchmark metrics unavailable")

    # 3. RS ratings (3M-based) + RS vs SPY
    log("Computing RS ratings (3-month relative strength)...")
    compute_rs_ratings(stocks)
    for m in stocks:
        m["rs_vs_spy_1m"] = round(m["chg_1m"] - spy_1m, 2)

    # 4. group by TradingView sector; ensure a sector row exists for each name
    name_to_def = {s["name"]: (i + 1, s) for i, s in enumerate(SECTOR_DEFS)}
    sector_id_by_name = {}
    by_sector = {}
    for m in stocks:
        name = m.get("sector") or "Miscellaneous"
        by_sector.setdefault(name, []).append(m)
    next_id = len(SECTOR_DEFS) + 1
    sdef_by_name = {}
    for name in sorted(by_sector):
        if name in name_to_def:
            sid, sdef = name_to_def[name]
        else:  # a sector TradingView added that we don't know yet
            sid, sdef = next_id, {"name": name, "ticker": name[:4].upper().replace(" ", ""), "sub": "Cyclical", "tags": "other"}
            next_id += 1
        sector_id_by_name[name] = sid
        sdef_by_name[name] = sdef
        c.execute(
            """INSERT OR IGNORE INTO sector (id, name, ticker, sub, tags, color, conviction)
               VALUES (?,?,?,?,?,?,?)""",
            (sid, sdef["name"], sdef["ticker"], sdef["sub"], sdef["tags"],
             SECTOR_COLORS[(sid - 1) % len(SECTOR_COLORS)], 3),
        )
        c.execute("UPDATE sector SET color=? WHERE id=?", (SECTOR_COLORS[(sid - 1) % len(SECTOR_COLORS)], sid))
        c.execute(
            "INSERT OR REPLACE INTO etf (ticker, name, sector_id, role, weighting) VALUES (?,?,?,?,?)",
            (sdef["ticker"], sdef["name"], sid, "primary", "equal"),
        )

    # 5. top-10 per sector by 3M performance; re-apply the universal filters on
    # the stored metrics first (the scanner's server-side volume filter is not
    # perfectly consistent with the returned average_volume columns)
    log("Selecting top 10 three-month performers per sector...")
    today = date.today().isoformat()
    c.execute("DELETE FROM holding")
    c.execute("DELETE FROM stock")

    def passes(m):
        return (m.get("market_cap_musd") is not None and m["market_cap_musd"] >= MIN_MARKET_CAP_MUSD
                and m["avg_volume"] and m["avg_volume"] >= MIN_AVG_VOLUME
                and m.get("adr_pct") is not None and m["adr_pct"] >= MIN_ADR_PCT
                and m.get("price") is not None and m["price"] >= MIN_PRICE)

    top_by_sector = {}
    for name, members in by_sector.items():
        top = [m for m in sorted(members, key=lambda m: m["chg_3m"], reverse=True) if passes(m)][:TOP_N_PER_SECTOR]
        top_by_sector[name] = top
        report["sectors"][name] = {"n_holdings": len(top), "n_scanned": len(members)}
    # Coverage check: log how many passing stocks landed in each sector so a
    # silently missing sector/industry is visible in the sync log.
    log("Stocks per sector: " + ", ".join(
        f"{name}={len(members)}" for name, members in sorted(by_sector.items())))

    # 6. write all scanned stocks (sector-mapped), holdings for the top-10s, benchmark
    log(f"Writing {len(stocks)} stocks to the database...")
    for m in stocks:
        sid = sector_id_by_name.get(m.get("sector") or "Miscellaneous")
        c.execute(STOCK_INSERT_SQL, _stock_row(m["ticker"], m, sid))
    for name, top in top_by_sector.items():
        sdef_ticker = sdef_by_name[name]["ticker"]
        for m in top:
            c.execute(
                "INSERT INTO holding (etf_ticker, stock_ticker, weight_pct, as_of_date) VALUES (?,?,?,?)",
                (sdef_ticker, m["ticker"], round(100.0 / len(top), 2), today),
            )
    if bench:
        c.execute(STOCK_INSERT_SQL, _stock_row(BENCHMARK_TICKER, bench, None))

    # 7. sector CCI(34) of each sector's proxy ETF (SECTOR_ETF_MAP) — computed
    # BEFORE the snapshot rollup because the canonical sector score is
    # CCI-based (50% performance + 50% CCI).
    log("Computing sector CCI(34) from proxy ETFs (SMH, IGV, XBI, ...)...")
    try:
        etf_rows = fetch_sector_etf_cci(progress_cb=log)
        c.execute("DELETE FROM sector_etf_cci")
        for r in etf_rows:
            c.execute(
                "INSERT OR REPLACE INTO sector_etf_cci (sector_id, etf, dt, cci34, cci_ema, rating)"
                " VALUES (?,?,?,?,?,?)",
                (r["sector_id"], r["etf"], r["dt"], r["cci34"], r["cci_ema"], r["rating"]),
            )
        if len(etf_rows) < len(SECTOR_ETF_MAP):
            report["errors"].append(
                f"Sector ETF CCI: only {len(etf_rows)}/{len(SECTOR_ETF_MAP)} ETFs downloaded")
    except Exception as e:
        report["errors"].append(f"Sector ETF CCI unavailable: {e}")

    # 7b. industry CCI(34) of each mapped industry's benchmark ETF
    # (INDUSTRY_ETF_MAP) — the CCI input for the industry leadership score of
    # industries with more than 25 stocks.
    log("Computing industry CCI(34) from benchmark ETFs (SMH, XBI, KRE, ...)...")
    try:
        # One yfinance batch feeds both the CCI pass and the MA-pullback
        # green-candle signal pass below.
        ind_etf_frames = _yf_download_batch(sorted(set(INDUSTRY_ETF_MAP.values())))
        ind_etf_rows = fetch_industry_etf_cci(progress_cb=log, frames=ind_etf_frames)
        c.execute("DELETE FROM industry_etf_cci")
        for r in ind_etf_rows:
            c.execute(
                "INSERT OR REPLACE INTO industry_etf_cci (industry, etf, dt, cci34, cci_ema, rating)"
                " VALUES (?,?,?,?,?,?)",
                (r["industry"], r["etf"], r["dt"], r["cci34"], r["cci_ema"], r["rating"]),
            )
        if len(ind_etf_rows) < len(INDUSTRY_ETF_MAP):
            report["errors"].append(
                f"Industry ETF CCI: only {len(ind_etf_rows)}/{len(INDUSTRY_ETF_MAP)} industries got CCI")
    except Exception as e:
        report["errors"].append(f"Industry ETF CCI unavailable: {e}")

    # 7c. MA-pullback green-candle signals on the same industry ETF history
    log("Detecting MA-pullback green-candle signals on industry ETFs...")
    try:
        sig_rows = fetch_industry_ma_signals(frames=ind_etf_frames, progress_cb=log)
        c.execute("DELETE FROM industry_ma_signal")
        for r in sig_rows:
            c.execute(
                """INSERT OR REPLACE INTO industry_ma_signal
                   (dt, industry, etf, detected, body_ratio, close_pos, vol_ratio, bonus)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (r["dt"], r["industry"], r["etf"], r["detected"], r["body_ratio"],
                 r["close_pos"], r["vol_ratio"],
                 PATTERN_BONUS if r["detected"] else 0.0),
            )
    except Exception as e:
        report["errors"].append(f"Industry MA-pullback signals unavailable: {e}")

    # 8. index CCI(34) oscillator ratings (SPY / QQQ / DJI / IWM)
    log("Computing CCI(34) ratings for SPY / QQQ / DJI / IWM...")
    try:
        idx_rows = fetch_index_cci(progress_cb=log)
        c.execute("DELETE FROM index_cci")
        for r in idx_rows:
            c.execute(
                "INSERT OR REPLACE INTO index_cci (ticker, dt, price, chg_1d, cci34, cci_ema, rating,"
                " chg_1w, chg_1m, chg_3m, chg_ytd, chg_1y) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["ticker"], r["dt"], r["price"], r["chg_1d"], r["cci34"], r["cci_ema"], r["rating"],
                 r.get("chg_1w"), r.get("chg_1m"), r.get("chg_3m"), r.get("chg_ytd"), r.get("chg_1y")),
            )
        if len(idx_rows) < len(INDEX_DEFS):
            report["errors"].append(f"Index CCI: only {len(idx_rows)}/{len(INDEX_DEFS)} indices downloaded")
    except Exception as e:
        report["errors"].append(f"Index CCI unavailable: {e}")

    # 9. sector snapshot rollup for today. Two data layers:
    #    - displayed performance: COPIED VERBATIM from TradingView's own
    #      sector and industry symbols (SECTOR_US:* / INDUSTRY_US:* on the
    #      scanner API) — the exact numbers shown on the website for every
    #      horizon (1D / 1W / 1M / 3M / 6M).
    #    - scores: CCI-based (50% normalized performance + 50% sector CCI);
    #      breadth/new-highs aggregated from the filtered momentum universe
    #      (whole-sector average and breadth, so a handful of explosive
    #      small-cap runners cannot put a sector at the top on their own)
    log("Computing sector snapshots...")
    log("Fetching exact TradingView sector performance (SECTOR_US:* symbols)...")
    try:
        tv_sector_perf = fetch_tv_sector_performance(progress_cb=log)
    except Exception as e:
        tv_sector_perf = {}
        report["errors"].append(f"TradingView exact sector performance scan failed: {e}")

    # Exact TradingView industry performance, stored per sector so the
    # dashboard's industry tables show the website's numbers.
    log("Fetching exact TradingView industry performance (INDUSTRY_US:* symbols)...")
    n_ind_scraped = 0
    try:
        tv_industries = fetch_tv_industry_performance(progress_cb=log)
    except Exception as e:
        tv_industries = []
        report["errors"].append(f"TradingView exact industry performance scan failed: {e}")
    sector_id_by_lower = {n.strip().lower(): sid for n, sid in sector_id_by_name.items()}
    for ind in tv_industries:
        sid = sector_id_by_lower.get((ind.get("sector") or "").strip().lower())
        if sid is None:
            continue
        c.execute(
            "INSERT OR REPLACE INTO industry_page (dt, sector_id, name, slug, chg_1d,"
            " chg_1w, chg_1m, chg_3m, chg_6m) VALUES (?,?,?,?,?,?,?,?,?)",
            (today, sid, ind["name"], ind["symbol"], ind["chg_1d"],
             ind["chg_1w"], ind["chg_1m"], ind["chg_3m"], ind["chg_6m"]),
        )
        n_ind_scraped += 1
    log(f"TradingView industries: {n_ind_scraped} industries with exact performance stored.")
    sector_rows = []
    for name, members in by_sector.items():
        if not members:
            continue
        sid = sector_id_by_name[name]
        rows = [dict(m, weight_pct=100.0 / len(members)) for m in members]

        n = len(rows)
        avg = lambda key, rows=rows: sum(r[key] for r in rows if r.get(key) is not None) / max(1, sum(1 for r in rows if r.get(key) is not None))
        breadth = sum(1 for r in rows if r["above_50d"]) / n * 100
        avg_rs = sum(r["rs_rating"] for r in rows) / n
        rs_vs_spy = sum(r["rs_vs_spy_1m"] for r in rows) / n
        avg_vol_ratio = sum(r["volume_ratio"] for r in rows) / n
        conc = concentration_index(rows)

        # Scoring inputs: weighted performance (15% 1W / 50% 1M / 35% 3M) and
        # breadth/new-highs context; the final score is computed cross-sector
        # below via cci_sector_scores (50% normalized performance + 50% CCI).
        breadth_20 = sum(1 for r in rows if r["above_20d"]) / n * 100

        def near_pivot(r):
            dists = [d for d in (r.get("dist_high_1m"), r.get("dist_high_3m")) if d is not None]
            d = max(dists) if dists else r.get("pct_from_52w_high")
            return d is not None and d >= -5

        pct_new_highs = sum(1 for r in rows if near_pivot(r)) / n * 100

        frac_ema10_above_20 = sum(1 for r in rows if r.get("ema10") and r.get("ema20") and r["ema10"] > r["ema20"]) / n
        frac_above_50ema = sum(1 for r in rows if r.get("ema50") and r["price"] > r["ema50"]) / n

        sector_rows.append({
            "sid": sid, "name": name, "rows": rows, "avg": avg, "breadth": breadth, "avg_rs": avg_rs,
            "rs_vs_spy": rs_vs_spy, "avg_vol_ratio": avg_vol_ratio, "conc": conc,
            "pct_new_highs": pct_new_highs,
            "frac_ema10_above_20": frac_ema10_above_20, "frac_above_50ema": frac_above_50ema,
        })

    # Qullamaggie weekly-scan score (cross-sector point system + acceleration test)
    q_scores = qullamaggie_scan_scores([
        {"sector_id": sr["sid"], "perf_1w": sr["avg"]("chg_1w"), "perf_1m": sr["avg"]("chg_1m"),
         "perf_3m": sr["avg"]("chg_3m"), "perf_6m": sr["avg"]("chg_6m"),
         "breadth": sr["breadth"], "rs_vs_spy": sr["rs_vs_spy"]}
        for sr in sector_rows
    ])

    # CCI-based sector scores: performance (15% 1W / 50% 1M / 35% 3M, min-max
    # normalized 0-100 across sectors) blended 50/50 with the sector ETF CCI.
    # The performance input mirrors the displayed (TradingView-exact) sector
    # performance where available, falling back to the universe average.
    def _disp_perf(sr, key):
        tv = tv_sector_perf.get(sr["name"]) or tv_sector_perf.get(
            next((n for n in tv_sector_perf if n.strip().lower() == sr["name"].strip().lower()), "")) or {}
        v = tv.get(key)
        return v if v is not None else round(sr["avg"](key), 2)

    score_stats = [
        {"sector_id": sr["sid"], "perf_1w": _disp_perf(sr, "chg_1w"),
         "perf_1m": _disp_perf(sr, "chg_1m"), "perf_3m": _disp_perf(sr, "chg_3m")}
        for sr in sector_rows
    ]
    perf_scores = sector_performance_scores(score_stats)
    final_scores = cci_sector_scores(score_stats, 50.0, sector_cci_factors(conn))

    for sr in sector_rows:
        sid = sr["sid"]
        avg = sr["avg"]
        q_score = q_scores.get(sid, 0)
        score = final_scores.get(sid, 0)

        # Displayed sector performance: copied verbatim from TradingView's own
        # sector symbols (all horizons); fall back to the filtered-universe
        # average only when TradingView has no value for that sector.
        name = sr["name"]
        tv = tv_sector_perf.get(name) or tv_sector_perf.get(
            next((n for n in tv_sector_perf if n.strip().lower() == name.strip().lower()), "")) or {}

        def perf(key):
            v = tv.get(key)
            return v if v is not None else round(avg(key), 2)

        prev_rows = c.execute(
            "SELECT score, dt FROM sector_snapshot WHERE sector_id=? AND dt != ? ORDER BY dt DESC LIMIT 5",
            (sid, today)
        ).fetchall()
        prev_score = prev_rows[0]["score"] if prev_rows else None
        state = classify_sector_state(score, sr["breadth"], sr["avg_rs"], prev_score)

        c.execute("DELETE FROM sector_snapshot WHERE sector_id=? AND dt=?", (sid, today))
        c.execute(
            """INSERT INTO sector_snapshot (sector_id, dt, price, chg_1d, chg_1w, chg_1m, chg_3m,
               chg_6m, breadth_pct_above_50ma, avg_rs_rating, pct_new_highs, concentration_index,
               avg_volume_ratio, rs_vs_spy_1m, score, score_qullamaggie, score_bonde, state,
               etf_pct_from_52w_high, ema10_above_20, above_50ema)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, today, round(avg("price"), 2), perf("chg_1d"), perf("chg_1w"),
             perf("chg_1m"), perf("chg_3m"), perf("chg_6m"),
             round(sr["breadth"], 1), round(sr["avg_rs"], 1), round(sr["pct_new_highs"], 1),
             round(sr["conc"], 2), round(sr["avg_vol_ratio"], 2), round(sr["rs_vs_spy"], 2),
             round(score, 1), q_score, perf_scores.get(sid), state,
             round(avg("pct_from_52w_high"), 1),
             int(sr["frac_ema10_above_20"] >= 0.5), int(sr["frac_above_50ema"] >= 0.5)),
        )

    # Per-industry breadth/score history snapshot for today (same transaction).
    compute_industry_snapshots(conn, today)

    conn.commit()
    conn.close()
    report["ok"] = True
    report["universe_size"] = len(stocks)
    report["metrics_computed"] = len(stocks)
    log(f"Sync complete: {len(stocks)} stocks across {len(top_by_sector)} sectors.")
    return report


# ---------------------------------------------------------------------------
# Historical industry snapshot backfill
#
# The live sync writes ONE industry_snapshot row per industry per day, so a
# fresh install has a single snapshot date — which leaves the Capital Rotation
# deltas (need >= 2 dates) and the Breadth Timeline (needs many dates) blank.
# This backfill reconstructs real historical snapshots from ~1 year of daily
# closes (yfinance) for every stock in the `stock` table: for each trading day
# in the last ~35 calendar days it recomputes breadth (% above the 20 SMA, the
# 100 EMA — industry breadth_50 is measured as % above the 100 EMA, not the 50
# SMA — and the 200 SMA, as of that date), 1W/1M/3M performance and the industry
# leadership score using the SAME formula as the live path (engine.industry_leadership_scores —
# 50% 1M + 35% 3M + 15% 1W, min-max normalized; the CCI component falls back
# to the market default 50 since historical CCI is unavailable). Only
# industries with >= engine.IND_MIN_STOCKS stocks get rows, matching the live
# ranking's eligibility rule.
# ---------------------------------------------------------------------------

BACKFILL_CALENDAR_DAYS = 35
BACKFILL_BATCH_SIZE = 100


def backfill_industry_history(progress_cb=None, calendar_days=BACKFILL_CALENDAR_DAYS):
    """Rebuild ~1 month of daily industry_snapshot rows from historical
    closes. Returns a report dict. Does not touch today's live-synced row
    semantics — INSERT OR REPLACE per (dt, industry) only."""
    import pandas as pd
    from datetime import timedelta
    import engine as eng

    def log(msg):
        if progress_cb:
            progress_cb(msg)

    conn = _mk_conn()
    stocks = [dict(r) for r in conn.execute(
        """SELECT ticker, industry, sector_id, market_cap_musd FROM stock
           WHERE ticker != ? AND industry IS NOT NULL AND industry != ''
             AND market_cap_musd >= ? AND avg_volume >= ?
             AND (adr_pct IS NULL OR adr_pct >= ?)
             AND price >= ?""",
        (BENCHMARK_TICKER, MIN_MARKET_CAP_MUSD, MIN_AVG_VOLUME, MIN_ADR_PCT,
         MIN_PRICE),
    ).fetchall()]
    if not stocks:
        conn.close()
        return {"ok": False, "error": "no stocks in universe — run a live sync first"}

    tickers = sorted({s["ticker"] for s in stocks})
    log(f"Backfill: downloading 1y daily history for {len(tickers)} tickers…")
    ohlc = {}
    for i in range(0, len(tickers), BACKFILL_BATCH_SIZE):
        batch = tickers[i:i + BACKFILL_BATCH_SIZE]
        ohlc.update(_yf_download_batch(batch, period="1y"))
        log(f"Backfill: downloaded {min(i + BACKFILL_BATCH_SIZE, len(tickers))}/{len(tickers)} "
            f"({len(ohlc)} usable so far)")
    if not ohlc:
        conn.close()
        return {"ok": False, "error": "yfinance returned no data"}

    # Trading-day calendar = the union of session dates across all downloaded
    # series, restricted to the last `calendar_days` calendar days.
    cutoff = (_today_ny() - timedelta(days=calendar_days)).isoformat()
    all_dates = set()
    for df in ohlc.values():
        all_dates.update(d.date().isoformat() for d in df.index)
    trading_days = sorted(d for d in all_dates if d >= cutoff)
    if not trading_days:
        conn.close()
        return {"ok": False, "error": "no trading days in backfill window"}
    log(f"Backfill: computing snapshots for {len(trading_days)} trading days "
        f"({trading_days[0]} .. {trading_days[-1]})")

    # Precompute per-ticker close / SMA / rolling-high frames.
    frames = {}
    for tk, df in ohlc.items():
        try:
            close = df["Close"]
            frames[tk] = {
                "close": close,
                "dates": [d.date().isoformat() for d in close.index],
                "sma20": close.rolling(20).mean(),
                "ema100": close.ewm(span=100, adjust=False).mean(),
                "sma200": close.rolling(200).mean(),
                "high63": df["High"].rolling(63).max(),
            }
        except Exception:
            continue

    by_industry = {}
    for s in stocks:
        if s["ticker"] in frames:
            by_industry.setdefault(s["industry"], []).append(s)

    written = 0
    for dt in trading_days:
        rows = []
        for name, members in by_industry.items():
            if len(members) < eng.IND_MIN_STOCKS:
                continue
            chgs_1d, chgs_1w, chgs_1m, chgs_3m = [], [], [], []
            b20 = b50 = b200 = 0
            n_b50 = n_b200 = 0
            near_high = 0
            n_high = 0
            for m in members:
                f = frames[m["ticker"]]
                try:
                    pos = f["dates"].index(dt)
                except ValueError:
                    continue  # no bar for this ticker on this session
                close = f["close"]
                c = close.iloc[pos]
                if pos >= 1:
                    chgs_1d.append((c / close.iloc[pos - 1] - 1) * 100)
                if pos >= 5:
                    chgs_1w.append((c / close.iloc[pos - 5] - 1) * 100)
                if pos >= 21:
                    chgs_1m.append((c / close.iloc[pos - 21] - 1) * 100)
                if pos >= 63:
                    chgs_3m.append((c / close.iloc[pos - 63] - 1) * 100)
                v = f["sma20"].iloc[pos]
                if not pd.isna(v):
                    b20 += 1 if c > v else 0
                v = f["ema100"].iloc[pos]
                if not pd.isna(v):
                    n_b50 += 1
                    b50 += 1 if c > v else 0
                v = f["sma200"].iloc[pos]
                if not pd.isna(v):
                    n_b200 += 1
                    b200 += 1 if c > v else 0
                v = f["high63"].iloc[pos]
                if not pd.isna(v):
                    n_high += 1
                    near_high += 1 if (c / v - 1) * 100 >= -5 else 0
            n = len(members)

            def avg(lst):
                return round(sum(lst) / len(lst), 2) if lst else None

            sids = [m.get("sector_id") for m in members if m.get("sector_id") is not None]
            rows.append({
                "industry": name,
                "sector_id": max(set(sids), key=sids.count) if sids else None,
                "stock_count": n,
                "chg_1d": avg(chgs_1d),
                "chg_1w": avg(chgs_1w),
                "chg_1m": avg(chgs_1m),
                "chg_3m": avg(chgs_3m),
                "chg_6m": None,
                "breadth_20": round(b20 / n * 100, 1),
                "breadth_50": round(b50 / n * 100, 1),
                "breadth_200": round(b200 / n * 100, 1) if n_b200 else None,
                "pct_new_highs": round(near_high / n_high * 100, 1) if n_high else None,
                "vol_ratio": None,
            })
        # Same leadership-score formula as the live path (CCI component falls
        # back to the market default 50 — historical CCI is unavailable).
        scores = eng.industry_leadership_scores(rows)
        for row in rows:
            ls = scores.get(row["industry"])
            row["leadership_score"] = ls["leadership_score"] if ls else None
        ranked = sorted(
            (r for r in rows if r["leadership_score"] is not None),
            key=lambda r: r["leadership_score"], reverse=True)
        for i, r in enumerate(ranked):
            r["leadership_rank"] = i + 1
        for r in rows:
            r.setdefault("leadership_rank", None)
            conn.execute(
                """INSERT OR REPLACE INTO industry_snapshot
                   (dt, industry, sector_id, chg_1d, chg_1w, chg_1m, chg_3m, chg_6m,
                    breadth_20, breadth_50, breadth_200, pct_new_highs, vol_ratio,
                    leadership_score, leadership_rank, stocks_count)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (dt, r["industry"], r["sector_id"], r["chg_1d"], r["chg_1w"],
                 r["chg_1m"], r["chg_3m"], r["chg_6m"], r["breadth_20"],
                 r["breadth_50"], r["breadth_200"], r["pct_new_highs"],
                 r["vol_ratio"], r["leadership_score"], r["leadership_rank"],
                 r["stock_count"]),
            )
            written += 1
        conn.commit()
        log(f"Backfill: {dt} — {len(rows)} industry snapshots")

    conn.close()
    log(f"Backfill complete: {written} snapshot rows across {len(trading_days)} days.")
    return {"ok": True, "dates": len(trading_days), "rows_written": written,
            "first_dt": trading_days[0], "last_dt": trading_days[-1]}


def industry_history_needs_backfill():
    """True when industry_snapshot has fewer than 2 distinct dates (rotation
    deltas and the breadth timeline are blank until history exists)."""
    try:
        conn = _mk_conn()
        n = conn.execute("SELECT COUNT(DISTINCT dt) FROM industry_snapshot").fetchone()[0]
        conn.close()
        return n < 2
    except Exception:
        return False
