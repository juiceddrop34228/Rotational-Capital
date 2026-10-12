"""Offline tests for tv_pages.py — parses the saved TradingView market pages
(tv_sector.html = sector listing, tv_sec_ind.html = one sector's industries
page) and checks the extracted numbers against what the site showed.
Run from the repo root: python test_tv_pages.py"""
import os
import sys

sys.path.insert(0, "backend")
import tv_pages

SAMPLE_DIR = os.path.dirname(os.path.abspath(__file__))
if not os.path.exists(os.path.join(SAMPLE_DIR, "tv_sector.html")):
    SAMPLE_DIR = os.path.dirname(SAMPLE_DIR)  # samples live one level up


def _load(name):
    with open(os.path.join(SAMPLE_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_sector_page():
    print("test_sector_page...", end=" ")
    sectors = tv_pages.parse_sector_page(_load("tv_sector.html"))
    assert len(sectors) == 20, f"expected 20 sectors, got {len(sectors)}"
    by_name = {s["name"]: s for s in sectors}
    et = by_name["Electronic Technology"]
    assert et["slug"] == "electronic-technology"
    assert abs(et["change_pct"] - (-0.93)) < 1e-9, et["change_pct"]
    assert abs(et["market_cap"] - 24.23e12) < 1e10, et["market_cap"]
    assert et["industries_count"] == 9
    assert et["stocks_count"] == 360
    ts = by_name["Technology Services"]
    assert abs(ts["change_pct"] - 3.92) < 1e-9, ts["change_pct"]
    print("PASS")


def test_sector_industries_page():
    print("test_sector_industries_page...", end=" ")
    inds = tv_pages.parse_sector_industries_page(_load("tv_sec_ind.html"))
    assert len(inds) == 9, f"expected 9 industries, got {len(inds)}"
    by_name = {i["name"]: i for i in inds}
    semis = by_name["Semiconductors"]
    assert abs(semis["change_pct"] - 0.34) < 1e-9, semis["change_pct"]
    assert semis["stocks_count"] == 102
    # HTML entities must be unescaped
    assert "Aerospace & Defense" in by_name, list(by_name)
    print("PASS")


if __name__ == "__main__":
    test_sector_page()
    test_sector_industries_page()
    print("All tv_pages tests passed.")
