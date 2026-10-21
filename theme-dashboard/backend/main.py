import os
import json
import time
import threading
import functools
import statistics
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Body, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

import engine
from engine import _mk_conn, MIN_MARKET_CAP_MUSD, MIN_AVG_VOLUME, MIN_ADR_PCT, MIN_PRICE, SECTOR_DEFS, BENCHMARK_TICKER, CCI_RATING_SCORE

# Universal stock filters applied everywhere a stock is listed or ranked:
# market cap >= $500M, avg 30d volume >= 1M, ADR >= 2%, price >= $3
# (adr_pct rows that predate the column pass through so demo data stays
# usable).
STOCK_FILTER_SQL = """market_cap_musd >= ? AND avg_volume >= ?
                      AND (adr_pct IS NULL OR adr_pct >= ?)
                      AND price >= ?"""
STOCK_FILTER_PARAMS = (MIN_MARKET_CAP_MUSD, MIN_AVG_VOLUME, MIN_ADR_PCT, MIN_PRICE)

app = FastAPI(title="Sector Rotation Scanner")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
# Compress API payloads — the dashboard/screener responses are ~1 MB of JSON.
app.add_middleware(GZipMiddleware, minimum_size=5000)

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")


# ---------------------------------------------------------------------------
# Read-response cache: heavy GET endpoints (dashboard, screener, industries)
# recompute the same aggregation on every page navigation. The data only
# changes on sync/refresh/backfill, so cache responses for a short TTL and
# invalidate on any write. This makes repeat page loads near-instant.
# ---------------------------------------------------------------------------
_resp_cache = {}
_resp_cache_lock = threading.Lock()


def cached_get(ttl=60):
    """Cache a GET endpoint's return value for `ttl` seconds, keyed by args."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = (fn.__name__, str(args), str(sorted(kwargs.items())))
            with _resp_cache_lock:
                hit = _resp_cache.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
            val = fn(*args, **kwargs)
            with _resp_cache_lock:
                _resp_cache[key] = (time.time(), val)
            return val
        return wrapper
    return deco


def invalidate_cache():
    with _resp_cache_lock:
        _resp_cache.clear()

_sync_lock = threading.Lock()
_sync_state = {"running": False, "progress": [], "last_report": None}


@app.on_event("startup")
def _startup():
    if not os.path.exists(engine.DB_PATH):
        engine.init_db(force=True)
        engine.generate_universe()
    else:
        engine.init_db(force=False)
    # One-shot historical industry backfill: only when industry_snapshot has
    # < 2 distinct dates (blank rotation deltas / breadth timeline). Once the
    # history exists this check short-circuits and it never runs again.
    import live_data
    if live_data.industry_history_needs_backfill():
        threading.Thread(target=_run_backfill, daemon=True).start()


# Chrome DevTools probes this path on every reload; answer it to keep the log clean.
@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
def _chrome_devtools_probe():
    return {}


@app.post("/api/refresh")
def refresh():
    """Regenerate the synthetic demo universe."""
    engine.init_db(force=True)
    engine.generate_universe()
    conn = _mk_conn()
    conn.execute("UPDATE sync_status SET mode='demo', last_synced=NULL, report_json=NULL WHERE id=1")
    conn.commit()
    conn.close()
    invalidate_cache()
    return {"status": "ok", "refreshed_at": datetime.now().isoformat()}


def _run_sync():
    import live_data
    with _sync_lock:
        _sync_state["running"] = True
        _sync_state["progress"] = []
    try:
        report = live_data.sync_all(progress_cb=lambda msg: _sync_state["progress"].append(msg))
    except Exception as e:
        report = {"ok": False, "error": str(e), "synced_at": datetime.now(timezone.utc).isoformat()}
    conn = _mk_conn()
    conn.execute(
        "UPDATE sync_status SET mode='live', last_synced=?, report_json=? WHERE id=1",
        (report.get("synced_at"), json.dumps(report)),
    )
    conn.commit()
    conn.close()
    invalidate_cache()
    with _sync_lock:
        _sync_state["running"] = False
        _sync_state["last_report"] = report


@app.post("/api/sync")
def start_sync(background_tasks: BackgroundTasks):
    """Kick off a live TradingView sync in the background."""
    with _sync_lock:
        if _sync_state["running"]:
            return {"status": "already_running"}
    background_tasks.add_task(_run_sync)
    return {"status": "started"}


_backfill_lock = threading.Lock()
_backfill_state = {"running": False, "last_report": None}


def _run_backfill():
    import live_data
    with _backfill_lock:
        if _backfill_state["running"]:
            return
        _backfill_state["running"] = True
    try:
        report = live_data.backfill_industry_history(
            progress_cb=lambda msg: _sync_state["progress"].append(msg))
    except Exception as e:
        report = {"ok": False, "error": str(e)}
    invalidate_cache()
    with _backfill_lock:
        _backfill_state["running"] = False
        _backfill_state["last_report"] = report


@app.post("/api/backfill-industry-history")
def start_backfill(background_tasks: BackgroundTasks):
    """Rebuild ~1 month of historical industry_snapshot rows from daily
    prices (yfinance) in the background. Fixes blank Capital Rotation and
    Breadth Timeline on a fresh install."""
    with _backfill_lock:
        if _backfill_state["running"]:
            return {"status": "already_running"}
    background_tasks.add_task(_run_backfill)
    return {"status": "started"}


@app.get("/api/backfill-industry-history/status")
def backfill_status():
    with _backfill_lock:
        return {"running": _backfill_state["running"],
                "last_report": _backfill_state["last_report"]}


@app.get("/api/sync/status")
def sync_status():
    conn = _mk_conn()
    row = conn.execute("SELECT * FROM sync_status WHERE id=1").fetchone()
    conn.close()
    with _sync_lock:
        running = _sync_state["running"]
        progress = list(_sync_state["progress"][-20:])
    return {
        "running": running,
        "progress_log": progress,
        "mode": row["mode"] if row else "demo",
        "last_synced": row["last_synced"] if row else None,
        "report": json.loads(row["report_json"]) if row and row["report_json"] else None,
    }


@app.get("/api/config")
def get_config():
    return {
        "min_market_cap_musd": MIN_MARKET_CAP_MUSD,
        "min_avg_volume": MIN_AVG_VOLUME,
        "min_adr_pct": MIN_ADR_PCT,
        "min_price": MIN_PRICE,
        "benchmark": BENCHMARK_TICKER,
    }


# ---------------------------------------------------------------------------
# Strategy helpers — one shell, one engine (Qullamaggie); sector ranking is
# CCI-based (50% performance + 50% CCI)
# ---------------------------------------------------------------------------

def _norm_strategy(strategy):
    return strategy if strategy in engine.STRATEGY_DEFS else engine.STRATEGY_DEFAULT


def _strategy_context(conn, strategy):
    """Compute per-strategy sector scores + states for the latest snapshot.

    Returns {"strategy", "label", "cci_factor", "scores": {sid: score},
    "states": {sid: state}, "base": {sid: pre-CCI strategy score}}."""
    strategy = _norm_strategy(strategy)
    cci = engine.cci_market_factor(conn)
    # Sector CCI: CCI(34) of each sector's proxy ETF (SECTOR_ETF_MAP) — the
    # compulsory CCI input for the strategy sector scores; sectors without an
    # ETF CCI value fall back to the market-wide factor.
    cci_by_sector = engine.sector_cci_factors(conn)
    stats = []
    prev_scores = {}
    rows = conn.execute(
        "SELECT id AS sector_id FROM sector ORDER BY id"
    ).fetchall()
    for r in rows:
        sid = r["sector_id"]
        hist = conn.execute(
            "SELECT * FROM sector_snapshot WHERE sector_id=? ORDER BY dt ASC", (sid,)
        ).fetchall()
        if not hist:
            continue
        snap = hist[-1]
        stats.append({
            "sector_id": sid,
            "perf_1w": snap["chg_1w"], "perf_1m": snap["chg_1m"],
            "perf_3m": snap["chg_3m"], "perf_6m": snap["chg_6m"],
            "breadth": snap["breadth_pct_above_50ma"],
            "rs_vs_spy": snap["rs_vs_spy_1m"],
            "pct_new_highs": snap["pct_new_highs"],
            "avg_vol_ratio": snap["avg_volume_ratio"],
            "concentration": snap["concentration_index"],
            "etf_pct_from_52w_high": snap["etf_pct_from_52w_high"],
            "ema10_above_20": snap["ema10_above_20"],
            "above_50ema": snap["above_50ema"],
            "avg_rs": snap["avg_rs_rating"],
        })
        if len(hist) >= 6:
            prev_scores[sid] = (snap["score"] or 0) - (hist[-6]["score"] or 0)
    scores = engine.strategy_sector_scores(stats, strategy, cci, cci_by_sector)
    # pre-CCI component for the composite-factor display: the normalized
    # performance score (15% 1W / 50% 1M / 35% 3M, min-max normalized 0-100)
    base = engine.sector_performance_scores(stats)
    states = {}
    for st in stats:
        sid = st["sector_id"]
        vel = prev_scores.get(sid, 0)
        states[sid] = engine.classify_sector_state_strategy(
            scores.get(sid, 0), st["breadth"], st["avg_rs"],
            scores.get(sid, 0) - vel, strategy)
    return {
        "strategy": strategy,
        "label": engine.STRATEGY_DEFS[strategy]["label"],
        "cci_factor": cci,
        "cci_by_sector": cci_by_sector,
        "scores": scores,
        "states": states,
        "base": base,
    }


# ---------------------------------------------------------------------------
# Sector helpers
# ---------------------------------------------------------------------------

def _sector_holdings_ranked(sector_id, conn, strategy=engine.STRATEGY_DEFAULT, cci_factor=50.0):
    etfs = conn.execute("SELECT * FROM etf WHERE sector_id=?", (sector_id,)).fetchall()
    all_ranked = {}
    for etf in etfs:
        rows = conn.execute(
            """SELECT h.stock_ticker, h.weight_pct, h.etf_ticker, s.*
               FROM holding h JOIN stock s ON s.ticker = h.stock_ticker
               WHERE h.etf_ticker=?""",
            (etf["ticker"],),
        ).fetchall()
        merged = [dict(r) for r in rows]
        ranked, excluded = engine.score_and_rank(merged, strategy, cci_factor)
        all_ranked[etf["ticker"]] = {
            "etf": dict(etf),
            "holdings": ranked,
            "excluded_count": excluded,
            "total_holdings": len(merged),
        }
    return all_ranked


def _latest_sector_snapshot(sector_id, conn):
    return conn.execute(
        "SELECT * FROM sector_snapshot WHERE sector_id=? ORDER BY dt DESC LIMIT 1", (sector_id,)
    ).fetchone()


def _sector_history(sector_id, conn):
    return conn.execute(
        "SELECT * FROM sector_snapshot WHERE sector_id=? ORDER BY dt ASC", (sector_id,)
    ).fetchall()


def _style_for(sub):
    return "defensive" if sub == "Defensive" else "offensive"


def _score_delta_5d(history):
    if len(history) >= 6:
        return round((history[-1]["score"] or 0) - (history[-6]["score"] or 0), 1)
    return 0


def _rs_trend_5d(history):
    if len(history) >= 6:
        return round((history[-1]["avg_rs_rating"] or 0) - (history[-6]["avg_rs_rating"] or 0), 1)
    return 0


def _rank_delta(sector_id, conn):
    """Rank by score 5 snapshots ago minus rank today (positive = moved up)."""
    dts = [r[0] for r in conn.execute(
        "SELECT DISTINCT dt FROM sector_snapshot ORDER BY dt DESC LIMIT 6"
    ).fetchall()]
    if len(dts) < 6:
        return 0

    def rank_at(dt):
        rows = conn.execute(
            "SELECT sector_id, score FROM sector_snapshot WHERE dt=?", (dt,)
        ).fetchall()
        ordered = sorted(rows, key=lambda r: (r["score"] or 0), reverse=True)
        for i, r in enumerate(ordered):
            if r["sector_id"] == sector_id:
                return i + 1
        return None

    rank_now = rank_at(dts[0])
    rank_prev = rank_at(dts[-1])
    if rank_now is None or rank_prev is None:
        return 0
    return rank_prev - rank_now


def _lin_slope(vals):
    """Least-squares slope (units per step) of a short series."""
    n = len(vals)
    if n < 2:
        return 0.0
    mx = (n - 1) / 2
    my = sum(vals) / n
    num = sum((i - mx) * (v - my) for i, v in enumerate(vals))
    den = sum((i - mx) ** 2 for i in range(n)) or 1
    return num / den


def _daily_returns(prices):
    return [
        (prices[i] / prices[i - 1] - 1) * 100
        for i in range(1, len(prices))
        if prices[i - 1]
    ]


def _command_metrics(history, holdings):
    """Derived command-center metrics for one sector (per-sector only).

    Works off the snapshot history and the ranked primary-ETF holdings, so it
    is valid in both demo and live modes."""
    cmd = {}
    if holdings:
        n = len(holdings)
        cmd["breadth_20"] = round(sum(1 for h in holdings if h.get("above_20d")) / n * 100, 1)
        cmd["breadth_50"] = round(sum(1 for h in holdings if h.get("above_50d")) / n * 100, 1)
        cmd["breadth_200"] = round(sum(1 for h in holdings if h.get("above_200d")) / n * 100, 1)
        cmd["breakouts"] = sum(1 for h in holdings if (h.get("pct_from_52w_high") or -100) >= -3)
        cmd["breakdowns"] = sum(1 for h in holdings if (h.get("pct_from_52w_low") or 100) <= 3)
    prices = [r["price"] for r in history if r["price"]]
    rets = _daily_returns(prices)
    cmd["atr_pct"] = round(sum(abs(r) for r in rets[-14:]) / len(rets[-14:]), 2) if rets else None
    cmd["realized_vol"] = round(statistics.pstdev(rets[-30:]) * (252 ** 0.5), 1) if len(rets) >= 5 else None
    ph = [r["etf_pct_from_52w_high"] for r in history[-20:] if r["etf_pct_from_52w_high"] is not None]
    cmd["drawdown"] = round(min(ph), 1) if ph else None
    if prices:
        pivot = max(prices[-20:])
        cmd["dist_pivot"] = round((prices[-1] / pivot - 1) * 100, 1) if pivot else None
    rs = [r["avg_rs_rating"] for r in history[-10:] if r["avg_rs_rating"] is not None]
    cmd["rs_slope"] = round(_lin_slope(rs), 2) if rs else None
    return cmd


def _sector_summary(sector_id, conn, strategy=None, sctx=None):
    s = conn.execute("SELECT * FROM sector WHERE id=?", (sector_id,)).fetchone()
    if not s:
        return None
    if strategy is not None:
        strategy = _norm_strategy(strategy)
    snap = _latest_sector_snapshot(sector_id, conn)
    history = _sector_history(sector_id, conn)
    etfs = conn.execute("SELECT ticker FROM etf WHERE sector_id=?", (sector_id,)).fetchall()
    primary_ticker = etfs[0]["ticker"] if etfs else None
    cci = (sctx or {}).get("cci_factor", 50.0)
    ranked_by_etf = _sector_holdings_ranked(
        sector_id, conn, strategy or engine.STRATEGY_DEFAULT, cci)
    primary_holdings = ranked_by_etf.get(primary_ticker, {}).get("holdings", []) if primary_ticker else []
    conc = engine.concentration_index(primary_holdings) if primary_holdings else None
    rotation_score = None
    if snap and primary_holdings:
        dispersion = statistics.pstdev([r["chg_1m"] for r in primary_holdings]) if len(primary_holdings) > 1 else 0
        rotation_score = engine.rotation_health_score(
            snap["breadth_pct_above_50ma"], conc or 0, dispersion, snap["avg_rs_rating"]
        )
    snap_dict = dict(snap) if snap else None
    strategy_info = None
    if strategy is not None and snap_dict:
        if sctx is None:
            sctx = _strategy_context(conn, strategy)
        sid = s["id"]
        # The CCI input shown for a sector is that sector's ETF CCI (sector
        # CCI), falling back to the market-wide factor when unavailable.
        sector_cci = (sctx.get("cci_by_sector") or {}).get(sid, sctx["cci_factor"])
        # Preserve the canonical (strategy-agnostic) values so the universal
        # Markets layer can keep showing them on every dashboard.
        snap_dict["canonical_score"] = snap_dict.get("score")
        snap_dict["canonical_state"] = snap_dict.get("state")
        snap_dict["score"] = sctx["scores"].get(sid, snap_dict.get("score"))
        snap_dict["state"] = sctx["states"].get(sid, snap_dict.get("state"))
        strategy_info = {
            "strategy": sctx["strategy"],
            "label": sctx["label"],
            "composite_score": sctx["scores"].get(sid),
            "composite_base": (sctx["base"] or {}).get(sid),
            "cci_factor": sector_cci,
            "factors": {
                "performance": round((sctx["base"] or {}).get(sid, 0), 1),
                "cci": sector_cci,
            },
        }
    return {
        "id": s["id"],
        "name": s["name"],
        "ticker": s["ticker"],
        "sub": s["sub"],
        "tags": s["tags"],
        "color": s["color"],
        "conviction": s["conviction"],
        "notes": s["notes"],
        "latest_snapshot": snap_dict,
        "strategy_info": strategy_info,
        "history": [dict(r) for r in history],
        "primary_etf": primary_ticker,
        "proxy_etf": engine.SECTOR_ETF_MAP.get(s["name"]),
        "concentration_index": conc,
        "rotation_health_score": rotation_score,
        "style": _style_for(s["sub"]),
        "score_delta_5d": _score_delta_5d(history),
        "rs_trend": _rs_trend_5d(history),
        "rank_delta": _rank_delta(s["id"], conn),
        "command": _command_metrics(history, primary_holdings),
        "excluded_summary": {
            k: {"excluded": v["excluded_count"], "total": v["total_holdings"]}
            for k, v in ranked_by_etf.items()
        },
    }


# ---------------------------------------------------------------------------
# Industries (TradingView "industry" classification stored on stock.industry)
# ---------------------------------------------------------------------------

def _industry_aggregate(rows):
    """Aggregate one industry's constituent stocks into summary metrics."""
    n = len(rows)

    def avgf(key, digits=2):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), digits) if vals else None

    def pct(cond):
        return round(sum(1 for r in rows if cond(r)) / n * 100, 1)

    def near_high(r):
        d = r.get("dist_high_3m")
        if d is None:
            d = r.get("pct_from_52w_high")
        return d is not None and d >= -5

    return {
        "stock_count": n,
        "avg_chg_1w": avgf("chg_1w"),
        "avg_chg_1m": avgf("chg_1m"),
        "avg_chg_3m": avgf("chg_3m"),
        "avg_chg_6m": avgf("chg_6m"),
        "breadth_20": pct(lambda r: r["above_20d"]),
        "breadth_50": pct(lambda r: r["above_100ema"] if r.get("above_100ema") is not None else r["above_50d"]),
        "breadth_200": pct(lambda r: r["above_200d"]) if any(
            r.get("above_200d") is not None for r in rows) else None,
        "pct_new_highs": pct(near_high),
        "avg_volume_ratio": avgf("volume_ratio"),
        "avg_rs_vs_spy_1m": avgf("rs_vs_spy_1m"),
        "avg_volatility_d": avgf("volatility_d"),
        "avg_recommend_all": avgf("recommend_all"),
    }


