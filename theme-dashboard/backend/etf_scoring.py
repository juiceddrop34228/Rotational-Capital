"""
etf_scoring.py
Multi-factor ETF leadership & opportunity model (pure functions, no I/O).

Inputs are the ETF-hub scanner rows built by main._etf_hub_payload plus 1y
daily OHLCV bars per ETF and for SPY (live_data.fetch_hub_etf_bars). Every
factor is percentile-ranked across the scanned universe, mirroring the
composite_factors explainability pattern in engine.score_and_rank. Rows with
missing bars still get scored: bar-derived inputs fall back to a neutral 50th
percentile so the scanner-only fields keep working.
"""

import math
import statistics

# ---------------------------------------------------------------------------
# ETF type classification
# ---------------------------------------------------------------------------
LEVERAGED_ETFS = {
    "TQQQ", "SOXL", "UPRO", "TNA", "LABU", "FAS", "NUGT", "JNUG", "TECL",
    "QLD", "SSO", "UDOW", "SQQQ", "SOXS", "SPXU", "UVXY", "TZA", "LABD",
    "FAZ", "DUST", "JDST", "TECS", "QID", "SDS", "SDOW",
}
INVERSE_ETFS = {
    "SQQQ", "SOXS", "SPXU", "SH", "PSQ", "DOG", "SDS", "QID", "SDOW",
    "TZA", "FAZ", "UVXY",
}
BOND_ETFS = {
    "TLT", "IEF", "SHY", "AGG", "BND", "LQD", "HYG", "JNK", "TIP", "MUB",
    "BIL", "SGOV", "IEI", "TLH", "EMB", "VCIT", "BNDX", "GOVT",
}
INTERNATIONAL_ETFS = {
    "EEM", "EFA", "VEA", "VWO", "IEMG", "IEFA", "EWJ", "EWZ", "FXI",
    "INDA", "EWG", "EWU", "EWA", "EWC",
}

_CATEGORY_TYPE = {
    "Broad": "broad",
    "Sector": "sector",
    "Thematic": "thematic",
    "Industry": "industry",
    "Commodity/Macro": "commodity",
}

# ---------------------------------------------------------------------------
# Model constants
# ---------------------------------------------------------------------------
# Breadth (% of constituent stocks above their 50-day SMA) and performance
# (rs + momentum) dominate the score with equal weight (0.35 + 0.35 = 0.70).
LEADERSHIP_WEIGHTS = {
    "rs": 0.20, "momentum": 0.15, "breadth": 0.35,
    "trend": 0.15, "volume": 0.05, "consistency": 0.10,
}
# Extension penalty knee (mirrors engine.score_and_rank's ext penalty shape):
# no penalty under EXT_KNEE % above the blended SMA distance, then linear.
EXT_KNEE = 4.0
EXT_SLOPE = 3.0
EXT_CAP = 30.0
EXT_STATE_THRESHOLD = 8.0   # |extension| that marks a leader "Extended"
PULLBACK_BONUS = 10.0       # constructive pullback: above rising SMA50, near SMA20
BREAKOUT_BONUS = 10.0       # early breakout: within 3% of 20d high on rising volume
OPP_LEVERAGED_CAP = 60.0    # hard opportunity cap for leveraged/inverse ETFs
RISK_LEVERAGED_SURCHARGE = 15.0


def etf_type_flags(ticker, category):
    """Classify an ETF: {type, warnings}. Leveraged/inverse get a risk
    warning; bond/international get wider volatility tolerance downstream."""
    t = (ticker or "").upper()
    warnings = []
    if t in INVERSE_ETFS:
        etype = "inverse"
    elif t in LEVERAGED_ETFS:
        etype = "leveraged"
    elif t in BOND_ETFS:
        etype = "bond"
    elif t in INTERNATIONAL_ETFS:
        etype = "international"
    else:
        etype = _CATEGORY_TYPE.get(category, "thematic")
    if etype == "leveraged":
        warnings.append("Leveraged ETF: amplified daily moves, opportunity score capped at 60.")
    if etype == "inverse":
        warnings.append("Inverse ETF: moves against its benchmark, opportunity score capped at 60.")
    if etype == "bond":
        warnings.append("Bond fund: structurally low volatility — volatility risk is de-emphasized.")
    return {"type": etype, "warnings": warnings}


