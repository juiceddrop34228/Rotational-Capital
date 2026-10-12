"""Offline tests for the ETF multi-factor scoring model (backend/etf_scoring.py)
and its wiring into the ETF hub payload (backend/main.py). Synthetic data only,
no network. Run: python -m pytest test_etf_scoring.py -q"""
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, "backend")
import etf_scoring as es


# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------
def _bars(closes, vol=1_000_000.0):
    closes = np.asarray(closes, dtype=float)
    idx = pd.bdate_range("2023-01-02", periods=len(closes))
    return pd.DataFrame({
        "Open": closes, "High": closes * 1.005, "Low": closes * 0.995,
        "Close": closes, "Volume": vol,
    }, index=idx)


def _steady(daily_ret, n=260, start=100.0):
    return [start * (1 + daily_ret) ** i for i in range(n)]


def _row(ticker, closes, spy_closes, category="Sector", rel_vol=1.0):
    def ret(c, n):
        return (c[-1] / c[-1 - n] - 1) * 100
    return {
        "ticker": ticker, "category": category,
        "chg_1w": ret(closes, 5), "chg_1m": ret(closes, 21),
        "chg_3m": ret(closes, 63), "chg_6m": ret(closes, 126),
        "rs_1m": ret(closes, 21) - ret(spy_closes, 21),
        "rs_3m": ret(closes, 63) - ret(spy_closes, 63),
        "rs_6m": ret(closes, 126) - ret(spy_closes, 126),
        "rel_vol": rel_vol,
    }


SPY_CLOSES = _steady(0.0005)
SPY_BARS = _bars(SPY_CLOSES)


# ---------------------------------------------------------------------------
# 1. Percentile scoring: sustained RS beats a one-week spike
# ---------------------------------------------------------------------------
def test_sustained_rs_beats_one_week_spike():
    a_closes = _steady(0.0015)                       # grind higher all year
    b_closes = [100.0] * 254 + [101.5, 103.2, 105.0, 106.6, 108.0, 108.0]  # spike
    rows = [_row("AAA", a_closes, SPY_CLOSES), _row("BBB", b_closes, SPY_CLOSES)]
    bars = {"AAA": _bars(a_closes), "BBB": _bars(b_closes)}
    es.score_universe(rows, bars, SPY_BARS)
    a, b = rows
    assert a["leadership_score"] > b["leadership_score"]
    assert a["rank_leadership"] == 1 and b["rank_leadership"] == 2
    assert a["factors"]["rs"]["percentile"] > b["factors"]["rs"]["percentile"]
    # the spike shows up in B's 1W momentum but not in sustained RS
    assert b["factors"]["momentum"]["inputs"]["chg_1w"] > a["factors"]["momentum"]["inputs"]["chg_1w"]
    assert a["factors"]["rs"]["inputs"]["rs_3m"] > b["factors"]["rs"]["inputs"]["rs_3m"]
    for r in rows:
        for k in ("leadership_score", "opportunity_score", "rotation_score", "risk_score",
                  "rank_leadership", "rank_opportunity", "rank_rotation", "rank_risk",
                  "state", "etf_type", "factors"):
            assert k in r, k
        assert set(r["factors"]) == {"rs", "momentum", "breadth", "trend", "volume",
                                     "consistency", "risk", "opportunity"}
        for d in r["factors"].values():
            assert "score" in d and "weight" in d and "percentile" in d and "inputs" in d
    print("OK sustained-RS percentile test")