def _industry_page_lookup(conn, sector_id=None):
    """Latest exact TradingView industry performance (copied verbatim from
    TradingView's INDUSTRY_US:* symbols during sync), keyed by normalized
    industry name. These are the exact numbers shown on the website."""
    q = """SELECT sector_id, name, chg_1d, chg_1w, chg_1m, chg_3m, chg_6m,
                  market_cap_usd, div_yield_pct, volume, stocks_count
           FROM industry_page
           WHERE dt = (SELECT MAX(dt) FROM industry_page)"""
    params = []
    if sector_id is not None:
        q += " AND sector_id=?"
        params.append(sector_id)
    return {r["name"].strip().lower(): dict(r) for r in conn.execute(q, params).fetchall()}


def _industry_score_deltas(conn):
    """Latest leadership_score minus the score from the most recent previous
    distinct dt in industry_snapshot, per industry. Empty dict when fewer
    than 2 snapshot dates exist (e.g. before the first sync that writes
    industry_snapshot rows)."""
    try:
        dts = [r[0] for r in conn.execute(
            "SELECT DISTINCT dt FROM industry_snapshot ORDER BY dt DESC LIMIT 2").fetchall()]
    except Exception:
        return {}
    if len(dts) < 2:
        return {}
    latest, prev = dts
    cur = {r["industry"]: r["leadership_score"] for r in conn.execute(
        "SELECT industry, leadership_score FROM industry_snapshot WHERE dt=?", (latest,)).fetchall()}
    old = {r["industry"]: r["leadership_score"] for r in conn.execute(
        "SELECT industry, leadership_score FROM industry_snapshot WHERE dt=?", (prev,)).fetchall()}
    out = {}
    for name, score in cur.items():
        p = old.get(name)
        if score is not None and p is not None:
            out[name] = round(score - p, 1)
    return out


def _industry_state(row):
    """Legacy fallback rotation state for industries not covered by the
    leaderboard (fewer than IND_MIN_STOCKS stocks). Leaderboard-covered
    industries get their Leading/Emerging/Fading/Lagging/Recovering state
    from engine.industry_leaderboard_scores instead."""
    delta = row.get("score_delta")
    score = row.get("leadership_score")
    if delta is not None and delta >= 3:
        return "Emerging"
    if delta is not None and delta <= -3:
        return "Fading"
    if score is not None and score >= 70:
        return "Leading"
    if score is not None and score <= 30:
        return "Lagging"
    return "Neutral"


def _enrich_industry_rows(conn, out, cci_factor):
    """Attach sector identity, benchmark ETF, CCI and the industry leadership
    score to each industry row. Every industry with >= 3 stocks gets a
    leadership score: > 25 stocks -> 65% performance + 35% CCI (benchmark
    chart enabled); <= 25 stocks -> performance only (1M > 3M > 1W). The
    benchmark is a dedicated industry ETF (INDUSTRY_ETF_MAP) or, when none
    exists, an equal-weight custom index of the top members by market cap —
    never a broad parent-sector ETF."""
    ind_cci = engine.industry_cci_factors(conn)
    sector_cci = engine.sector_cci_factors(conn)
    sector_names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM sector").fetchall()}
    for row in out:
        members = row.pop("_members", [])
        sids = [m.get("sector_id") for m in members if m.get("sector_id") is not None]
        sid = max(set(sids), key=sids.count) if sids else None
        row["sector_id"] = sid
        row["sector_name"] = sector_names.get(sid)
    scores = engine.industry_leadership_scores(
        out, ind_cci, sector_cci, cci_factor)
    for row in out:
        ls = scores.get(row["industry"])
        if not ls:
            row["leadership_score"] = None
            # Even unscored (<3 stocks) industries display their dedicated
            # ETF as benchmark when one is mapped.
            row["benchmark_etf"] = engine.INDUSTRY_ETF_MAP.get(row["industry"])
            row["benchmark_kind"] = "etf" if row["benchmark_etf"] else None
            continue
        row.update(ls)
        # No sector-ETF fallback: industries without a dedicated ETF in
        # INDUSTRY_ETF_MAP get an equal-weight custom index of their top
        # market-cap members (see _industry_tv_symbol).
        row["benchmark_kind"] = ("etf" if ls["benchmark_etf"] else
                                 "custom" if (row.get("stock_count") or 0) >= engine.IND_MIN_STOCKS
                                 else None)
        ic = ind_cci.get(row["industry"])
        if ic:
            row["cci_rating"] = ic["rating"]
            row["cci34"] = ic["cci34"]
            row["cci_ema"] = ic["cci_ema"]
    # Rank across all scored industries (1 = strongest).
    ranked = sorted(
        (r for r in out if r.get("leadership_score") is not None),
        key=lambda r: r["leadership_score"], reverse=True)
    for i, r in enumerate(ranked):
        r["leadership_rank"] = i + 1
    return out