# ---------------------------------------------------------------------------
# Small numeric helpers (no engine import — this module stays standalone)
# ---------------------------------------------------------------------------
def _percentile_rank(values, v):
    if not values:
        return 50.0
    below = sum(1 for x in values if x <= v)
    return round(below / len(values) * 100, 1)


def _lin_slope(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    mx = (n - 1) / 2
    my = sum(vals) / n
    num = sum((i - mx) * (v - my) for i, v in enumerate(vals))
    den = sum((i - mx) ** 2 for i in range(n)) or 1
    return num / den


def _sma(series, n):
    if len(series) < n:
        return None
    return sum(series[-n:]) / n


def _r(v, d=2):
    return round(float(v), d) if v is not None else None


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# Raw factor inputs per ETF from its scanner row + daily bars
# ---------------------------------------------------------------------------
def compute_factors(row, bars=None, spy_bars=None, universe_stats=None):
    """Raw factor inputs for one ETF. `bars`/`spy_bars` are pandas DataFrames
    with High/Low/Close/Volume columns (1y daily) or None. Any input that
    cannot be computed is None and scores at the neutral percentile later."""
    f = {
        "rs_1m": row.get("rs_1m"), "rs_3m": row.get("rs_3m"), "rs_6m": row.get("rs_6m"),
        "chg_1w": row.get("chg_1w"), "chg_1m": row.get("chg_1m"),
        "chg_3m": row.get("chg_3m"), "rel_vol": row.get("rel_vol"),
        "rs_slope_60d": None, "mom_accel": None,
        "dist_sma10": None, "dist_sma20": None, "dist_sma50": None, "dist_sma200": None,
        "sma20_slope": None, "sma50_slope": None,
        "ma_align": None, "pct_above_sma50": None, "above_sma200": None,
        "pct_above_50d": row.get("pct_above_50d"),
        "vol_trend": None, "up_down_vol": None,
        "pct_pos_days_60": None, "pct_pos_weeks_13": None,
        "realized_vol_30d": None, "max_drawdown_6m": None,
        "dist_high_20d": None, "extension": None,
    }
    if bars is None or not len(bars):
        return f
    try:
        closes = [float(x) for x in bars["Close"].dropna().tolist()]
    except Exception:
        return f
    if len(closes) < 25:
        return f
    price = closes[-1]

    try:
        vols = [float(x) for x in bars["Volume"].fillna(0).tolist()]
    except Exception:
        vols = [0.0] * len(closes)

    # --- trend: MAs, slopes, alignment ---
    sma10, sma20, sma50 = _sma(closes, 10), _sma(closes, 20), _sma(closes, 50)
    sma200 = _sma(closes, 200)
    if sma10:
        f["dist_sma10"] = _r((price / sma10 - 1) * 100)
    if sma20:
        f["dist_sma20"] = _r((price / sma20 - 1) * 100)
    if sma50:
        f["dist_sma50"] = _r((price / sma50 - 1) * 100)
    if sma200:
        f["dist_sma200"] = _r((price / sma200 - 1) * 100)
        f["above_sma200"] = bool(price > sma200)
    if len(closes) >= 40 and sma20:
        sma20_series = [sum(closes[i - 20:i]) / 20 for i in range(20, len(closes) + 1)]
        f["sma20_slope"] = _r(_lin_slope(sma20_series[-20:]) / price * 100, 3)  # %/day
    if len(closes) >= 70 and sma50:
        sma50_series = [sum(closes[i - 50:i]) / 50 for i in range(50, len(closes) + 1)]
        f["sma50_slope"] = _r(_lin_slope(sma50_series[-20:]) / price * 100, 3)
    if sma20 and sma50 and sma200:
        f["ma_align"] = _r(100.0 * (int(sma20 > sma50) + int(sma50 > sma200)
                                    + int(price > sma50)) / 3, 1)
    if sma50 and len(closes) >= 110:
        sma50_full = [sum(closes[i - 50:i]) / 50 for i in range(50, len(closes) + 1)]
        tail_c, tail_s = closes[-60:], sma50_full[-60:]
        f["pct_above_sma50"] = _r(100.0 * sum(1 for c, s in zip(tail_c, tail_s) if c > s)
                                  / len(tail_c), 1)

    # --- volume ---
    if len(vols) >= 60 and sum(vols[-60:-20]) > 0:
        avg20 = sum(vols[-20:]) / 20
        avg60 = sum(vols[-60:]) / 60
        f["vol_trend"] = _r(avg20 / avg60, 3) if avg60 else None
    if len(vols) >= 21:
        up = sum(vols[i] for i in range(-20, 0) if closes[i] > closes[i - 1])
        dn = sum(vols[i] for i in range(-20, 0) if closes[i] < closes[i - 1])
        f["up_down_vol"] = _r(up / dn, 3) if dn else (2.0 if up else 1.0)

    # --- consistency ---
    rets = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes)) if closes[i - 1]]
    if len(rets) >= 60:
        f["pct_pos_days_60"] = _r(100.0 * sum(1 for x in rets[-60:] if x > 0) / 60, 1)
    if len(rets) >= 30:
        f["realized_vol_30d"] = _r(statistics.pstdev(rets[-30:]) * math.sqrt(252) * 100, 2)
    if len(closes) >= 66:
        weeks = closes[-66::5]
        wrets = [(weeks[i] / weeks[i - 1] - 1) for i in range(1, len(weeks)) if weeks[i - 1]]
        if wrets:
            f["pct_pos_weeks_13"] = _r(100.0 * sum(1 for x in wrets if x > 0) / len(wrets), 1)
    if len(closes) >= 126:
        window = closes[-126:]
        peak, mdd = window[0], 0.0
        for c in window:
            peak = max(peak, c)
            mdd = min(mdd, c / peak - 1)
        f["max_drawdown_6m"] = _r(mdd * 100, 2)

    # --- extension (blended distance above SMA10/20/50) ---
    parts = [(f["dist_sma10"], 0.3), (f["dist_sma20"], 0.5), (f["dist_sma50"], 0.2)]
    avail = [(v, w) for v, w in parts if v is not None]
    if avail:
        wsum = sum(w for _, w in avail)
        f["extension"] = _r(sum(v * w for v, w in avail) / wsum, 2)

    # --- 20d high distance (breakout detection) ---
    if len(closes) >= 20:
        hi20 = max(float(x) for x in bars["High"].dropna().tolist()[-20:]) if "High" in bars else max(closes[-20:])
        f["dist_high_20d"] = _r((price / hi20 - 1) * 100, 2) if hi20 else None

    # --- RS vs SPY from bars: ratio slope + momentum acceleration ---
    if spy_bars is not None and len(spy_bars):
        try:
            spy_closes = [float(x) for x in spy_bars["Close"].dropna().tolist()]
            n = min(len(closes), len(spy_closes))
            if n >= 65:
                ec, sc = closes[-n:], spy_closes[-n:]
                ratio = [e / s for e, s in zip(ec[-60:], sc[-60:]) if s]
                if ratio:
                    mean_r = sum(ratio) / len(ratio)
                    f["rs_slope_60d"] = _r(_lin_slope(ratio) / mean_r * 100, 4)  # %/day
                # momentum acceleration: recent 1M RS minus prior 1M RS
                rs_recent = (ec[-1] / ec[-22] - 1) - (sc[-1] / sc[-22] - 1)
                rs_prior = (ec[-22] / ec[-43] - 1) - (sc[-22] / sc[-43] - 1)
                f["mom_accel"] = _r((rs_recent - rs_prior) * 100, 2)
        except Exception:
            pass
    return f


