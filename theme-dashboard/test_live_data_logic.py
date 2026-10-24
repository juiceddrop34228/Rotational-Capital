"""Offline tests for live_data.py logic (TradingView row parsing + RS ratings),
using synthetic rows shaped like real scanner API responses.
Run: python3 test_live_data_logic.py"""
import sys

sys.path.insert(0, "backend")
import live_data as ld


def _fake_tv_row(**overrides):
    row = {
        "close": 50.0, "change": 1.2, "Perf.W": 3.5, "Perf.1M": 8.0, "Perf.3M": 25.0,
        "Perf.6M": 40.0, "SMA20": 48.0, "SMA50": 45.0, "SMA200": 40.0,
        "EMA10": 49.0, "EMA20": 48.5, "EMA50": 46.0, "EMA200": 42.0,
        "price_52_week_high": 52.0, "price_52_week_low": 30.0,
        "volume": 3_000_000, "average_volume_10d_calc": 2_000_000,
        "average_volume_30d_calc": 1_900_000, "average_volume_60d_calc": 1_800_000,
        "sector": "Electronic Technology", "industry": "Semiconductors",
        "market_cap_basic": 5_000_000_000,
        "relative_volume_10d_calc": 1.5,
        "High.1M": 51.0, "High.3M": 52.0, "High.6M": 52.0, "Low.1M": 44.0,
        "Volatility.D": 3.2, "ATR": 1.1, "ADR": 2.0, "Recommend.All": 0.25,
    }
    row.update(overrides)
    return [row.get(c) for c in ld.TV_COLUMNS]


def test_tv_row_to_metrics():
    print("test_tv_row_to_metrics...", end=" ")
    m = ld._tv_row_to_metrics(_fake_tv_row())
    assert m is not None
    for k in ["price", "chg_1d", "chg_1w", "chg_1m", "chg_3m", "chg_6m",
              "pct_from_52w_high", "pct_from_52w_low", "volume_ratio",
              "above_20d", "above_50d", "above_200d", "momentum_20d",
              "days_since_new_high", "is_new_high_today",
              "sector", "industry", "market_cap_musd",
              "dist_high_1m", "dist_high_3m", "ext_ema10", "volatility_d", "atr"]:
        assert k in m, f"missing key {k}"
    assert m["price"] == 50.0
    assert m["market_cap_musd"] == 5000.0
    assert m["sector"] == "Electronic Technology"
    assert m["dist_high_1m"] == round((50.0 / 51.0 - 1) * 100, 1)
    assert m["ext_ema10"] == round((50.0 / 49.0 - 1) * 100, 1)
    assert m["above_50d"] is True and m["above_200d"] is True
    assert m["volume_ratio"] == 1.5
    assert m["adr_pct"] == round(2.0 / 50.0 * 100, 2)
    print("OK ->", {k: m[k] for k in ["price", "chg_3m", "dist_high_3m", "ext_ema10"]})


def test_tv_row_no_price():
    print("test_tv_row_no_price...", end=" ")
    assert ld._tv_row_to_metrics(_fake_tv_row(close=None)) is None
    assert ld._tv_row_to_metrics(_fake_tv_row(close=0)) is None
    print("OK (correctly returned None)")


def test_compute_rs_ratings():
    print("test_compute_rs_ratings (IBD-weighted fallback)...", end=" ")
    stocks = [
        {"ticker": "AAA", "chg_3m": 30},
        {"ticker": "BBB", "chg_3m": -10},
        {"ticker": "CCC", "chg_3m": 5},
        {"ticker": "DDD", "chg_3m": 50},
    ]
    out_list, matched = ld.compute_rs_ratings(stocks, {})
    assert matched == 0
    out = {m["ticker"]: m for m in out_list}
    assert out["DDD"]["rs_rating"] == 99  # top performer, capped at 99
    assert out["BBB"]["rs_rating"] < out["CCC"]["rs_rating"] < out["AAA"]["rs_rating"] < out["DDD"]["rs_rating"]
    print("OK ->", {k: v["rs_rating"] for k, v in out.items()})

    # TradingView dataset values win verbatim over the local fallback
    print("test_compute_rs_ratings (TradingView dataset)...", end=" ")
    out_list, matched = ld.compute_rs_ratings(
        [{"ticker": "AAA", "chg_3m": 30}, {"ticker": "ZZZ", "chg_3m": 1}],
        {"AAA": 87.3},
    )
    out = {m["ticker"]: m for m in out_list}
    assert matched == 1 and out["AAA"]["rs_rating"] == 87.3
    assert 1 <= out["ZZZ"]["rs_rating"] <= 99
    print("OK ->", {k: v["rs_rating"] for k, v in out.items()})