def _industry_rows(conn, sector_id=None, strategy=None, cci_factor=50.0):
    """Group filtered stocks by industry and aggregate; when a strategy is
    given, each industry's stocks are scored with that strategy's composite
    and industries are ranked by their average strategy score (best industry
    first). The displayed 1D/1W/1M/3M/6M performance is TradingView's exact
    published value (tv_* fields, copied verbatim during sync); breadth/
    new-highs/etc. are computed from the filtered stock universe."""
    q = f"""SELECT * FROM stock
           WHERE ticker != ? AND industry IS NOT NULL AND industry != ''
             AND {STOCK_FILTER_SQL}"""
    params = [BENCHMARK_TICKER, *STOCK_FILTER_PARAMS]
    if sector_id is not None:
        q += " AND sector_id=?"
        params.append(sector_id)
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    by_industry = {}
    for r in rows:
        by_industry.setdefault(r["industry"], []).append(r)
    out = [{"industry": name, "_members": members, **_industry_aggregate(members)}
           for name, members in by_industry.items()]
    if strategy is not None:
        strategy = _norm_strategy(strategy)
        for row in out:
            members = row["_members"]
            ranked, _ = engine.score_and_rank(members, strategy, cci_factor)
            row["strategy_score"] = (
                round(sum(m["score"] for m in ranked) / len(ranked), 1) if ranked else None
            )
            row["strategy_leaders"] = sum(1 for m in ranked if m.get("classification") == "leader")
    page = _industry_page_lookup(conn, sector_id)
    for row in out:
        p = page.get(row["industry"].strip().lower())
        if p:
            for k in ("chg_1d", "chg_1w", "chg_1m", "chg_3m", "chg_6m"):
                row["tv_" + k] = p[k]
            row["tv_market_cap_usd"] = p["market_cap_usd"]
            row["tv_div_yield_pct"] = p["div_yield_pct"]
            row["tv_volume"] = p["volume"]
            row["tv_stocks_count"] = p["stocks_count"]
        # Displayed performance: TradingView exact when available, else the
        # filtered-universe average. Breadth metrics stay computed.
        row["chg_1d"] = row.get("tv_chg_1d")
        row["chg_1w"] = row.get("tv_chg_1w") if row.get("tv_chg_1w") is not None else row["avg_chg_1w"]
        row["chg_1m"] = row.get("tv_chg_1m") if row.get("tv_chg_1m") is not None else row["avg_chg_1m"]
        row["chg_3m"] = row.get("tv_chg_3m") if row.get("tv_chg_3m") is not None else row["avg_chg_3m"]
        row["chg_6m"] = row.get("tv_chg_6m") if row.get("tv_chg_6m") is not None else row["avg_chg_6m"]
    _enrich_industry_rows(conn, out, cci_factor)
    if strategy is not None:
        out.sort(key=lambda x: (x["strategy_score"] is not None, x["strategy_score"] or 0), reverse=True)
    else:
        out.sort(key=lambda x: (x["leadership_score"] is not None, x["leadership_score"] or 0), reverse=True)
    return out


@app.get("/api/industries")
def list_industries(strategy: str = None):
    """All industries across the filtered universe. Each row carries the
    two-stage leaderboard fields (leadership_score, opportunity_score, state,
    status, confidence, reasons, rank changes, score breakdown) from
    engine.industry_leaderboard_scores when the industry qualifies."""
    conn = _mk_conn()
    cci = engine.cci_market_factor(conn)
    out = _industry_rows(conn, strategy=strategy, cci_factor=cci)
    deltas = _industry_score_deltas(conn)
    try:
        board = engine.industry_leaderboard_scores(conn)
    except Exception:
        board = None
    conn.close()
    by_name = {r["industry"]: r for r in (board or {}).get("rows", [])}
    merge_keys = ("leadership_score", "opportunity_score", "state", "status",
                  "confidence", "reasons", "actionable_score",
                  "leadership_rank", "opportunity_rank", "rotation_rank",
                  "risk_rank", "risk_score", "rank_chg_5d", "rank_chg_20d",
                  "score_chg_5d", "breakdown", "components", "rs",
                  "ext_ema20", "ext_ema50")
    for row in out:
        row["score_delta"] = deltas.get(row["industry"])
        lb = by_name.get(row["industry"])
        if lb:
            for k in merge_keys:
                row[k] = lb.get(k)
        else:
            row["state"] = _industry_state(row)
    if strategy is None:
        out.sort(key=lambda x: (x["leadership_score"] is not None,
                                x["leadership_score"] or 0), reverse=True)
    return out


@app.get("/api/leaderboards")
@cached_get(ttl=60)
def leaderboards(profile: str = None):
    """Industry Scores page: the two-stage 100-point industry ranking —
    eligibility status gate + Leadership Score with percentile-ranked
    components, multiple rank lists and the Actionable Now list (see
    engine.industry_leaderboard_scores). `profile` selects the weight profile
    (swing / position / early_rotation)."""
    conn = _mk_conn()
    try:
        return engine.industry_leaderboard_scores(
            conn, profile=profile or engine.LEAD_PROFILE_DEFAULT)
    finally:
        conn.close()


@app.get("/api/industries/{industry_name}/stocks")
def industry_stocks(industry_name: str, strategy: str = None):
    """Constituent stocks of one industry, scored and ranked by the selected
    strategy. NOTE: names containing "/" cannot be passed as a path segment —
    use the /api/industry-stocks?name= variant for those."""
    return _industry_stocks(industry_name, strategy)


@app.get("/api/industry-stocks")
def industry_stocks_by_query(name: str, strategy: str = None):
    """Query-param variant of /api/industries/{name}/stocks that also works
    for industry names containing slashes (e.g. 'Oil Refining/Marketing')."""
    return _industry_stocks(name, strategy)


@app.get("/api/industry-symbol")
def industry_symbol(name: str):
    """TradingView benchmark for charting an industry:
    - kind "etf": a dedicated industry ETF from INDUSTRY_ETF_MAP
      (exchange-prefixed: AMEX: by default, NASDAQ:/CBOE: per ETF_EXCHANGE).
      Never a broad parent-sector ETF.
    - kind "custom_index": an equal-weight TradingView arithmetic expression
      over the industry's top INDUSTRY_CUSTOM_INDEX_SIZE members by market
      cap (e.g. "AAPL/5+MSFT/5+NVDA/5+AVGO/5+CRM/5").
    - kind "none": fewer than 3 stocks — nothing sensible to chart."""
    conn = _mk_conn()
    out = _industry_tv_symbol(conn, name)
    conn.close()
    return out


# Listing exchange for the benchmark ETFs used in charts. TradingView quotes
# NYSE Arca ETFs under "AMEX:"; anything not listed here defaults to AMEX.
# The overrides below were verified against the TradingView scanner
# (scanner.tradingview.com/america/scan): the exchange prefix is the FIRST of
# AMEX -> NASDAQ -> NYSE -> CBOE that returns a live quote whose fund
# description matches the ETF. Verified 2026-10 (IHF, MOO, SLX, IPAY, IHI
# resolve under AMEX; SMH/QQQ/PPH under NASDAQ; iShares' IGV/ITA/IYZ only
# resolve under CBOE).
ETF_EXCHANGE = {
    "AIRR": "NASDAQ", "CARZ": "NASDAQ", "IBB": "NASDAQ", "PPH": "NASDAQ",
    "QCLN": "NASDAQ", "QQQ": "NASDAQ", "SMH": "NASDAQ", "SOXX": "NASDAQ",
    "WOOD": "NASDAQ",
    "IGV": "CBOE", "ITA": "CBOE", "IYZ": "CBOE",
}


def _industry_tv_symbol(conn, name):
    """Resolve an industry's chart benchmark per the rules on
    INDUSTRY_ETF_MAP: dedicated industry ETF first, otherwise an
    equal-weight custom index of the top members by market cap."""
    etf = engine.INDUSTRY_ETF_MAP.get(name)
    if etf:
        return {"symbol": ETF_EXCHANGE.get(etf, "AMEX") + ":" + etf,
                "kind": "etf", "benchmark": etf}
    members = [r[0] for r in conn.execute(
        f"""SELECT ticker FROM stock
            WHERE industry = ? AND ticker != ? AND {STOCK_FILTER_SQL}
            ORDER BY market_cap_musd DESC LIMIT ?""",
        (name, BENCHMARK_TICKER, *STOCK_FILTER_PARAMS,
         engine.INDUSTRY_CUSTOM_INDEX_SIZE)).fetchall()]
    if len(members) >= engine.IND_MIN_STOCKS:
        n = len(members)
        expr = "+".join(f"{t}/{n}" for t in members)
        return {"symbol": expr, "kind": "custom_index", "members": members,
                "benchmark": "Custom EW-%d" % n}
    return {"symbol": None, "kind": "none", "benchmark": None}


@app.get("/api/industry-benchmark-emas")
def industry_benchmark_emas(name: str):
    """EMA readout (5/10/20/50/200) + price for an industry's benchmark.

    - ETF benchmark: live values from the TradingView scanner.
    - Custom index: equal-weight average of the members' EMAs/prices stored
      in the stock table (EMA is a linear operator, so the EMA of an
      equal-weight basket is the average of the member EMAs). No network
      call, so it works in demo mode too.
    """
    import live_data
    conn = _mk_conn()
    tv = _industry_tv_symbol(conn, name)
    if tv["kind"] == "etf":
        conn.close()
        data = live_data.fetch_symbol_emas(tv["benchmark"])
        if not data:
            raise HTTPException(404, "no EMA data for benchmark ETF")
        data["kind"] = "etf"
        data["benchmark"] = tv["benchmark"]
        return data
    if tv["kind"] == "custom_index":
        members = tv["members"]
        marks = ",".join("?" * len(members))
        rows = conn.execute(
            f"""SELECT price, ema5, ema10, ema20, ema50, ema200 FROM stock
                WHERE ticker IN ({marks})""", members).fetchall()
        conn.close()

        def avgf(col):
            vals = [r[col] for r in rows if r[col] is not None]
            return round(sum(vals) / len(vals), 2) if vals else None

        data = {
            "symbol": tv["symbol"], "kind": "custom_index",
            "benchmark": tv["benchmark"], "members": members,
            "price": avgf("price"),
            "ema5": avgf("ema5"), "ema10": avgf("ema10"),
            "ema20": avgf("ema20"), "ema50": avgf("ema50"),
            "ema200": avgf("ema200"),
        }
        if data["price"] is None:
            raise HTTPException(404, "no member data for custom index")
        return data
    conn.close()
    raise HTTPException(404, "industry has no benchmark")


@app.get("/api/industry-detail")
def industry_detail(name: str):
    """Everything the industry-analysis page needs in one payload: parent
    sector identity, aggregate metrics, the industry benchmark (a dedicated
    industry ETF, or an equal-weight custom index of the top members by
    market cap — never a broad sector ETF), the industry CCI(34) readout and
    the industry leadership score/rank (65% performance + 35% CCI for >25
    stocks, performance-only 1M>3M>1W otherwise; every industry with >= 3
    stocks is ranked)."""
    conn = _mk_conn()
    cci = engine.cci_market_factor(conn)
    rows = _industry_rows(conn, cci_factor=cci)
    row = next((r for r in rows if r["industry"] == name), None)
    if not row:
        conn.close()
        raise HTTPException(404, "industry not found")
    history = [dict(r) for r in conn.execute(
        """SELECT dt, breadth_20, breadth_50, breadth_200, chg_1w, chg_1m,
                  leadership_score AS score
           FROM (
               SELECT * FROM industry_snapshot
               WHERE industry=? ORDER BY dt DESC LIMIT 90
           ) ORDER BY dt ASC""",
        (name,)).fetchall()]
    row["tv_symbol"] = _industry_tv_symbol(conn, name)
    conn.close()
    row["history"] = history
    row["market_cci_factor"] = cci
    return row


def _industry_stocks(industry_name, strategy=None):
    conn = _mk_conn()
    cci = engine.cci_market_factor(conn)
    rows = conn.execute(
        f"""SELECT s.*, sec.name AS sector_name, sec.color AS sector_color
           FROM stock s LEFT JOIN sector sec ON sec.id = s.sector_id
           WHERE s.industry = ?
             AND s.market_cap_musd >= ? AND s.avg_volume >= ?
             AND (s.adr_pct IS NULL OR s.adr_pct >= ?)
             AND s.price >= ?""",
        (industry_name, *STOCK_FILTER_PARAMS),
    ).fetchall()
    conn.close()
    merged = [dict(r) for r in rows]
    if strategy is not None:
        ranked, _ = engine.score_and_rank(merged, strategy, cci)
        return ranked
    merged.sort(key=lambda r: (r["chg_3m"] is not None, r["chg_3m"] or 0), reverse=True)
    return merged


@app.get("/api/sectors/{sector_id}/industries")
def sector_industries(sector_id: int, strategy: str = None):
    """Industries within one sector, aggregated like /api/industries."""
    conn = _mk_conn()
    if not conn.execute("SELECT 1 FROM sector WHERE id=?", (sector_id,)).fetchone():
        conn.close()
        raise HTTPException(404, "sector not found")
    cci = engine.cci_market_factor(conn)
    out = _industry_rows(conn, sector_id, strategy=strategy, cci_factor=cci)
    conn.close()
    return out


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.get("/api/strategies")
def list_strategies():
    """The strategy dashboard available inside the shared app shell."""
    return {
        "default": engine.STRATEGY_DEFAULT,
        "strategies": [
            {"id": k, "label": v["label"]} for k, v in engine.STRATEGY_DEFS.items()
        ],
    }


@app.get("/api/etf-emas")
def etf_emas(symbol: str):
    """EMA readout (5/10/20/50/200) for an ETF symbol, from the TradingView
    scanner. Used by the Charts pages below each chart."""
    import live_data
    symbol = symbol.strip().upper()
    if not symbol or len(symbol) > 12:
        raise HTTPException(400, "invalid symbol")
    data = live_data.fetch_symbol_emas(symbol)
    if not data:
        raise HTTPException(404, "no EMA data for symbol")
    return data