# ---------------------------------------------------------------------------
# State classification (priority order per plan)
# ---------------------------------------------------------------------------
def classify_state(m):
    """m: {leadership, extension, rs_3m_pct, rs_6m_pct, trend, rotation,
    rs_1m, above_sma200, trend_improving}."""
    if m["leadership"] >= 60 and abs(m.get("extension") or 0) >= EXT_STATE_THRESHOLD:
        return "Extended"
    if m.get("rs_3m_pct", 0) >= 70 and m.get("rs_6m_pct", 0) >= 70 and m["trend"] >= 60:
        return "Leading"
    if m["rotation"] >= 70 and m.get("rs_6m_pct", 100) < 50 and m.get("trend_improving"):
        return "Emerging"
    if m.get("rs_6m_pct", 0) >= 60 and (m["rotation"] <= 30 or (m.get("rs_1m") or 0) < 0):
        return "Fading"
    if not m.get("above_sma200", True) and m["rotation"] >= 60:
        return "Recovering"
    if m["leadership"] <= 30:
        return "Lagging"
    return "Neutral"


# ---------------------------------------------------------------------------
# Universe scoring
# ---------------------------------------------------------------------------
def _blend(parts):
    """Weighted average of (value, weight) parts; None -> neutral 50."""
    return sum((v if v is not None else 50.0) * w for v, w in parts)