def test_score_and_rank_swing():
    print("test_score_and_rank_swing...", end=" ")
    import engine
    base = {
        "market_cap_musd": 5000, "avg_volume": 2_000_000, "price": 50.0,
        "rs_rating": 90, "chg_1w": 2, "chg_1m": 10, "chg_3m": 30,
    }
    strong = dict(base, stock_ticker="AAA")
    mid = dict(base, stock_ticker="BBB", chg_1w=0, chg_1m=4, chg_3m=12)
    weak = dict(base, stock_ticker="CCC", rs_rating=20, chg_1w=-3, chg_1m=-15, chg_3m=-20)
    ranked, excluded = engine.score_and_rank([weak, mid, strong])
    assert excluded == 0 and len(ranked) == 3
    assert [r["stock_ticker"] for r in ranked] == ["AAA", "BBB", "CCC"]
    assert strong["score"] > mid["score"] > weak["score"]
    assert strong["score"] == 100.0  # top of the eligible pool
    assert all(0 <= r["score"] <= 100 for r in ranked)
    assert ranked[0]["classification"] == "leader"
    assert ranked[-1]["classification"] == "laggard"
    print("OK ->", {r["stock_ticker"]: r["score"] for r in ranked})


def test_universal_filters():
    print("test_universal_filters (mcap >= $500M, avg vol >= 1M, ADR >= 2%, price >= $3)...", end=" ")
    import engine
    assert engine.MIN_MARKET_CAP_MUSD == 500.0
    assert engine.MIN_PRICE == 3.0
    ok = {"market_cap_musd": 800, "avg_volume": 2_000_000, "price": 50.0,
          "above_200d": 0, "adr_pct": 4.0}
    small_cap = dict(ok, market_cap_musd=499.9)
    low_vol = dict(ok, avg_volume=999_999)
    low_adr = dict(ok, adr_pct=1.9)
    low_price = dict(ok, price=2.99)
    legacy_no_adr = dict(ok, adr_pct=None)
    kept, excluded = engine.score_and_rank(
        [dict(r, stock_ticker=t, rs_rating=50, chg_1m=1, chg_3m=1,
              pct_from_52w_high=-5, volume_ratio=1.0, above_20d=1, above_50d=1)
         for t, r in [("OK", ok), ("SMALL", small_cap), ("LOWVOL", low_vol),
                      ("LOWADR", low_adr), ("LOWPRICE", low_price),
                      ("LEGACY", legacy_no_adr)]])
    tickers = {r["stock_ticker"] for r in kept}
    assert excluded == 4 and tickers == {"OK", "LEGACY"}, (tickers, excluded)
    print("OK ->", sorted(tickers))


def test_cci_rating():
    print("test_cci_rating...", end=" ")
    from engine import cci_rating
    assert cci_rating(150, 120) == "Bullish (Caution)"  # yellow above blue, both > 100
    assert cci_rating(120, 150) == "Bullish"            # both > 100, yellow below blue
    assert cci_rating(50, 80) == "Neutral"              # yellow 0-100
    assert cci_rating(150, -5) == "Bearish"             # blue below 0
    assert cci_rating(-5, 150) == "Bearish"             # yellow below 0
    assert cci_rating(150, 50) == "Bullish (Caution)"   # yellow > 100, blue 0-100
    assert cci_rating(None, 50) is None
    print("OK")


def test_cap_weighted_average():
    print("test_cap_weighted_average...", end=" ")
    cols = ["close", "change", "Perf.W", "Perf.1M", "Perf.3M", "Perf.6M",
            "market_cap_basic", "sector"]
    close, change, mc = (cols.index(c) for c in ("close", "change", "market_cap_basic"))

    def row(price, chg, cap):
        r = [None] * len(cols)
        r[close], r[change], r[mc] = price, chg, cap
        return r

    rows = [
        row(100.0, 10.0, 90.0),   # 90% of the cap, +10%
        row(50.0, -10.0, 10.0),   # 10% of the cap, -10%
        row(10.0, None, 5.0),     # missing change -> skipped
        row(5.0, 50.0, None),     # missing cap -> skipped
    ]
    w = ld.cap_weighted_average(rows, change, mc)
    assert w == (90 * 10 + 10 * -10) / 100
    assert ld.cap_weighted_average([], change, mc) is None
    assert ld.cap_weighted_average([row(1.0, 2.0, 0.0)], change, mc) is None  # zero weight
    print("OK ->", round(w, 2))