@app.get("/api/sectors")
def list_sectors(strategy: str = None):
    conn = _mk_conn()
    sctx = _strategy_context(conn, strategy) if strategy is not None else None
    sectors = conn.execute("SELECT * FROM sector ORDER BY id").fetchall()
    out = []
    for s in sectors:
        out.append(_sector_summary(s["id"], conn, strategy, sctx))
    conn.close()
    return out


@app.get("/api/sectors/{sector_id}")
def sector_detail(sector_id: int, strategy: str = None):
    conn = _mk_conn()
    strategy = _norm_strategy(strategy)
    sctx = _strategy_context(conn, strategy)
    summary = _sector_summary(sector_id, conn, strategy, sctx)
    if not summary:
        conn.close()
        raise HTTPException(404, "sector not found")
    ranked_by_etf = _sector_holdings_ranked(sector_id, conn, strategy, sctx["cci_factor"])
    etfs = conn.execute("SELECT * FROM etf WHERE sector_id=?", (sector_id,)).fetchall()
    conn.close()
    return {
        **summary,
        "etfs": [dict(e) for e in etfs],
        "holdings_by_etf": ranked_by_etf,
    }


@app.get("/api/sectors/{sector_id}/stocks")
def sector_stocks(sector_id: int, classification: str = None, strategy: str = None):
    """EVERY stock in the sector passing the universal filters, scored with
    the selected strategy's composite (CCI compulsory) and ranked 1..N
    (rank 1 = highest score, ties broken by ticker so the order is stable).
    Optionally filtered by leader/laggard/neutral."""
    conn = _mk_conn()
    cci = engine.cci_market_factor(conn)
    rows = conn.execute(
        f"""SELECT s.*, sec.name AS sector_name, sec.color AS sector_color
           FROM stock s LEFT JOIN sector sec ON sec.id = s.sector_id
           WHERE s.sector_id = ? AND s.ticker != ?
             AND s.market_cap_musd >= ? AND s.avg_volume >= ?
             AND (s.adr_pct IS NULL OR s.adr_pct >= ?)
             AND s.price >= ?""",
        (sector_id, BENCHMARK_TICKER, *STOCK_FILTER_PARAMS),
    ).fetchall()
    conn.close()
    merged = []
    for r in rows:
        d = dict(r)
        d["stock_ticker"] = d["ticker"]  # score_and_rank / frontend compat
        merged.append(d)
    ranked, _ = engine.score_and_rank(merged, _norm_strategy(strategy), cci)
    # score_and_rank already orders by (-score, ticker) and assigns rank 1..N
    if classification:
        ranked = [r for r in ranked if r["classification"] == classification]
    return ranked


@app.get("/api/screener")
def screener(strategy: str = None):
    """Every stock in the universe passing the universal scanner filters
    (market cap >= $500M, avg 30d volume >= 1M, ADR >= 2%), scored with the
    selected strategy's composite (CCI compulsory) and sorted by it, plus 3M
    and 6M rankings (rank 1 = strongest). The benchmark ticker is excluded."""
    conn = _mk_conn()
    cci = engine.cci_market_factor(conn)
    rows = conn.execute(
        f"""SELECT s.*, sec.name AS sector_name, sec.color AS sector_color
           FROM stock s LEFT JOIN sector sec ON sec.id = s.sector_id
           WHERE s.ticker != ?
             AND s.market_cap_musd >= ? AND s.avg_volume >= ?
             AND (s.adr_pct IS NULL OR s.adr_pct >= ?)
             AND s.price >= ?""",
        (BENCHMARK_TICKER, *STOCK_FILTER_PARAMS),
    ).fetchall()
    conn.close()
    stocks = [dict(r) for r in rows]
    strategy = _norm_strategy(strategy)
    stocks, _ = engine.score_and_rank(stocks, strategy, cci)

    def add_rank(field, out_field):
        ordered = sorted(stocks, key=lambda x: (x.get(field) is not None, x.get(field) or 0), reverse=True)
        for i, s in enumerate(ordered):
            s[out_field] = i + 1 if s.get(field) is not None else None

    add_rank("chg_3m", "rank_3m")
    add_rank("chg_6m", "rank_6m")
    # score_and_rank already ordered by the strategy composite; keep that order
    return {
        "count": len(stocks),
        "strategy": strategy,
        "filters": {
            "min_market_cap_musd": MIN_MARKET_CAP_MUSD,
            "min_avg_volume": MIN_AVG_VOLUME,
            "min_adr_pct": MIN_ADR_PCT,
        },
        "stocks": stocks,
    }


# Short-TTL cache for live index quotes so a page full of index cards does
# not hit the TradingView scanners on every request.
_index_quote_cache = {"at": 0.0, "data": {}}
_INDEX_QUOTE_TTL = 60  # seconds


def _overlay_live_index_quotes(indices):
    """Replace the stale sync-time price/return fields on index_cci rows with
    live TradingView quotes (CCI/rating stay sync-computed — they intentionally
    use closed daily bars). Falls back to the stored numbers on any failure."""
    now = time.time()
    if now - _index_quote_cache["at"] >= _INDEX_QUOTE_TTL:
        try:
            from live_data import fetch_index_quotes
            data = fetch_index_quotes()
            if data:
                _index_quote_cache["data"] = data
                _index_quote_cache["at"] = now
        except Exception:
            _index_quote_cache["at"] = now  # don't hammer a failing endpoint
    live = _index_quote_cache["data"]
    for idx in indices:
        q = live.get(idx.get("ticker"))
        if not q:
            continue
        for key in ("price", "chg_1d", "chg_1w", "chg_1m", "chg_3m", "chg_ytd", "chg_1y"):
            if q.get(key) is not None:
                idx[key] = q[key]
        idx["live"] = True


@app.get("/api/dashboard")
def dashboard(strategy: str = None):
    """High-level summary: leaders, emerging, fading, lagging, market summary.
    The Markets layer (market_summary, index CCI) is universal and identical
    across strategies; sector scores/states/rankings are strategy-specific."""
    conn = _mk_conn()
    strategy = _norm_strategy(strategy)
    sctx = _strategy_context(conn, strategy)
    status_row = conn.execute("SELECT * FROM sync_status WHERE id=1").fetchone()
    sectors = conn.execute("SELECT * FROM sector ORDER BY id").fetchall()
    summaries = []
    for s in sectors:
        summaries.append(_sector_summary(s["id"], conn, strategy, sctx))
    conn.close()

    for s in summaries:
        if s["latest_snapshot"]:
            # The Markets layer (movers classification) is universal: it uses
            # the canonical score/state, not the strategy-specific ones.
            s["score"] = s["latest_snapshot"].get("canonical_score", s["latest_snapshot"].get("score", 0))
            s["state"] = s["latest_snapshot"].get("canonical_state", s["latest_snapshot"].get("state", "neutral"))
        else:
            s["score"] = 0
            s["state"] = "neutral"

    leaders = sorted([s for s in summaries if s["state"] == "leader"], key=lambda x: x["score"], reverse=True)
    emerging = sorted([s for s in summaries if s["state"] == "emerging"], key=lambda x: x["score"], reverse=True)
    fading = sorted([s for s in summaries if s["state"] == "fading"], key=lambda x: x["score"], reverse=True)
    lagging = sorted([s for s in summaries if s["state"] == "lagging"], key=lambda x: x["score"])
    neutral = [s for s in summaries if s["state"] == "neutral"]

    # market summary from benchmark
    conn = _mk_conn()
    bench = conn.execute(
        "SELECT * FROM stock WHERE ticker=?", (BENCHMARK_TICKER,)
    ).fetchone()
    conn.close()

    # synthetic market history: average of normalized sector price histories
    # (last 30 common snapshot dates). Points are aligned by date (not index)
    # and corrupt prints are filtered out: a sector ETF jumping more than 20%
    # in a single snapshot is a data glitch, so the last good value is carried
    # forward instead of letting it cliff the composite.
    market_history = []
    series = [
        {r["dt"]: r["price"] for r in s["history"] if r["price"]}
        for s in summaries if s.get("history")
    ]
    series = [h for h in series if h]
    if series:
        common = sorted(set.intersection(*[set(h) for h in series]))[-30:]
        if common:
            normed = []
            for h in series:
                base = h[common[0]] or 1
                vals = []
                prev = None
                for dt in common:
                    v = h[dt] / base * 100
                    if prev is not None and abs(v / prev - 1) > 0.20:
                        v = prev
                    vals.append(v)
                    prev = v
                normed.append(vals)
            for i in range(len(common)):
                market_history.append(round(sum(v[i] for v in normed) / len(normed), 2))

    # Cross-sector command metrics: RS percentile, beta vs benchmark, top-5 persistence
    rs_vals = [
        (s["latest_snapshot"] or {}).get("rs_vs_spy_1m") or 0
        for s in summaries if s["latest_snapshot"]
    ]
    mkt_rets = _daily_returns(market_history)
    conn = _mk_conn()
    dts = [r[0] for r in conn.execute(
        "SELECT DISTINCT dt FROM sector_snapshot ORDER BY dt DESC LIMIT 10"
    ).fetchall()]
    rank_by_dt = {}
    for dt in dts:
        rows = conn.execute(
            "SELECT sector_id, score FROM sector_snapshot WHERE dt=?", (dt,)
        ).fetchall()
        ordered = sorted(rows, key=lambda r: (r["score"] or 0), reverse=True)
        rank_by_dt[dt] = {r["sector_id"]: i + 1 for i, r in enumerate(ordered)}
    conn.close()

    for s in summaries:
        cmd = s.get("command") or {}
        v = (s["latest_snapshot"] or {}).get("rs_vs_spy_1m") or 0
        cmd["rs_percentile"] = (
            round(sum(1 for x in rs_vals if x <= v) / len(rs_vals) * 100, 0) if rs_vals else None
        )
        cmd["top5_persistence"] = (
            round(sum(1 for dt in dts if rank_by_dt[dt].get(s["id"], 99) <= 5) / len(dts) * 100, 0)
            if dts else None
        )
        prices = [r["price"] for r in (s.get("history") or []) if r["price"]]
        sr = _daily_returns(prices)
        k = min(len(sr), len(mkt_rets))
        beta = None
        if k >= 5:
            mr, sr = mkt_rets[-k:], sr[-k:]
            mm, sm = sum(mr) / k, sum(sr) / k
            var = sum((x - mm) ** 2 for x in mr) / k
            if var:
                cov = sum((a - mm) * (b - sm) for a, b in zip(mr, sr)) / k
                beta = round(cov / var, 2)
        cmd["beta"] = beta
        s["command"] = cmd

    # Risk environment from the CCI(34) oscillator on the major indices
    # (SPY / QQQ / DJI / IWM). Each index's rating is scored and averaged:
    # >= 0.5 -> Bullish, <= -0.25 -> Bearish, otherwise Mixed. The average
    # also maps to the 0-100 risk gauge.
    conn = _mk_conn()
    idx_rows = conn.execute(
        """SELECT * FROM index_cci ORDER BY CASE ticker
           WHEN 'SPY' THEN 0 WHEN 'QQQ' THEN 1 WHEN 'DJI' THEN 2 ELSE 3 END"""
    ).fetchall()
    conn.close()
    indices = [dict(r) for r in idx_rows]
    _overlay_live_index_quotes(indices)
    scores = [CCI_RATING_SCORE[r["rating"]] for r in indices if r["rating"] in CCI_RATING_SCORE]
    market_rating = None
    risk_score = None
    if scores:
        avg_score = sum(scores) / len(scores)
        risk_score = round(50 + 50 * avg_score)
        market_rating = "Bullish" if avg_score >= 0.5 else ("Bearish" if avg_score <= -0.25 else "Mixed")

    def _bench_col(name):
        return bench[name] if bench and name in bench.keys() else None

    # Trend flags the Markets page expects: 10/20 EMA cross for the short-term
    # trend, price vs 50 EMA for the overall trend. Previously these keys were
    # missing from the payload, so the UI always fell back to
    # "Downtrend / Below 50EMA".
    bench_price = _bench_col("price")
    bench_ema10 = _bench_col("ema10")
    bench_ema20 = _bench_col("ema20")
    bench_ema50 = _bench_col("ema50")
    trend = None
    if bench_ema10 is not None and bench_ema20 is not None:
        trend = "uptrend" if bench_ema10 > bench_ema20 else "downtrend"
    overall_trend = None
    if bench_price is not None and bench_ema50 is not None:
        overall_trend = "above_50ema" if bench_price > bench_ema50 else "below_50ema"

    return {
        "last_synced": status_row["last_synced"] if status_row else None,
        "mode": status_row["mode"] if status_row else "demo",
        "strategy": {
            "id": sctx["strategy"],
            "label": sctx["label"],
            "cci_factor": sctx["cci_factor"],
        },
        "market_history": market_history,
        "sectors": summaries,
        "leaders": leaders[:5],
        "emerging": emerging[:5],
        "fading": fading[:5],
        "lagging": lagging[:5],
        "neutral": neutral,
        "market_summary": {
            "ticker": BENCHMARK_TICKER,
            "price": bench["price"] if bench else None,
            "chg_1d": bench["chg_1d"] if bench else None,
            "chg_1w": bench["chg_1w"] if bench else None,
            "chg_1m": bench["chg_1m"] if bench else None,
            "indices": indices,
            "market_rating": market_rating,
            "risk_score": risk_score,
            "trend": trend,
            "overall_trend": overall_trend,
            "returns": {
                "1M": _bench_col("chg_1m"),
                "3M": _bench_col("chg_3m"),
                "YTD": _bench_col("chg_ytd"),
                "1Y": _bench_col("chg_1y"),
            },
        }
    }