# ---------------------------------------------------------------------------
# 2. Extension penalty: opportunity reduced, leadership unchanged
# ---------------------------------------------------------------------------
def test_extension_penalty_reduces_opportunity_not_leadership():
    base = _steady(0.0015)
    ext = base[:-3] + [base[-3] * 1.04, base[-2] * 1.08, base[-1] * 1.12]  # +12% pop
    row_x = _row("XXX", base, SPY_CLOSES)
    row_y = dict(_row("YYY", base, SPY_CLOSES), ticker="YYY")  # identical scanner row
    rows = [row_x, row_y]
    bars = {"XXX": _bars(base), "YYY": _bars(ext)}
    es.score_universe(rows, bars, SPY_BARS)
    x, y = rows
    y_ext = y["factors"]["opportunity"]["inputs"]["extension"]
    assert y_ext >= es.EXT_KNEE + 3  # genuinely extended above the blended SMAs
    assert y["factors"]["opportunity"]["inputs"]["extension_penalty"] > 0
    assert y["opportunity_score"] < x["opportunity_score"] - 3
    # leadership only moves via the small trend/rs-slope components
    assert abs(y["leadership_score"] - x["leadership_score"]) <= 8
    print("OK extension-penalty test")


# ---------------------------------------------------------------------------
# 3. State machine: all seven states
# ---------------------------------------------------------------------------
def test_state_machine():
    base = dict(leadership=50, extension=0.0, rs_3m_pct=50, rs_6m_pct=50,
                trend=50, rotation=50, rs_1m=0.5, above_sma200=True,
                trend_improving=False)
    cases = {
        "Extended":   dict(leadership=70, extension=10.0),
        "Leading":    dict(rs_3m_pct=80, rs_6m_pct=75, trend=70),
        "Emerging":   dict(rotation=80, rs_6m_pct=40, trend_improving=True),
        "Fading":     dict(rs_6m_pct=65, rotation=20),
        "Recovering": dict(above_sma200=False, rotation=65),
        "Lagging":    dict(leadership=20),
        "Neutral":    {},
    }
    for want, over in cases.items():
        got = es.classify_state({**base, **over})
        assert got == want, f"{want}: got {got}"
    print("OK state machine (7 states)")


# ---------------------------------------------------------------------------
# 4. Type flags: leveraged warning + opportunity cap, bond vol tolerance
# ---------------------------------------------------------------------------
def test_type_flags_leveraged_and_bond():
    f = es.etf_type_flags("TQQQ", "Sector")
    assert f["type"] == "leveraged" and f["warnings"]
    assert es.etf_type_flags("SQQQ", "Sector")["type"] == "inverse"
    assert es.etf_type_flags("TLT", "Commodity/Macro")["type"] == "bond"
    assert es.etf_type_flags("EEM", "Commodity/Macro")["type"] == "international"
    assert es.etf_type_flags("XLK", "Sector")["type"] == "sector"

    # Leveraged ETF with a strong tape: leadership high, opportunity capped at 60
    strong = _steady(0.004)
    weak = _steady(-0.001)
    rows = [_row("TQQQ", strong, SPY_CLOSES), _row("XLK", weak, SPY_CLOSES)]
    es.score_universe(rows, {"TQQQ": _bars(strong), "XLK": _bars(weak)}, SPY_BARS)
    tqqq = rows[0]
    assert tqqq["etf_type"] == "leveraged"
    assert tqqq["risk_warning"]
    assert tqqq["opportunity_score"] <= es.OPP_LEVERAGED_CAP
    assert tqqq["factors"]["opportunity"]["inputs"]["leveraged_cap"] is True

    # Bond ETF with the same volatile tape gets a higher (calmer) risk score
    vol_closes = 100 * np.cumprod([1.0] + [1.02 if i % 2 else 0.982 for i in range(1, 260)])
    calm_closes = _steady(0.0005)
    bond_row = _row("TLT", vol_closes, SPY_CLOSES, category="Commodity/Macro")
    eq_row = _row("XLE", vol_closes, SPY_CLOSES, category="Sector")
    calm_row = _row("XLU", calm_closes, SPY_CLOSES, category="Sector")
    rows = [bond_row, eq_row, calm_row]
    es.score_universe(rows, {"TLT": _bars(vol_closes), "XLE": _bars(vol_closes),
                             "XLU": _bars(calm_closes)}, SPY_BARS)
    assert rows[0]["etf_type"] == "bond"
    assert rows[0]["risk_score"] > rows[1]["risk_score"]
    print("OK type flags (leveraged cap, bond tolerance)")