def score_universe(rows, bars_map=None, spy_bars=None):
    """Augment each hub row with leadership/opportunity/rotation/risk scores,
    ranks, state, etf_type, risk_warning and the full factors explainability
    payload. Mutates and returns `rows`. Pure: no I/O."""
    bars_map = bars_map or {}
    raw = {}
    flags = {}
    for row in rows:
        t = row["ticker"]
        raw[t] = compute_factors(row, bars_map.get(t), spy_bars)
        flags[t] = etf_type_flags(t, row.get("category"))

    def pctl(key, transform=None):
        vals = {}
        for t, f in raw.items():
            v = f.get(key)
            if v is not None and transform:
                v = transform(v)
            vals[t] = v
        have = sorted(v for v in vals.values() if v is not None)
        return {t: (_percentile_rank(have, v) if v is not None else 50.0)
                for t, v in vals.items()}

    p = {k: pctl(k) for k in (
        "rs_3m", "rs_6m", "rs_slope_60d", "chg_1w", "chg_1m", "chg_3m",
        "mom_accel", "dist_sma50", "sma20_slope", "sma50_slope",
        "rel_vol", "vol_trend", "up_down_vol",
        "pct_pos_days_60", "pct_pos_weeks_13", "pct_above_50d")}
    p["neg_vol"] = pctl("realized_vol_30d", transform=lambda v: -v)
    p["abs_dd"] = pctl("max_drawdown_6m", transform=abs)
    p["neg_rs_1m"] = pctl("rs_1m", transform=lambda v: -v)
    p["gap_1w_3m"] = {t: p["chg_1w"][t] - p["chg_3m"][t] for t in raw}
    gap_vals = sorted(p["gap_1w_3m"].values())
    p["gap_1w_3m"] = {t: _percentile_rank(gap_vals, v) for t, v in p["gap_1w_3m"].items()}

    for row in rows:
        t = row["ticker"]
        f, fl = raw[t], flags[t]
        rs_pct = _blend([(p["rs_3m"][t], 0.35), (p["rs_6m"][t], 0.35),
                         (p["rs_slope_60d"][t], 0.30)])
        mom_pct = _blend([(p["chg_1w"][t], 0.30), (p["chg_1m"][t], 0.40),
                          (p["mom_accel"][t], 0.30)])
        trend_pct = _blend([(p["dist_sma50"][t], 0.25), (p["sma20_slope"][t], 0.20),
                            (p["sma50_slope"][t], 0.15), (f["ma_align"], 0.20),
                            (f["pct_above_sma50"], 0.20)])
        vol_pct = _blend([(p["rel_vol"][t], 0.50), (p["vol_trend"][t], 0.25),
                          (p["up_down_vol"][t], 0.25)])
        cons_pct = _blend([(p["pct_pos_days_60"][t], 0.35), (p["pct_pos_weeks_13"][t], 0.35),
                           (p["neg_vol"][t], 0.30)])
        # Breadth: % of the ETF's constituent stocks above their 50-day SMA
        # (from the ETF hub breadth map; None -> neutral 50).
        breadth_pct = _blend([(p["pct_above_50d"][t], 1.0)])

        leadership = _clamp(sum(LEADERSHIP_WEIGHTS[k] * v for k, v in (
            ("rs", rs_pct), ("momentum", mom_pct), ("breadth", breadth_pct),
            ("trend", trend_pct), ("volume", vol_pct), ("consistency", cons_pct))))

        ext = f["extension"] if f["extension"] is not None else 0.0
        penalty = min(EXT_CAP, max(0.0, (ext - EXT_KNEE) * EXT_SLOPE))
        bonus = 0.0
        sma50_rising = (f["sma50_slope"] or 0) > 0
        if (f["dist_sma50"] or -999) > 0 and sma50_rising \
                and f["dist_sma20"] is not None and abs(f["dist_sma20"]) <= 3:
            bonus = PULLBACK_BONUS
        if f["dist_high_20d"] is not None and f["dist_high_20d"] >= -3 \
                and (f["vol_trend"] or 0) > 1.1:
            bonus = max(bonus, BREAKOUT_BONUS)
        opportunity = _clamp(leadership - penalty + bonus)
        capped = False
        if fl["type"] in ("leveraged", "inverse"):
            opportunity = min(opportunity, OPP_LEVERAGED_CAP)
            capped = True

        rotation = _clamp(0.40 * p["mom_accel"][t] + 0.30 * p["rs_slope_60d"][t]
                          + 0.30 * p["gap_1w_3m"][t])

        # riskiness: high vol, deep drawdown, downtrend, negative RS momentum
        downtrend = 100.0 if ((f["dist_sma50"] or 0) < 0 and (f["sma50_slope"] or 0) < 0) else 0.0
        vol_risk = 100.0 - p["neg_vol"][t] if f["realized_vol_30d"] is not None else 50.0
        if fl["type"] in ("bond", "international"):
            vol_risk *= 0.5  # structurally lower vol -> wider tolerance
        risk_pen = (0.35 * vol_risk + 0.35 * p["abs_dd"][t]
                    + 0.15 * downtrend + 0.15 * p["neg_rs_1m"][t])
        surcharge = RISK_LEVERAGED_SURCHARGE if fl["type"] in ("leveraged", "inverse") else 0.0
        risk = _clamp(100.0 - risk_pen - surcharge)

        state = classify_state({
            "leadership": leadership, "extension": ext,
            "rs_3m_pct": p["rs_3m"][t], "rs_6m_pct": p["rs_6m"][t],
            "trend": trend_pct, "rotation": rotation, "rs_1m": f["rs_1m"],
            "above_sma200": f["above_sma200"] if f["above_sma200"] is not None else True,
            "trend_improving": (f["sma20_slope"] or 0) > 0,
        })

        row["leadership_score"] = round(leadership, 1)
        row["opportunity_score"] = round(opportunity, 1)
        row["rotation_score"] = round(rotation, 1)
        row["risk_score"] = round(risk, 1)
        row["state"] = state
        row["etf_type"] = fl["type"]
        row["risk_warning"] = fl["warnings"][0] if fl["warnings"] else None
        row["factors"] = {
            "rs": {"score": round(rs_pct, 1), "weight": LEADERSHIP_WEIGHTS["rs"],
                   "percentile": round(rs_pct, 1),
                   "inputs": {k: f[k] for k in ("rs_1m", "rs_3m", "rs_6m", "rs_slope_60d")}},
            "momentum": {"score": round(mom_pct, 1), "weight": LEADERSHIP_WEIGHTS["momentum"],
                         "percentile": round(mom_pct, 1),
                         "inputs": {k: f[k] for k in ("chg_1w", "chg_1m", "mom_accel")}},
            "breadth": {"score": round(breadth_pct, 1), "weight": LEADERSHIP_WEIGHTS["breadth"],
                        "percentile": round(breadth_pct, 1),
                        "inputs": {"pct_above_50d": f["pct_above_50d"]}},
            "trend": {"score": round(trend_pct, 1), "weight": LEADERSHIP_WEIGHTS["trend"],
                      "percentile": round(trend_pct, 1),
                      "inputs": {k: f[k] for k in ("dist_sma10", "dist_sma20", "dist_sma50",
                                                   "dist_sma200", "sma20_slope", "sma50_slope",
                                                   "ma_align", "pct_above_sma50")}},
            "volume": {"score": round(vol_pct, 1), "weight": LEADERSHIP_WEIGHTS["volume"],
                       "percentile": round(vol_pct, 1),
                       "inputs": {k: f[k] for k in ("rel_vol", "vol_trend", "up_down_vol")}},
            "consistency": {"score": round(cons_pct, 1), "weight": LEADERSHIP_WEIGHTS["consistency"],
                            "percentile": round(cons_pct, 1),
                            "inputs": {k: f[k] for k in ("pct_pos_days_60", "pct_pos_weeks_13",
                                                         "realized_vol_30d", "max_drawdown_6m")}},
            "risk": {"score": round(risk, 1), "weight": None,
                     "percentile": round(100 - risk_pen, 1),
                     "inputs": {"realized_vol_30d": f["realized_vol_30d"],
                                "max_drawdown_6m": f["max_drawdown_6m"],
                                "downtrend": downtrend,
                                "rs_1m": f["rs_1m"],
                                "leveraged_surcharge": surcharge}},
            "opportunity": {"score": round(opportunity, 1), "weight": None, "percentile": None,
                            "inputs": {"extension": f["extension"],
                                       "extension_penalty": round(penalty, 1),
                                       "setup_bonus": round(bonus, 1),
                                       "leveraged_cap": capped}},
        }

    for field, out_field in (("leadership_score", "rank_leadership"),
                             ("opportunity_score", "rank_opportunity"),
                             ("rotation_score", "rank_rotation"),
                             ("risk_score", "rank_risk")):
        ordered = sorted(rows, key=lambda r: (-r[field], r["ticker"]))
        for i, r in enumerate(ordered):
            r[out_field] = i + 1
    return rows