def test_market_scan_filter_accounting():
    print("test_market_scan_filter_accounting...", end=" ")
    # Fake a two-stock scanner universe: one passes ADR >= 2%, one fails it.
    pages = [
        {"totalCount": 3, "data": [
            {"s": "NASDAQ:KEEP", "d": _fake_tv_row(ADR=2.0)},          # 2/50 = 4% -> kept
            {"s": "NYSE:DROP", "d": _fake_tv_row(ADR=0.5)},           # 1% -> dropped (ADR)
            {"s": "NYSE:DROP", "d": _fake_tv_row(ADR=0.5)},           # duplicate row
        ]},
        {"totalCount": 3, "data": []},
    ]
    calls = iter(pages)
    orig_post = ld._tv_post
    ld._tv_post = lambda body, url=ld.TV_SCAN_URL: next(calls)
    try:
        stats = {}
        stocks = ld.fetch_tv_market_scan(stats_out=stats)
    finally:
        ld._tv_post = orig_post
    assert [s["ticker"] for s in stocks] == ["KEEP"]
    assert stats["kept"] == 1 and stats["adr_below_min"] == 1 and stats["duplicates"] == 1
    assert stats["server_total"] == 3 and stats["downloaded"] == 3
    # The sort key must be the stable ticker name, not a live price-derived field.
    print("OK ->", stats)


def test_sector_rotation_scores():
    import engine

    neutral = engine.sector_rotation_scores([{"sector_id": 1}])[1]
    assert neutral["score"] == 50.0
    assert neutral["state"] == "neutral" and neutral["rank_label"] == "Neutral"
    weighted = sum(neutral["components"][key] * weight
                   for key, weight in engine.SECTOR_SCORE_WEIGHTS.items())
    assert round(weighted, 1) == neutral["score"]

    base = {
        "breadth_20": 50, "breadth_50": 50, "breadth_200": 50,
        "breadth_pct": 50, "new_highs_pct": 0, "new_lows_pct": 0,
        "advances": 5, "declines": 5, "ema10_above_20": 1,
        "above_50ema": 1, "top5_persistence": 50, "rank_now": 2,
        "extension": 2, "atr_pct": 1, "volatility": 1,
        "drawdown": -2, "distance_high": -2, "beta": 1,
    }
    leader = dict(base, sector_id=1, perf_1d=2, perf_1w=6, perf_1m=12,
                  perf_3m=25, score_chg_5d=2, rank_chg_5d=1, rs_vs_spy=8,
                  avg_rs=90, rs_chg_5d=1, rs_slope=0.5, breadth_20=85,
                  breadth_50=80, breadth_200=75, breadth_pct=80,
                  new_highs_pct=20, advances=9, declines=1,
                  top5_persistence=100, rank_now=1)
    emerging = dict(base, sector_id=2, perf_1d=1, perf_1w=3, perf_1m=6,
                    perf_3m=10, score_chg_5d=8, rank_chg_5d=4, rs_vs_spy=0,
                    avg_rs=55, rs_chg_5d=4, rs_slope=0.2, breadth_20=65,
                    breadth_50=60, breadth_200=55, breadth_pct=60,
                    new_highs_pct=8, advances=7, declines=3,
                    top5_persistence=20, rank_now=2)
    weak = dict(base, sector_id=3, perf_1d=-2, perf_1w=-5, perf_1m=-10,
                perf_3m=-20, score_chg_5d=-8, rank_chg_5d=-4, rs_vs_spy=-8,
                avg_rs=20, rs_chg_5d=-4, rs_slope=-0.5, breadth_20=20,
                breadth_50=25, breadth_200=30, breadth_pct=25,
                new_lows_pct=20, advances=1, declines=9, ema10_above_20=0,
                above_50ema=0, top5_persistence=0, rank_now=3)
    rows = [leader, emerging, weak]
    scored = engine.sector_rotation_scores(rows)
    assert scored[1]["score"] > scored[2]["score"] > scored[3]["score"]
    assert scored[1]["state"] == "leader"
    assert scored[2]["state"] == "emerging"
    assert scored[3]["state"] == "lagging"
    assert all(0 <= result["score"] <= 100 for result in scored.values())

    extended = engine.sector_rotation_scores([dict(leader, extension=18), emerging, weak])
    assert extended[1]["score"] < scored[1]["score"]
    assert extended[1]["state"] == "leader"

    normal_beta = engine.sector_rotation_scores([leader, weak])[1]
    high_beta = engine.sector_rotation_scores([dict(leader, beta=2.5), weak])[1]
    assert high_beta["score"] == normal_beta["score"]
    weak_high_beta = engine.sector_rotation_scores([leader, dict(weak, beta=2.5)])[3]
    assert weak_high_beta["components"]["risk"] < scored[3]["components"]["risk"]
    print("OK ->", {sid: (r["score"], r["rank_label"]) for sid, r in scored.items()})


if __name__ == "__main__":
    test_tv_row_to_metrics()
    test_tv_row_no_price()
    test_compute_rs_ratings()
    test_score_and_rank_swing()
    test_universal_filters()
    test_cci_rating()
    test_cap_weighted_average()
    test_market_scan_filter_accounting()
    test_sector_rotation_scores()
    print("\nAll offline logic tests passed.")