# ---------------------------------------------------------------------------
# 5. Hub payload fallback: no bars -> legacy score, new fields omitted
# ---------------------------------------------------------------------------
def _fake_quotes():
    import live_data as ld
    base = {"close": 100.0, "change": 0.5, "Perf.W": 1.0, "Perf.1M": 2.0,
            "Perf.3M": 6.0, "Perf.6M": 10.0, "Perf.YTD": 8.0, "Perf.Y": 12.0,
            "ADR": 2.0, "volume": 1e6, "average_volume_30d_calc": 1e6,
            "relative_volume_10d_calc": 1.0, "price_52_week_high": 105.0,
            "price_52_week_low": 80.0, "SMA20": 99.0, "SMA50": 97.0,
            "Volatility.D": 1.0, "Volatility.W": 2.0, "Volatility.M": 3.0,
            "description": "Fake ETF", "aum": 1e10}
    out = {}
    for t in ("SPY", "XLK", "XLE"):
        out[t] = {c: base.get(c) for c in ld.ETF_HUB_COLUMNS}
    return out


def _hub_payload_with(monkeypatch, bars_map):
    import live_data as ld
    import main
    monkeypatch.setattr(ld, "fetch_etf_hub_quotes", lambda tickers: _fake_quotes())
    monkeypatch.setattr(ld, "fetch_hub_etf_bars", lambda tickers: bars_map)
    monkeypatch.setattr(ld, "fetch_hub_etf_cci", lambda tickers: {t: None for t in tickers})
    monkeypatch.setattr(main, "_etf_hub_breadth", lambda conn: {})
    monkeypatch.setattr(main, "ETF_CATEGORY",
                        {"SPY": "Broad", "XLK": "Sector", "XLE": "Sector"})
    monkeypatch.setattr(main, "_etf_hub_cache", {"at": 0.0, "data": None})
    return main


def test_no_bars_legacy_fallback(monkeypatch):
    main = _hub_payload_with(monkeypatch, {"SPY": None, "XLK": None, "XLE": None})
    payload = main._etf_hub_payload()
    for e in payload["etfs"]:
        assert "score" in e  # legacy 0.6/0.4 score still populated
        assert "leadership_score" not in e  # new model omitted on fallback
    print("OK legacy fallback (no bars)")


def test_hub_payload_with_bars_and_breakdown(monkeypatch):
    spy = _bars(SPY_CLOSES)
    up, down = _bars(_steady(0.002)), _bars(_steady(-0.001))
    main = _hub_payload_with(monkeypatch, {"SPY": spy, "XLK": up, "XLE": down})
    payload = main._etf_hub_payload()
    for e in payload["etfs"]:
        assert "leadership_score" in e
        assert e["score"] == e["leadership_score"]  # legacy field mirrors leadership
        assert e["rank_leadership"] in (1, 2, 3)
        assert e["state"] in ("Extended", "Leading", "Emerging", "Fading",
                              "Recovering", "Lagging", "Neutral")
    xlk = next(e for e in payload["etfs"] if e["ticker"] == "XLK")
    assert xlk["leadership_score"] > 50  # steady riser vs flat SPY

    bd = main.etf_hub_breakdown("XLK")
    assert bd["ticker"] == "XLK"
    assert set(bd["scores"]) == {"leadership", "opportunity", "rotation", "risk"}
    assert set(bd["ranks"]) == {"leadership", "opportunity", "rotation", "risk"}
    assert set(bd["factors"]) == {"rs", "momentum", "breadth", "trend", "volume",
                                  "consistency", "risk", "opportunity"}
    assert isinstance(bd["explanation"], list) and bd["explanation"]
    with pytest.raises(Exception):
        main.etf_hub_breakdown("NOPE")
    print("OK hub payload + breakdown endpoint")