# ---------------------------------------------------------------------------
# Human-readable explanation of the score breakdown
# ---------------------------------------------------------------------------
def explain(row):
    """Bullet list of the top positive/negative leadership contributors plus
    state, penalties and type warnings. Works on a row scored by
    score_universe (as served from the hub cache)."""
    f = row.get("factors") or {}
    out = []

    def _ord(n):
        n = int(round(n))
        suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return "%d%s" % (n, suf)

    contrib = sorted(
        ((name, d["weight"] * (d["percentile"] or 50.0), d) for name, d in f.items()
         if d.get("weight")),
        key=lambda x: -x[1])
    for name, _, d in contrib[:2]:
        out.append("%s: %s percentile (weight %.0f%%) is a top contributor."
                   % (name.capitalize(), _ord(d["percentile"] or 0), d["weight"] * 100))
    for name, _, d in contrib[-2:]:
        out.append("%s: %s percentile (weight %.0f%%) drags the leadership score."
                   % (name.capitalize(), _ord(d["percentile"] or 0), d["weight"] * 100))
    opp = f.get("opportunity", {}).get("inputs", {})
    if opp.get("extension_penalty"):
        out.append("Extended %.1f%% above the blended SMA10/20/50 — opportunity penalty -%s."
                   % (opp.get("extension") or 0, opp["extension_penalty"]))
    if opp.get("setup_bonus"):
        out.append("Constructive setup (pullback to support or early breakout): +%s opportunity."
                   % opp["setup_bonus"])
    if opp.get("leveraged_cap"):
        out.append("Opportunity score capped at 60 for leveraged/inverse ETFs.")
    if row.get("risk_warning"):
        out.append(row["risk_warning"])
    if row.get("state"):
        out.append("State: %s." % row["state"])
    return out
