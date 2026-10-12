"""
tv_pages.py
Scrapes TradingView's server-rendered market pages so the dashboard's
sector and industry PERFORMANCE numbers are exactly the ones shown on the
website (not recomputed from the scanner API):

- https://www.tradingview.com/markets/stocks-usa/sectorandindustry-sector/
    -> every US sector: Mkt cap, Div yield %, Chg %, Vol, #Industries, #Stocks
- https://www.tradingview.com/markets/stocks-usa/sectorandindustry-sector/<slug>/industries/
    -> every industry inside that sector: Mkt cap, Div yield %, Chg %, Vol, #Stocks

Parsing is structural (data-rowkey attributes, <td> cells, href patterns)
and deliberately avoids the hashed CSS class suffixes, which change
between TradingView deploys.
"""

import html as _html
import re
import time

import requests

BASE_URL = "https://www.tradingview.com"
SECTOR_PAGE_URL = BASE_URL + "/markets/stocks-usa/sectorandindustry-sector/"
SECTOR_INDUSTRIES_URL = SECTOR_PAGE_URL + "{slug}/industries/"

REQUEST_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Gecko/20100101 Firefox/126.0"),
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = 30

_SUFFIX_MULT = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}

_ROW_RE = re.compile(r'<tr[^>]*data-rowkey="([^"]+)"[^>]*>(.*?)</tr>', re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_LINK_RE = re.compile(r'<a[^>]*href="([^"]+)"[^>]*title="([^"]*)"', re.S)


def _clean_text(cell_html):
    txt = _COMMENT_RE.sub("", cell_html)
    txt = _TAG_RE.sub("", txt)
    return txt.replace(" ", " ").strip()


def _parse_number(text):
    """'24.23 T USD' -> 24.23e12 ; '64.58 M' -> 64.58e6 ; '360' -> 360.0"""
    text = text.replace("USD", "").replace(",", "").strip()
    m = re.match(r"^([−\-+]?\d*\.?\d+)\s*([TBMK])?$", text)
    if not m:
        return None
    val = float(m.group(1).replace("−", "-"))
    return val * _SUFFIX_MULT.get(m.group(2) or "", 1.0)


def _parse_pct(text):
    """'+0.34%' -> 0.34 ; '−0.93%' (U+2212) -> -0.93"""
    text = text.replace("−", "-").replace("+", "").replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _parse_rows(html_text, rowkey_prefix):
    """Yield dicts for every table row whose data-rowkey starts with
    rowkey_prefix. The first <td> is the name/link cell; the rest are the
    value cells in page order."""
    for rowkey, row_html in _ROW_RE.findall(html_text):
        if not rowkey.startswith(rowkey_prefix):
            continue
        cells = _CELL_RE.findall(row_html)
        if len(cells) < 2:
            continue
        link = _LINK_RE.search(cells[0])
        href = link.group(1) if link else ""
        name = _html.unescape(link.group(2) if link else _clean_text(cells[0]))
        slug = href.rstrip("/").rsplit("/", 1)[-1] if href else ""
        yield {
            "rowkey": rowkey,
            "name": name,
            "slug": slug,
            "values": [_clean_text(c) for c in cells[1:]],
        }


def parse_sector_page(html_text):
    """Parse the sector listing page -> [{name, slug, market_cap, div_yield_pct,
    change_pct, volume, industries_count, stocks_count}]."""
    out = []
    for row in _parse_rows(html_text, "SECTOR_US:"):
        v = row["values"]
        if len(v) < 6:
            continue
        out.append({
            "name": row["name"],
            "slug": row["slug"],
            "market_cap": _parse_number(v[0]),
            "div_yield_pct": _parse_pct(v[1]),
            "change_pct": _parse_pct(v[2]),
            "volume": _parse_number(v[3]),
            "industries_count": int(_parse_number(v[4]) or 0),
            "stocks_count": int(_parse_number(v[5]) or 0),
        })
    return out


def parse_sector_industries_page(html_text):
    """Parse a sector's industries page -> [{name, slug, market_cap,
    div_yield_pct, change_pct, volume, stocks_count}]."""
    out = []
    for row in _parse_rows(html_text, "INDUSTRY_US:"):
        v = row["values"]
        if len(v) < 5:
            continue
        out.append({
            "name": row["name"],
            "slug": row["slug"],
            "market_cap": _parse_number(v[0]),
            "div_yield_pct": _parse_pct(v[1]),
            "change_pct": _parse_pct(v[2]),
            "volume": _parse_number(v[3]),
            "stocks_count": int(_parse_number(v[4]) or 0),
        })
    return out


def _fetch(url):
    resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def fetch_sector_page():
    """Scrape the TradingView US sector listing page."""
    return parse_sector_page(_fetch(SECTOR_PAGE_URL))


def fetch_sector_industries(slug):
    """Scrape one sector's industries page (every industry in the sector)."""
    return parse_sector_industries_page(_fetch(SECTOR_INDUSTRIES_URL.format(slug=slug)))


def fetch_all_industries_by_sector(sectors, delay=0.3):
    """Scrape the industries page of every sector. `sectors` is the list from
    fetch_sector_page(). Returns {sector_name: [industry dicts]}."""
    out = {}
    for i, s in enumerate(sectors):
        if not s.get("slug"):
            continue
        out[s["name"]] = fetch_sector_industries(s["slug"])
        if i < len(sectors) - 1:
            time.sleep(delay)
    return out