@app.get("/api/stocks/{ticker}")
def stock_detail(ticker: str):
    conn = _mk_conn()
    s = conn.execute("SELECT * FROM stock WHERE ticker=?", (ticker,)).fetchone()
    conn.close()
    if not s:
        raise HTTPException(404, "stock not found")
    return dict(s)


@app.post("/api/sectors/{sector_id}/journal")
def add_journal(sector_id: int, payload: dict = Body(...)):
    conn = _mk_conn()
    conn.execute(
        "INSERT INTO journal (sector_id, ts, note) VALUES (?,?,?)",
        (sector_id, datetime.now().isoformat(), payload.get("note", "")),
    )
    conn.commit()
    rows = conn.execute(
        "SELECT * FROM journal WHERE sector_id=? ORDER BY ts DESC", (sector_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/sectors/{sector_id}/journal")
def get_journal(sector_id: int):
    conn = _mk_conn()
    rows = conn.execute(
        "SELECT * FROM journal WHERE sector_id=? ORDER BY ts DESC", (sector_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.put("/api/sectors/{sector_id}/conviction")
def set_conviction(sector_id: int, payload: dict = Body(...)):
    conn = _mk_conn()
    conn.execute("UPDATE sector SET conviction=? WHERE id=?", (payload.get("conviction", 3), sector_id))
    conn.commit()
    conn.close()
    return {"status": "ok"}


# --- trades ---
@app.post("/api/trades")
def add_trade(payload: dict = Body(...)):
    conn = _mk_conn()
    conn.execute(
        "INSERT INTO trade (ts, ticker, sector_id, risk_pct) VALUES (?,?,?,?)",
        (
            datetime.now().isoformat(),
            (payload.get("ticker") or "").strip().upper(),
            payload.get("sector_id"),
            float(payload.get("risk_pct") or 0),
        ),
    )
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.get("/api/trades")
def list_trades():
    conn = _mk_conn()
    rows = conn.execute(
        """SELECT t.*, s.name AS sector_name, s.color
           FROM trade t LEFT JOIN sector s ON s.id = t.sector_id
           ORDER BY t.ts DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.delete("/api/trades/{trade_id}")
def delete_trade(trade_id: int):
    conn = _mk_conn()
    conn.execute("DELETE FROM trade WHERE id=?", (trade_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.get("/api/trades/summary")
def trades_summary():
    conn = _mk_conn()
    rows = conn.execute(
        """SELECT t.sector_id, s.name AS sector_name, s.ticker AS sector_ticker, s.color,
                  SUM(t.risk_pct) AS total_risk, COUNT(*) AS trades
           FROM trade t JOIN sector s ON s.id = t.sector_id
           GROUP BY t.sector_id ORDER BY total_risk DESC"""
    ).fetchall()
    out = []
    for r in rows:
        snap = _latest_sector_snapshot(r["sector_id"], conn)
        out.append({
            "sector_id": r["sector_id"],
            "sector_name": r["sector_name"],
            "sector_ticker": r["sector_ticker"],
            "color": r["color"],
            "total_risk": round(r["total_risk"], 2),
            "trades": r["trades"],
            "state": snap["state"] if snap else "neutral",
            "score": snap["score"] if snap else 0,
        })
    total = sum(r["total_risk"] for r in out)
    weak = sum(r["total_risk"] for r in out if r["state"] in ("fading", "lagging"))
    conn.close()
    return {
        "sectors": out,
        "total_risk": round(total, 2),
        "weak_risk": round(weak, 2),
        "weak_share": round(weak / total * 100, 1) if total > 0 else 0,
    }


# --- watchlist ---
@app.get("/api/watchlist")
def get_watchlist():
    conn = _mk_conn()
    entries = engine.watchlist_entries(conn)
    conn.close()
    return entries


@app.post("/api/watchlist")
def add_watchlist(payload: dict = Body(...)):
    ticker = (payload.get("ticker") or "").strip().upper()
    if not ticker:
        raise HTTPException(400, "ticker required")
    category = payload.get("category") or "breakout"
    if category not in ("breakout", "ep"):
        raise HTTPException(400, "category must be 'breakout' or 'ep'")
    conn = _mk_conn()
    conn.execute(
        """INSERT INTO watchlist (ticker, category, added_at) VALUES (?,?,?)
           ON CONFLICT(ticker) DO UPDATE SET category=excluded.category""",
        (ticker, category, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.patch("/api/watchlist/{ticker}")
def update_watchlist(ticker: str, payload: dict = Body(...)):
    category = payload.get("category")
    if category not in ("breakout", "ep"):
        raise HTTPException(400, "category must be 'breakout' or 'ep'")
    conn = _mk_conn()
    cur = conn.execute("UPDATE watchlist SET category=? WHERE ticker=?",
                       (category, ticker.strip().upper()))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "not in watchlist")
    return {"status": "ok"}


@app.delete("/api/watchlist/{ticker}")
def delete_watchlist(ticker: str):
    conn = _mk_conn()
    cur = conn.execute("DELETE FROM watchlist WHERE ticker=?", (ticker.strip().upper(),))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "not in watchlist")
    return {"status": "ok"}


# --- EP (Episodic Pivot) scanner ---
@app.get("/api/ep-scan")
def ep_scan():
    conn = _mk_conn()
    out = engine.ep_scan(conn)
    conn.close()
    return out


@app.get("/api/ep-dashboard")
def ep_dashboard():
    conn = _mk_conn()
    out = engine.ep_dashboard(conn)
    conn.close()
    return out


# --- ETF screening hub ---

# Curated universe of highly liquid US ETFs by category.
ETF_UNIVERSE = {
    "Broad":      ["SPY", "QQQ", "DIA", "IWM", "MDY", "RSP",
                   "VOO", "VTI", "IWB", "IWF", "IWD", "SCHD", "VIG",
                   "IVV", "VV", "ITOT", "SCHX", "SCHG", "VUG", "VTV",
                   "IJR", "IJH", "DGRO", "USMV", "QUAL", "MTUM", "VLUE",
                   "DVY", "NOBL", "JEPI"],
    "Sector":     ["XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU",
                   "XLC", "XLB", "XLRE", "SMH", "SOXX", "IGV",
                   "VGT", "VFH", "VHT", "FDN",
                   "VAW", "VDE", "VCR", "VDC", "VPU", "VOX", "VNQ", "VIS"],
    "Thematic":   ["ARKK", "ARKG", "HACK", "BOTZ", "ICLN", "TAN", "LIT", "SKYY",
                   "FINX", "CIBR", "XT",
                   "ROBO", "ARKW", "ARKF", "GRID", "KWEB", "AIQ"],
    "Industry":   ["XBI", "IBB", "KRE", "KBE", "XOP", "OIH", "XME", "IYT",
                   "ITB", "XHB", "XRT", "GDX", "GDXJ", "SIL", "URA", "XAR",
                   "PAVE", "JETS", "ITA",
                   "XSD", "PPH", "IHI", "IHF", "IAI", "KIE", "AMLP", "IGM",
                   "COPX", "PICK", "REM", "NLR", "WOOD"],
    "Commodity/Macro": ["GLD", "SLV", "USO", "UNG", "DBA", "CPER", "UUP",
                        "TLT", "HYG", "EEM", "EFA",
                        "AGG", "BND", "LQD", "IEF", "SHY", "DBC", "FXE",
                        "IEMG", "VWO", "VEA", "VXUS", "TIP", "MUB", "SHV",
                        "GOVT", "EMB", "BNDX"],
}
ETF_CATEGORY = {t: cat for cat, tickers in ETF_UNIVERSE.items() for t in tickers}

# Liquidity floor for the "qualified" universe.
ETF_MIN_AUM = 300e6
ETF_MIN_AVG_VOLUME = 200000

# Hand-picked constituents for every hub ETF. Only large, liquid names:
# every pick is enforced at fetch time to have 30d avg volume >= 1M shares
# and market cap >= $600M. Used whenever an ETF has no sector/industry mapping
# in the local stock universe (e.g. ARKG, thematic/macro funds), and to top up
# mapped ETFs whose local universe holds fewer than 5 stocks.
CURATED_MIN_AVG_VOLUME = 1_000_000
CURATED_MIN_MCAP_MUSD = 600.0
ETF_TOP_STOCKS = {
    # Broad
    "SPY":  ["NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:NVDA", "NASDAQ:AMZN", "NASDAQ:META", "NASDAQ:GOOGL", "NYSE:JPM"],
    "QQQ":  ["NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:NVDA", "NASDAQ:AVGO", "NASDAQ:COST", "NASDAQ:NFLX", "NASDAQ:AMD"],
    "DIA":  ["NYSE:UNH", "NYSE:GS", "NASDAQ:MSFT", "NYSE:HD", "NYSE:CAT", "NYSE:AXP", "NYSE:JNJ"],
    "IWM":  ["NASDAQ:SMCI", "NYSE:CVNA", "NASDAQ:HOOD", "NYSE:RBLX", "NYSE:IONQ", "NYSE:OKLO", "NASDAQ:AFRM", "NYSE:JOBY"],
    "MDY":  ["NYSE:IONQ", "NYSE:OKLO", "NYSE:FTAI", "NASDAQ:DUOL", "NYSE:ONON", "NYSE:RBRK", "NASDAQ:AFRM"],
    "RSP":  ["NASDAQ:AAPL", "NYSE:XOM", "NYSE:WMT", "NYSE:JPM", "NYSE:JNJ", "NYSE:PG"],
    "VOO":  ["NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:NVDA", "NASDAQ:AMZN", "NASDAQ:META", "NASDAQ:GOOGL", "NYSE:BRK-B"],
    "VTI":  ["NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:NVDA", "NASDAQ:AMZN", "NASDAQ:META", "NYSE:JPM", "NYSE:XOM"],
    "IWB":  ["NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:NVDA", "NASDAQ:AMZN", "NASDAQ:META", "NYSE:BRK-B", "NYSE:JPM"],
    "IWF":  ["NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:NVDA", "NASDAQ:META", "NASDAQ:AVGO", "NASDAQ:TSLA", "NYSE:LLY"],
    "IWD":  ["NYSE:JPM", "NYSE:XOM", "NYSE:JNJ", "NYSE:WMT", "NYSE:BAC", "NYSE:PG", "NYSE:HD"],
    "SCHD": ["NYSE:KO", "NASDAQ:PEP", "NYSE:HD", "NYSE:VZ", "NYSE:PFE", "NYSE:MO", "NYSE:CVX"],
    "VIG":  ["NASDAQ:AAPL", "NYSE:UNH", "NYSE:JNJ", "NYSE:XOM", "NYSE:JPM", "NYSE:PG", "NYSE:HD"],
    # Sector
    "XLK":  ["NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:NVDA", "NASDAQ:AVGO", "NYSE:ORCL", "NASDAQ:AMD", "NYSE:CRM"],
    "XLF":  ["NYSE:JPM", "NYSE:V", "NYSE:MA", "NYSE:BAC", "NYSE:WFC", "NYSE:GS"],
    "XLV":  ["NYSE:LLY", "NYSE:UNH", "NYSE:JNJ", "NYSE:ABBV", "NYSE:MRK", "NYSE:ABT", "NYSE:TMO"],
    "XLE":  ["NYSE:XOM", "NYSE:CVX", "NYSE:COP", "NYSE:EOG", "NYSE:SLB", "NYSE:MPC"],
    "XLI":  ["NYSE:GE", "NYSE:CAT", "NYSE:RTX", "NYSE:UNP", "NYSE:HON", "NYSE:BA", "NYSE:DE"],
    "XLY":  ["NASDAQ:AMZN", "NASDAQ:TSLA", "NYSE:HD", "NYSE:MCD", "NYSE:NKE", "NYSE:LOW", "NYSE:TJX"],
    "XLP":  ["NYSE:WMT", "NASDAQ:COST", "NYSE:PG", "NYSE:KO", "NASDAQ:PEP", "NYSE:PM"],
    "XLU":  ["NYSE:NEE", "NYSE:SO", "NYSE:DUK", "NASDAQ:CEG", "NYSE:VST", "NYSE:AEP"],
    "XLC":  ["NASDAQ:META", "NASDAQ:GOOGL", "NASDAQ:NFLX", "NYSE:DIS", "NASDAQ:TMUS", "NYSE:T"],
    "XLB":  ["NYSE:LIN", "NYSE:SHW", "NYSE:FCX", "NYSE:NEM", "NYSE:ECL", "NYSE:CTVA"],
    "XLRE": ["NYSE:PLD", "NYSE:AMT", "NASDAQ:EQIX", "NYSE:CCI", "NYSE:SPG", "NYSE:WELL"],
    "SMH":  ["NASDAQ:NVDA", "NASDAQ:TSM", "NASDAQ:AVGO", "NASDAQ:AMD", "NASDAQ:QCOM", "NYSE:TXN", "NASDAQ:AMAT", "NASDAQ:MU"],
    "SOXX": ["NASDAQ:NVDA", "NASDAQ:AVGO", "NASDAQ:AMD", "NYSE:TXN", "NASDAQ:MU", "NASDAQ:INTC", "NASDAQ:LRCX"],
    "IGV":  ["NASDAQ:MSFT", "NYSE:CRM", "NASDAQ:ADBE", "NYSE:NOW", "NASDAQ:PLTR", "NASDAQ:INTU", "NYSE:ORCL"],
    "VGT":  ["NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:NVDA", "NASDAQ:AVGO", "NASDAQ:AMD", "NYSE:ORCL", "NASDAQ:CSCO"],
    "VFH":  ["NYSE:JPM", "NYSE:V", "NYSE:MA", "NYSE:BAC", "NYSE:WFC", "NYSE:GS", "NYSE:MS"],
    "VHT":  ["NYSE:LLY", "NYSE:UNH", "NYSE:JNJ", "NYSE:ABBV", "NYSE:MRK", "NYSE:TMO", "NYSE:ABT"],
    "FDN":  ["NASDAQ:META", "NASDAQ:AMZN", "NASDAQ:GOOGL", "NASDAQ:NFLX", "NYSE:CRM", "NASDAQ:ADBE", "NYSE:SHOP"],
    # Thematic
    "ARKK": ["NASDAQ:TSLA", "NASDAQ:COIN", "NASDAQ:HOOD", "NYSE:ROKU", "NYSE:RBLX", "NASDAQ:PLTR", "NASDAQ:CRSP", "NASDAQ:SHOP"],
    "ARKG": ["NASDAQ:CRSP", "NASDAQ:VRTX", "NASDAQ:ILMN", "NASDAQ:NTRA", "NASDAQ:EXAS", "NASDAQ:TEM", "NASDAQ:MRNA"],
    "HACK": ["NASDAQ:CRWD", "NASDAQ:PANW", "NASDAQ:FTNT", "NASDAQ:ZS", "NASDAQ:OKTA", "NASDAQ:NET", "NYSE:S"],
    "BOTZ": ["NASDAQ:NVDA", "NASDAQ:ISRG", "NASDAQ:TER", "NASDAQ:PATH", "NASDAQ:SYM", "NASDAQ:CGNX"],
    "ICLN": ["NASDAQ:ENPH", "NASDAQ:FSLR", "NASDAQ:PLUG", "NYSE:RUN", "NYSE:NEE", "NYSE:AES"],
    "TAN":  ["NASDAQ:FSLR", "NASDAQ:ENPH", "NASDAQ:RUN", "NASDAQ:NXT", "NASDAQ:SEDG"],
    "LIT":  ["NYSE:ALB", "NASDAQ:SGML", "NYSE:LAC", "NASDAQ:TSLA", "NASDAQ:QS", "NYSE:RIO"],
    "SKYY": ["NASDAQ:MSFT", "NASDAQ:AMZN", "NASDAQ:GOOGL", "NYSE:ORCL", "NYSE:IBM", "NASDAQ:NET", "NASDAQ:SNOW"],
    "FINX": ["NASDAQ:PYPL", "NYSE:SQ", "NASDAQ:COIN", "NYSE:XP", "NASDAQ:HOOD", "NYSE:NU", "NYSE:FI"],
    "CIBR": ["NASDAQ:CRWD", "NASDAQ:PANW", "NASDAQ:FTNT", "NASDAQ:ZS", "NASDAQ:OKTA", "NASDAQ:CSCO", "NYSE:NET"],
    "XT":   ["NYSE:IBM", "NASDAQ:INTC", "NYSE:RTX", "NYSE:GE", "NYSE:CAT", "NYSE:DE", "NYSE:HON"],
    # Industry
    "XBI":  ["NASDAQ:MRNA", "NASDAQ:VRTX", "NASDAQ:REGN", "NASDAQ:BIIB", "NASDAQ:NBIX", "NASDAQ:INCY", "NASDAQ:NTRA"],
    "IBB":  ["NASDAQ:AMGN", "NASDAQ:GILD", "NASDAQ:VRTX", "NASDAQ:REGN", "NASDAQ:MRNA", "NASDAQ:BIIB", "NASDAQ:ILMN"],
    "KRE":  ["NYSE:RF", "NYSE:CFG", "NYSE:FITB", "NASDAQ:HBAN", "NYSE:KEY", "NYSE:MTB", "NASDAQ:ZION"],
    "KBE":  ["NYSE:JPM", "NYSE:BAC", "NYSE:WFC", "NYSE:C", "NYSE:USB", "NYSE:PNC"],
    "XOP":  ["NYSE:EOG", "NYSE:DVN", "NASDAQ:FANG", "NYSE:OXY", "NYSE:APA", "NYSE:OVV", "NYSE:SM"],
    "OIH":  ["NYSE:SLB", "NYSE:HAL", "NASDAQ:BKR", "NYSE:NOV", "NYSE:LBRT", "NYSE:RES"],
    "XME":  ["NYSE:FCX", "NYSE:NEM", "NASDAQ:STLD", "NYSE:NUE", "NYSE:CLF", "NYSE:X", "NYSE:AA"],
    "IYT":  ["NYSE:UNP", "NYSE:UPS", "NYSE:FDX", "NASDAQ:CSX", "NYSE:NSC", "NASDAQ:ODFL", "NYSE:UBER"],
    "ITB":  ["NYSE:DHI", "NYSE:LEN", "NYSE:PHM", "NYSE:TOL", "NYSE:BLDR", "NYSE:SHW"],
    "XHB":  ["NYSE:DHI", "NYSE:LEN", "NYSE:PHM", "NYSE:BLDR", "NYSE:HD", "NYSE:LOW", "NYSE:TOL", "NYSE:WSM"],
    "XRT":  ["NYSE:M", "NYSE:GAP", "NASDAQ:URBN", "NYSE:ANF", "NYSE:BBY", "NYSE:DKS"],
    "GDX":  ["NYSE:NEM", "NYSE:AEM", "NYSE:B", "NYSE:EGO", "NYSE:WPM", "NYSE:KGC", "NYSE:AU"],
    "GDXJ": ["NYSE:AGI", "AMEX:BTG", "NYSE:HL", "NYSE:CDE", "NYSE:IAG", "NYSE:OR"],
    "SIL":  ["NYSE:PAAS", "NYSE:AG", "NYSE:WPM", "NYSE:HL", "NYSE:CDE", "NYSE:FSM"],
    "URA":  ["NYSE:CCJ", "AMEX:UUUU", "AMEX:UEC", "NYSE:NXE", "AMEX:DNN", "NYSE:LEU", "NYSE:SMR"],
    "XAR":  ["NYSE:RTX", "NYSE:LMT", "NYSE:NOC", "NYSE:GD", "NYSE:HWM", "NYSE:RKLB", "NYSE:LHX", "NYSE:TXT"],
    "PAVE": ["NYSE:URI", "NYSE:PWR", "NYSE:EME", "NYSE:VMC", "NYSE:MLM", "NYSE:CAT", "NASDAQ:CSGP"],
    "JETS": ["NYSE:DAL", "NYSE:UAL", "NASDAQ:AAL", "NASDAQ:LUV", "NYSE:ALK", "NASDAQ:JBLU"],
    "ITA":  ["NYSE:RTX", "NYSE:LMT", "NYSE:GD", "NYSE:NOC", "NYSE:BA", "NYSE:HWM", "NYSE:LHX"],
    # Commodity / Macro
    "GLD":  ["NYSE:NEM", "NYSE:AEM", "NYSE:B", "NYSE:EGO", "NYSE:WPM", "NYSE:KGC", "NYSE:AU"],
    "SLV":  ["NYSE:PAAS", "NYSE:AG", "NYSE:WPM", "NYSE:HL", "NYSE:CDE", "NYSE:FSM"],
    "USO":  ["NYSE:XOM", "NYSE:CVX", "NYSE:COP", "NYSE:EOG", "NYSE:SLB", "NYSE:OXY"],
    "UNG":  ["NYSE:EQT", "NYSE:AR", "NYSE:RRC", "NASDAQ:EXE", "NYSE:CRGY"],
    "DBA":  ["NYSE:ADM", "NYSE:BG", "NYSE:CF", "NYSE:MOS", "NYSE:NTR", "NYSE:DE", "NYSE:AGCO"],
    "CPER": ["NYSE:FCX", "NYSE:SCCO", "NYSE:TECK", "NYSE:BHP", "NYSE:RIO", "NYSE:HBM"],
    "UUP":  ["NYSE:CAT", "NYSE:BA", "NYSE:GS", "NYSE:JPM", "NYSE:MMM"],
    "TLT":  ["NYSE:NEE", "NYSE:AMT", "NYSE:PLD", "NYSE:DUK", "NYSE:SO"],
    "HYG":  ["NYSE:F", "NYSE:T", "NYSE:VZ", "NYSE:OXY", "NASDAQ:CHTR", "NYSE:CCL"],
    "EEM":  ["NASDAQ:TSM", "NYSE:BABA", "NASDAQ:PDD", "NYSE:VALE", "NYSE:PBR", "NYSE:INFY", "NYSE:HDB"],
    "EFA":  ["NYSE:AZN", "NYSE:NVS", "NASDAQ:ASML", "NYSE:SAP", "NYSE:TM", "NYSE:SONY", "NYSE:SHEL"],
    "AGG":  ["NYSE:JPM", "NYSE:BAC", "NYSE:WFC", "NYSE:GS", "NYSE:MS", "NASDAQ:AAPL", "NYSE:XOM"],
    "BND":  ["NYSE:JPM", "NYSE:BAC", "NYSE:WFC", "NYSE:GS", "NYSE:MS", "NYSE:BRK-B", "NYSE:JNJ"],
    "LQD":  ["NYSE:JPM", "NYSE:BAC", "NYSE:GS", "NYSE:MS", "NASDAQ:AAPL", "NASDAQ:MSFT", "NYSE:VZ"],
    "IEF":  ["NYSE:NEE", "NYSE:DUK", "NYSE:SO", "NYSE:AMT", "NYSE:PLD", "NYSE:CCI"],
    "SHY":  ["NYSE:JPM", "NYSE:GS", "NYSE:MS", "NYSE:BAC", "NYSE:BLK"],
    "DBC":  ["NYSE:XOM", "NYSE:CVX", "NYSE:COP", "NYSE:ADM", "NYSE:NEM", "NYSE:FCX"],
    "FXE":  ["NYSE:SAP", "NYSE:ASML", "NYSE:NVS", "NYSE:SAN", "NYSE:UL", "NYSE:AZN"],
    # Broad (extended)
    "IVV":  ["NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:NVDA", "NASDAQ:AMZN", "NASDAQ:META", "NASDAQ:GOOGL", "NYSE:BRK-B"],
    "VV":   ["NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:NVDA", "NASDAQ:AMZN", "NASDAQ:META", "NYSE:JPM", "NYSE:XOM"],
    "ITOT": ["NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:NVDA", "NASDAQ:AMZN", "NASDAQ:META", "NYSE:JPM", "NYSE:XOM"],
    "SCHX": ["NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:NVDA", "NASDAQ:AMZN", "NASDAQ:META", "NYSE:JPM", "NYSE:LLY"],
    "SCHG": ["NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:NVDA", "NASDAQ:AMZN", "NASDAQ:META", "NASDAQ:TSLA", "NASDAQ:AVGO"],
    "VUG":  ["NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:NVDA", "NASDAQ:AMZN", "NASDAQ:META", "NASDAQ:GOOGL", "NASDAQ:TSLA"],
    "VTV":  ["NYSE:JPM", "NYSE:XOM", "NYSE:JNJ", "NYSE:WMT", "NYSE:PG", "NYSE:BAC", "NYSE:HD"],
    "IJR":  ["NASDAQ:HOOD", "NYSE:IONQ", "NYSE:OKLO", "NYSE:RBLX", "NYSE:JOBY", "NASDAQ:AFRM", "NYSE:CVNA"],
    "IJH":  ["NYSE:FTAI", "NASDAQ:DUOL", "NYSE:ONON", "NYSE:RBRK", "NYSE:IONQ", "NYSE:OKLO", "NYSE:WING"],
    "DGRO": ["NASDAQ:AAPL", "NASDAQ:MSFT", "NYSE:JNJ", "NYSE:XOM", "NYSE:JPM", "NYSE:PG", "NYSE:HD"],
    "USMV": ["NYSE:KO", "NYSE:JNJ", "NYSE:PG", "NYSE:WMT", "NYSE:MCD", "NYSE:VZ", "NYSE:NEE"],
    "QUAL": ["NASDAQ:NVDA", "NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:META", "NASDAQ:AVGO", "NYSE:V", "NYSE:MA"],
    "MTUM": ["NASDAQ:NVDA", "NYSE:GE", "NYSE:JPM", "NASDAQ:AVGO", "NASDAQ:NFLX", "NASDAQ:PLTR", "NYSE:V"],
    "VLUE": ["NYSE:GM", "NYSE:F", "NASDAQ:MU", "NYSE:PFE", "NYSE:T", "NYSE:VZ", "NYSE:CVS"],
    "DVY":  ["NYSE:MO", "NYSE:VZ", "NYSE:T", "NYSE:XOM", "NYSE:CVX", "NYSE:PFE", "NYSE:SO"],
    "NOBL": ["NYSE:MMM", "NYSE:KO", "NYSE:JNJ", "NYSE:PG", "NYSE:MCD", "NYSE:WMT", "NYSE:EMR"],
    "JEPI": ["NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:AMZN", "NASDAQ:META", "NASDAQ:GOOGL", "NYSE:JNJ", "NYSE:PG"],
    # Sector (extended)
    "VAW":  ["NYSE:LIN", "NYSE:SHW", "NYSE:FCX", "NYSE:NEM", "NYSE:ECL", "NYSE:CTVA"],
    "VDE":  ["NYSE:XOM", "NYSE:CVX", "NYSE:COP", "NYSE:EOG", "NYSE:SLB", "NYSE:MPC"],
    "VCR":  ["NASDAQ:AMZN", "NASDAQ:TSLA", "NYSE:HD", "NYSE:MCD", "NYSE:NKE", "NYSE:LOW"],
    "VDC":  ["NYSE:WMT", "NASDAQ:COST", "NYSE:PG", "NYSE:KO", "NASDAQ:PEP", "NYSE:PM"],
    "VPU":  ["NYSE:NEE", "NYSE:SO", "NYSE:DUK", "NASDAQ:CEG", "NYSE:VST", "NYSE:AEP"],
    "VOX":  ["NASDAQ:META", "NASDAQ:GOOGL", "NASDAQ:NFLX", "NYSE:DIS", "NASDAQ:TMUS", "NYSE:T"],
    "VNQ":  ["NYSE:PLD", "NYSE:AMT", "NASDAQ:EQIX", "NYSE:CCI", "NYSE:SPG", "NYSE:WELL"],
    "VIS":  ["NYSE:GE", "NYSE:CAT", "NYSE:RTX", "NYSE:UNP", "NYSE:HON", "NYSE:BA"],
    # Thematic (extended)
    "ROBO": ["NASDAQ:TER", "NASDAQ:PATH", "NASDAQ:ISRG", "NYSE:ROK", "NASDAQ:SYM", "NASDAQ:CGNX"],
    "ARKW": ["NASDAQ:TSLA", "NASDAQ:COIN", "NASDAQ:HOOD", "NYSE:ROKU", "NASDAQ:PLTR", "NASDAQ:SHOP", "NYSE:RBLX"],
    "ARKF": ["NASDAQ:COIN", "NASDAQ:HOOD", "NASDAQ:SHOP", "NASDAQ:SOFI", "NASDAQ:PYPL", "NYSE:NU", "NYSE:RBLX"],
    "GRID": ["NYSE:ETN", "NYSE:PWR", "NYSE:GEV", "NASDAQ:CEG", "NYSE:VST", "NYSE:EME"],
    "KWEB": ["NYSE:BABA", "NASDAQ:PDD", "NASDAQ:JD", "NASDAQ:BIDU", "NASDAQ:NTES", "NASDAQ:TCOM", "NYSE:BEKE"],
    "AIQ":  ["NASDAQ:NVDA", "NASDAQ:MSFT", "NASDAQ:META", "NASDAQ:GOOGL", "NASDAQ:AMZN", "NASDAQ:AVGO", "NASDAQ:AMD"],
    # Industry (extended)
    "XSD":  ["NASDAQ:NVDA", "NASDAQ:AMD", "NASDAQ:MU", "NASDAQ:LRCX", "NASDAQ:AMAT", "NASDAQ:QCOM", "NYSE:TXN"],
    "PPH":  ["NYSE:LLY", "NYSE:JNJ", "NYSE:MRK", "NYSE:PFE", "NYSE:ABBV", "NYSE:BMY", "NASDAQ:AMGN"],
    "IHI":  ["NASDAQ:ISRG", "NYSE:ABT", "NYSE:MDT", "NYSE:BSX", "NASDAQ:DXCM", "NYSE:SYK", "NYSE:EW"],
    "IHF":  ["NYSE:UNH", "NYSE:ELV", "NYSE:CI", "NYSE:CVS", "NYSE:HCA", "NYSE:HUM", "NYSE:MCK"],
    "IAI":  ["NYSE:GS", "NYSE:MS", "NYSE:BLK", "NYSE:SCHW", "NASDAQ:IBKR", "NYSE:RJF", "NYSE:SPGI"],
    "KIE":  ["NYSE:PGR", "NYSE:ALL", "NYSE:TRV", "NYSE:CB", "NYSE:MET", "NYSE:AIG", "NYSE:AFL"],
    "AMLP": ["NYSE:ET", "NYSE:EPD", "NYSE:WMB", "NYSE:KMI", "NYSE:OKE", "NYSE:MPLX", "NYSE:PAA"],
    "IGM":  ["NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:NVDA", "NASDAQ:AVGO", "NYSE:ORCL", "NYSE:CRM", "NASDAQ:AMD"],
    "COPX": ["NYSE:FCX", "NYSE:SCCO", "NYSE:TECK", "NYSE:BHP", "NYSE:RIO", "NYSE:HBM", "NYSE:AA"],
    "PICK": ["NYSE:BHP", "NYSE:RIO", "NYSE:VALE", "NYSE:FCX", "NYSE:SCCO", "NYSE:TECK", "NYSE:NEM"],
    "REM":  ["NASDAQ:AGNC", "NYSE:NLY", "NYSE:STWD", "NYSE:BXMT", "NYSE:RITM", "NYSE:NYMT"],
    "NLR":  ["NYSE:CCJ", "AMEX:UUUU", "AMEX:UEC", "NYSE:SMR", "NYSE:LEU", "NYSE:BWXT", "NYSE:GEV"],
    "WOOD": ["NYSE:WY", "NYSE:RYN", "NASDAQ:PCH", "NYSE:LPX", "NASDAQ:UFPI", "NYSE:BCC"],
    # Commodity / Macro (extended)
    "IEMG": ["NASDAQ:TSM", "NYSE:BABA", "NASDAQ:PDD", "NYSE:VALE", "NYSE:PBR", "NYSE:INFY", "NYSE:HDB"],
    "VWO":  ["NASDAQ:TSM", "NYSE:BABA", "NASDAQ:PDD", "NYSE:VALE", "NYSE:PBR", "NYSE:INFY", "NYSE:HDB"],
    "VEA":  ["NYSE:AZN", "NYSE:NVS", "NASDAQ:ASML", "NYSE:SAP", "NYSE:TM", "NYSE:SONY", "NYSE:SHEL"],
    "VXUS": ["NASDAQ:TSM", "NASDAQ:ASML", "NYSE:SAP", "NYSE:AZN", "NYSE:NVS", "NYSE:BABA", "NYSE:TM"],
    "TIP":  ["NYSE:NEE", "NYSE:DUK", "NYSE:SO", "NYSE:AMT", "NYSE:PLD", "NYSE:CCI"],
    "MUB":  ["NYSE:NEE", "NYSE:DUK", "NYSE:SO", "NYSE:AEP", "NASDAQ:EXC", "NYSE:D"],
    "SHV":  ["NYSE:JPM", "NYSE:GS", "NYSE:MS", "NYSE:BAC", "NYSE:BLK"],
    "GOVT": ["NYSE:JPM", "NYSE:GS", "NYSE:MS", "NYSE:BAC", "NYSE:BLK"],
    "EMB":  ["NYSE:PBR", "NYSE:VALE", "NYSE:ITUB", "NYSE:BABA", "NASDAQ:TSM", "NYSE:INFY"],
    "BNDX": ["NYSE:SAP", "NYSE:ASML", "NYSE:NVS", "NYSE:SAN", "NYSE:UL", "NYSE:AZN"],
}

# ETF hub response cache — one TradingView call every 2 minutes at most.
_etf_hub_cache = {"at": 0.0, "data": None}
_ETF_HUB_TTL = 120.0


def _etf_stock_scope(ticker):
    """Reverse-map an ETF to the local stock universe it represents:
    ("sector", sector_name) / ("industry", industry_name) / None."""
    for name, etf in engine.SECTOR_ETF_MAP.items():
        if etf == ticker and name != "Miscellaneous":
            return ("sector", name)
    for name, etf in engine.INDUSTRY_ETF_MAP.items():
        if etf == ticker:
            return ("industry", name)
    return None


def _etf_hub_breadth(conn):
    """{etf: {"pct_above_20d", "pct_above_50d"}} over the mapped stocks."""
    etfs = {t for t in ETF_CATEGORY}
    out = {}
    sectors = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM sector")}
    for ticker in etfs:
        scope = _etf_stock_scope(ticker)
        if not scope:
            continue
        kind, name = scope
        if kind == "sector":
            ids = [sid for sid, sname in sectors.items() if sname == name]
            if not ids:
                continue
            ph = ",".join("?" * len(ids))
            rows = conn.execute(
                f"SELECT above_20d, above_50d FROM stock WHERE sector_id IN ({ph})",
                ids).fetchall()
        else:
            rows = conn.execute(
                "SELECT above_20d, above_50d FROM stock WHERE industry=?",
                (name,)).fetchall()
        if rows:
            n = len(rows)
            out[ticker] = {
                "pct_above_20d": round(100.0 * sum(1 for r in rows if r["above_20d"]) / n, 1),
                "pct_above_50d": round(100.0 * sum(1 for r in rows if r["above_50d"]) / n, 1),
            }
    return out


def _etf_hub_payload():
    import live_data
    tickers = sorted(ETF_CATEGORY)
    quotes = live_data.fetch_etf_hub_quotes(tickers)
    spy = quotes.get("SPY") or {}

    def num(v):
        return float(v) if isinstance(v, (int, float)) else None

    def spy_perf(col):
        return num(spy.get(col))

    conn = _mk_conn()
    breadth = _etf_hub_breadth(conn)
    conn.close()

    etfs = []
    for t in tickers:
        q = quotes.get(t)
        if not q:
            continue
        close = num(q.get("close"))
        adr = num(q.get("ADR"))
        hi52, lo52 = num(q.get("price_52_week_high")), num(q.get("price_52_week_low"))
        sma20, sma50 = num(q.get("SMA20")), num(q.get("SMA50"))
        aum = num(q.get("aum"))
        avg_vol = num(q.get("average_volume_30d_calc"))
        row = {
            "ticker": t,
            "name": q.get("description") or t,
            "category": ETF_CATEGORY[t],
            "price": round(close, 2) if close else None,
            "chg_1d": num(q.get("change")),
            "chg_1w": num(q.get("Perf.W")),
            "chg_1m": num(q.get("Perf.1M")),
            "chg_3m": num(q.get("Perf.3M")),
            "chg_6m": num(q.get("Perf.6M")),
            "chg_ytd": num(q.get("Perf.YTD")),
            "chg_1y": num(q.get("Perf.Y")),
            "adr_pct": round(adr / close * 100, 2) if adr and close else None,
            "volatility_d": num(q.get("Volatility.D")),
            "volatility_w": num(q.get("Volatility.W")),
            "volatility_m": num(q.get("Volatility.M")),
            "volume": num(q.get("volume")),
            "avg_volume_30d": avg_vol,
            "rel_vol": num(q.get("relative_volume_10d_calc")),
            "aum": aum,
            "pct_from_52w_high": round((close / hi52 - 1) * 100, 2) if close and hi52 else None,
            "pct_from_52w_low": round((close / lo52 - 1) * 100, 2) if close and lo52 else None,
            "above_sma20": bool(close > sma20) if close and sma20 else None,
            "above_sma50": bool(close > sma50) if close and sma50 else None,
            "qualified": bool(aum and aum >= ETF_MIN_AUM and avg_vol and avg_vol >= ETF_MIN_AVG_VOLUME),
        }
        # RS vs SPY per timeframe (ETF perf minus SPY perf).
        for key, col in (("rs_1d", "change"), ("rs_1w", "Perf.W"), ("rs_1m", "Perf.1M"),
                         ("rs_3m", "Perf.3M"), ("rs_6m", "Perf.6M"),
                         ("rs_ytd", "Perf.YTD"), ("rs_1y", "Perf.Y")):
            perf, sp = num(q.get(col)), spy_perf(col)
            row[key] = round(perf - sp, 2) if perf is not None and sp is not None else None
        # RRG-style coordinates (100 = SPY baseline).
        x = 100 + row["rs_1m"] if row["rs_1m"] is not None else None
        y = 100 + row["rs_1w"] if row["rs_1w"] is not None else None
        row["rs_ratio"] = round(x, 2) if x is not None else None
        row["rs_momentum"] = round(y, 2) if y is not None else None
        if x is not None and y is not None:
            row["quadrant"] = ("leading" if y >= 100 else "weakening") if x >= 100 else (
                "improving" if y >= 100 else "lagging")
        else:
            row["quadrant"] = None
        b = breadth.get(t)
        row["pct_above_20d"] = b["pct_above_20d"] if b else None
        row["pct_above_50d"] = b["pct_above_50d"] if b else None
        row["tags"] = []
        etfs.append(row)

    # Cross-sectional tags.
    for key in ("chg_1d", "chg_1w", "chg_1m"):
        vals = [e for e in etfs if e[key] is not None]
        if vals:
            max_by = max(vals, key=lambda e: e[key])
            min_by = min(vals, key=lambda e: e[key])
            max_by["tags"].append("best_" + key.split("_")[1])
            min_by["tags"].append("worst_" + key.split("_")[1])
    adr_top = sorted((e for e in etfs if e["adr_pct"]), key=lambda e: -e["adr_pct"])[:3]
    for e in adr_top:
        e["tags"].append("high_adr")
    for e in etfs:
        if e["rel_vol"] is not None and e["rel_vol"] >= 1.5:
            e["tags"].append("high_vol_momentum")

    # CCI-34 oscillator per ETF + composite score (0-100):
    #   score = 0.6 * perf_component + 0.4 * cci_component
    # perf_component = min-max normalized weighted perf (15% 1W + 50% 1M + 35% 3M)
    # cci_component  = bullish 100 / neutral 50 / bearish 0 (unknown -> 50)
    cci_map = live_data.fetch_hub_etf_cci([e["ticker"] for e in etfs])
    weighted = {}
    for e in etfs:
        if e["chg_1w"] is not None and e["chg_1m"] is not None and e["chg_3m"] is not None:
            weighted[e["ticker"]] = 0.15 * e["chg_1w"] + 0.50 * e["chg_1m"] + 0.35 * e["chg_3m"]
    wvals = list(weighted.values())
    wmin, wmax = (min(wvals), max(wvals)) if wvals else (0.0, 0.0)
    wspan = wmax - wmin
    for e in etfs:
        c = cci_map.get(e["ticker"]) or {}
        e["cci"] = c.get("cci")
        e["cci_ema"] = c.get("cci_ema")
        e["cci_zone"] = c.get("cci_zone") or "unknown"
        if e["ticker"] in weighted and wspan > 0:
            perf_component = 100.0 * (weighted[e["ticker"]] - wmin) / wspan
        else:
            perf_component = 50.0  # flat range or missing perfs
        cci_component = {"bullish": 100, "neutral": 50, "bearish": 0}.get(e["cci_zone"], 50)
        e["score"] = round(0.6 * perf_component + 0.4 * cci_component, 1)

    # Multi-factor leadership/opportunity model (etf_scoring). Fail soft: on
    # any error (e.g. yfinance down) the legacy 0.6/0.4 score above stays and
    # the new fields are omitted — the frontend then hides the new columns.
    try:
        import etf_scoring
        bars_map = live_data.fetch_hub_etf_bars([e["ticker"] for e in etfs])
        spy_bars = bars_map.get("SPY")
        if spy_bars is not None and any(bars_map.get(e["ticker"]) is not None for e in etfs):
            etf_scoring.score_universe(etfs, bars_map, spy_bars)
            for e in etfs:
                # Backward compat: the frontend "Score" column reads `score`.
                e["score"] = e["leadership_score"]
    except Exception:
        pass

    return {
        "etfs": etfs,
        "universe_size": len(etfs),
        "qualified": sum(1 for e in etfs if e["qualified"]),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "spy": {
            "price": round(num(spy.get("close")), 2) if spy.get("close") else None,
            "chg_1d": spy_perf("change"), "chg_1w": spy_perf("Perf.W"),
            "chg_1m": spy_perf("Perf.1M"), "chg_3m": spy_perf("Perf.3M"),
            "chg_6m": spy_perf("Perf.6M"), "chg_ytd": spy_perf("Perf.YTD"),
            "chg_1y": spy_perf("Perf.Y"),
        },
    }


@app.get("/api/etf-hub")
def etf_hub():
    now = time.time()
    if _etf_hub_cache["data"] is None or now - _etf_hub_cache["at"] >= _ETF_HUB_TTL:
        try:
            _etf_hub_cache["data"] = _etf_hub_payload()
        except Exception:
            _etf_hub_cache["at"] = now  # don't hammer a failing endpoint
            if _etf_hub_cache["data"] is None:
                raise HTTPException(502, "ETF hub data unavailable")
        else:
            _etf_hub_cache["at"] = now
    return _etf_hub_cache["data"]


@app.get("/api/etf-hub/{ticker}/breakdown")
def etf_hub_breakdown(ticker: str):
    """Full score breakdown for one hub ETF — state, type flags, the four
    scores/ranks, the per-factor explainability payload and a human-readable
    list of the top contributors. Served from the cached /api/etf-hub
    payload (no recompute)."""
    ticker = ticker.strip().upper()
    if ticker not in ETF_CATEGORY:
        raise HTTPException(404, "ETF not in hub universe")
    payload = etf_hub()
    row = next((e for e in payload["etfs"] if e["ticker"] == ticker), None)
    if row is None:
        raise HTTPException(404, "ETF not in latest hub payload")
    if "leadership_score" not in row:
        raise HTTPException(404, "score breakdown unavailable (market data offline)")
    import etf_scoring
    return {
        "ticker": ticker,
        "state": row.get("state"),
        "etf_type": row.get("etf_type"),
        "risk_warning": row.get("risk_warning"),
        "scores": {
            "leadership": row["leadership_score"],
            "opportunity": row["opportunity_score"],
            "rotation": row["rotation_score"],
            "risk": row["risk_score"],
        },
        "ranks": {
            "leadership": row["rank_leadership"],
            "opportunity": row["rank_opportunity"],
            "rotation": row["rank_rotation"],
            "risk": row["rank_risk"],
        },
        "factors": row["factors"],
        "explanation": etf_scoring.explain(row),
    }


# Constituents response cache — CCI downloads are expensive, keep 30 min.
_etf_cons_cache = {}
_ETF_CONS_TTL = 1800.0


def _etf_curated_rows(ticker):
    """Fetch metrics for the hand-picked stocks of an ETF and keep only the
    liquid large caps (30d avg volume >= 1M, market cap >= $600M), ordered by
    market cap. Shaped like the local-universe SQL rows."""
    import live_data
    symbols = ETF_TOP_STOCKS.get(ticker) or []
    if not symbols:
        return []
    try:
        raw = live_data._tv_scan_chunk(symbols)
    except Exception:
        return []
    rows = []
    for sym, vals in raw.items():
        m = live_data._tv_row_to_metrics(vals)
        if not m:
            continue
        if (m.get("avg_volume") or 0) < CURATED_MIN_AVG_VOLUME:
            continue
        if (m.get("market_cap_musd") or 0) < CURATED_MIN_MCAP_MUSD:
            continue
        rows.append({"ticker": sym.split(":", 1)[1],
                     "price": m["price"], "chg_1d": m["chg_1d"], "chg_1m": m["chg_1m"],
                     "adr_pct": m["adr_pct"], "pct_from_52w_high": m["pct_from_52w_high"],
                     "market_cap_musd": m["market_cap_musd"]})
    rows.sort(key=lambda r: -(r["market_cap_musd"] or 0))
    return rows


@app.get("/api/etf-hub/{ticker}/constituents")
def etf_hub_constituents(ticker: str):
    ticker = ticker.strip().upper()
    if ticker not in ETF_CATEGORY:
        raise HTTPException(404, "ETF not in hub universe")
    now = time.time()
    hit = _etf_cons_cache.get(ticker)
    if hit and now - hit["at"] < _ETF_CONS_TTL:
        return hit["data"]
    scope = _etf_stock_scope(ticker)
    rows = []
    if scope:
        kind, name = scope
        conn = _mk_conn()
        if kind == "sector":
            rows = conn.execute(
                """SELECT s.ticker, s.price, s.chg_1d, s.chg_1m, s.adr_pct,
                          s.pct_from_52w_high, s.market_cap_musd
                   FROM stock s JOIN sector sec ON sec.id = s.sector_id
                   WHERE sec.name=? AND s.market_cap_musd IS NOT NULL
                   ORDER BY s.market_cap_musd DESC LIMIT 15""", (name,)).fetchall()
        else:
            rows = conn.execute(
                """SELECT ticker, price, chg_1d, chg_1m, adr_pct,
                          pct_from_52w_high, market_cap_musd
                   FROM stock WHERE industry=? AND market_cap_musd IS NOT NULL
                   ORDER BY market_cap_musd DESC LIMIT 15""", (name,)).fetchall()
        conn.close()
        rows = [dict(r) for r in rows]
    # Guarantee at least 5 hand-picked liquid stocks per ETF: fill gaps (or
    # the whole list when nothing is mapped locally) from the curated map.
    if len(rows) < 5:
        have = {r["ticker"] for r in rows}
        fill = [r for r in _etf_curated_rows(ticker) if r["ticker"] not in have]
        rows = rows + fill[:max(0, 8 - len(rows))]
    if not rows:
        return {"stocks": [], "note": f"No constituents available for {ticker} (run Sync Live Data)."}

    total_cap = sum(r["market_cap_musd"] for r in rows) or 1
    stocks = [{
        "ticker": r["ticker"], "name": r["ticker"],
        "weight_pct": round(100.0 * r["market_cap_musd"] / total_cap, 2),
        "price": r["price"], "chg_1d": r["chg_1d"], "chg_1m": r["chg_1m"],
        "adr_pct": r["adr_pct"], "pct_from_52w_high": r["pct_from_52w_high"],
    } for r in rows]

    # Alpha waterfall: contribution of each constituent to 1M performance.
    contribs = sorted(
        ({"ticker": s["ticker"], "contribution": round(s["weight_pct"] * (s["chg_1m"] or 0) / 100.0, 3)}
         for s in stocks),
        key=lambda c: -c["contribution"])
    top_pos = [c for c in contribs if c["contribution"] > 0][:5]
    top_neg = [c for c in contribs if c["contribution"] < 0][-5:]
    top_neg.sort(key=lambda c: c["contribution"])
    covered = {c["ticker"] for c in top_pos + top_neg}
    other = round(sum(c["contribution"] for c in contribs if c["ticker"] not in covered), 3)
    waterfall = {
        "positive": top_pos, "negative": top_neg, "other": other,
        "net": round(sum(c["contribution"] for c in contribs), 3),
    }

    # 30-day sparklines via one batched yfinance download (best effort).
    import live_data
    sparks = {}
    try:
        data = live_data._yf_download_batch([s["ticker"] for s in stocks], period="3mo")
        for sym, df in data.items():
            closes = df["Close"].dropna().tail(30)
            sparks[sym] = [round(float(c), 2) for c in closes]
    except Exception:
        sparks = {}
    for s in stocks:
        s["spark"] = sparks.get(s["ticker"], [])

    # CCI-34 classification per constituent (best effort, one batch download).
    cci_map = live_data.cci_for_symbols([s["ticker"] for s in stocks])
    for s in stocks:
        c = cci_map.get(s["ticker"]) or {}
        s["cci"] = c.get("cci")
        s["cci_zone"] = c.get("cci_zone") or "unknown"

    payload = {"stocks": stocks, "scope": ({"kind": kind, "name": name} if scope else None),
               "waterfall": waterfall, "generated_at": datetime.now().isoformat(timespec="seconds")}
    _etf_cons_cache[ticker] = {"at": now, "data": payload}
    return payload


# --- serve frontend ---
@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
