"""
engine.py
Sector rotation analytics engine.

Sector definitions are represented by a primary ETF and optional secondary ETFs.
The universal filter (market cap >= $500M, avg 30d volume >= 1M shares,
ADR >= 2%) is applied everywhere a stock is ranked or displayed.

NOTE: this module ships with a deterministic synthetic data generator so the app
is fully runnable offline.  Swap generate_universe() for live data from
live_data.py to pull real metrics from the TradingView scanner (free, no API key).
"""

import random
import sqlite3
import math
import os
from datetime import date, datetime, timedelta

# THEMES_DB_PATH override is used by the Vercel deployment (api/index.py),
# where only /tmp is writable. Locally this resolves to the same path as before.
DB_PATH = os.environ.get(
    "THEMES_DB_PATH", os.path.join(os.path.dirname(__file__), "themes.db"))

# ---------------------------------------------------------------------------
# Universal filters applied everywhere a stock is ranked or displayed
# ---------------------------------------------------------------------------
MIN_MARKET_CAP_MUSD = 500.0     # $500M (soft baseline for the EP universe)
MIN_AVG_VOLUME = 1_000_000      # 1M shares average daily volume (30d)
MIN_ADR_PCT = 2.0               # average day range >= 2% of price
MIN_PRICE = 3.0                 # price >= $3

random.seed(42)

# Sector color palette — vivid, clearly distinct neon hues (cyberpunk theme).
SECTOR_COLORS = [
    "#00e5ff",  # Information Technology — cyan
    "#ffd166",  # Financials — gold
    "#7dff62",  # Health Care — lime
    "#ff9f1c",  # Energy — orange
    "#b388ff",  # Industrials — violet
    "#ff4fd8",  # Consumer Discretionary — magenta
    "#8ecae6",  # Consumer Staples — ice blue
    "#ff5d3a",  # Materials — vermilion
    "#4cc9f0",  # Utilities — sky
    "#f72585",  # Communication Services — hot pink
    "#90f1ef",  # Real Estate — pale teal
    "#00ff9c",  # Semiconductors — neon green
    "#caff33",  # Biotechnology — acid green
    "#ff2e63",  # Cybersecurity — neon red
    "#a3e635",  # Homebuilders — chartreuse
]

# Sectors are TradingView's own sector classification (the scanner API's
# "sector" column). "ticker" is a short slug (max 4 chars) used as the sector's
# key in the holding/etf tables -- there is no underlying ETF anymore.
SECTOR_DEFS = [
    {"name": "Electronic Technology",  "ticker": "ETEC", "sub": "Technology", "tags": "semis,hardware,electronics"},
    {"name": "Technology Services",    "ticker": "TSVC", "sub": "Technology", "tags": "software,internet,it-services"},
    {"name": "Health Technology",      "ticker": "HLTH", "sub": "Defensive",  "tags": "pharma,biotech,medical-devices"},
    {"name": "Health Services",        "ticker": "HSVC", "sub": "Defensive",  "tags": "hospitals,health-services"},
    {"name": "Finance",                "ticker": "FIN",  "sub": "Cyclical",   "tags": "banks,insurance,capital-markets"},
    {"name": "Energy Minerals",        "ticker": "ENRG", "sub": "Cyclical",   "tags": "oil,gas,coal"},
    {"name": "Non-Energy Minerals",    "ticker": "NMIN", "sub": "Cyclical",   "tags": "metals,mining,steel"},
    {"name": "Producer Manufacturing", "ticker": "PMFG", "sub": "Cyclical",   "tags": "machinery,aerospace,electrical"},
    {"name": "Industrial Services",    "ticker": "ISVC", "sub": "Cyclical",   "tags": "engineering,construction,waste"},
    {"name": "Consumer Durables",      "ticker": "CDUR", "sub": "Cyclical",   "tags": "autos,homebuilding,appliances"},
    {"name": "Consumer Non-Durables",  "ticker": "CNDU", "sub": "Defensive",  "tags": "food,beverages,household"},
    {"name": "Consumer Services",      "ticker": "CSVC", "sub": "Cyclical",   "tags": "leisure,lodging,restaurants"},
    {"name": "Commercial Services",    "ticker": "COMS", "sub": "Cyclical",   "tags": "business-services,staffing"},
    {"name": "Distribution Services",  "ticker": "DIST", "sub": "Cyclical",   "tags": "wholesale,distributors"},
    {"name": "Retail Trade",           "ticker": "RET",  "sub": "Cyclical",   "tags": "retail,e-commerce"},
    {"name": "Communications",         "ticker": "COMM", "sub": "Communication", "tags": "telecom,media"},
    {"name": "Utilities",              "ticker": "UTIL", "sub": "Defensive",  "tags": "electric,gas,water"},
    {"name": "Process Industries",     "ticker": "PROC", "sub": "Cyclical",   "tags": "chemicals,paper,containers"},
    {"name": "Transportation",         "ticker": "TRAN", "sub": "Cyclical",   "tags": "airlines,rail,trucking,shipping"},
    {"name": "Miscellaneous",          "ticker": "MISC", "sub": "Cyclical",   "tags": "other,diversified"},
]

BENCHMARK_TICKER = "SPY"

# ---------------------------------------------------------------------------
# Sector -> proxy ETF mapping
#
# Each of the 20 TradingView sectors is mapped to ONE liquid, widely used
# sector ETF with AUM >= ~$1B. The "sector CCI" used by every strategy engine
# is the CCI(34) of that ETF (not a custom sector index): price data comes
# from the TradingView scanner, and the CCI(34)/EMA(13) oscillator history is
# computed the same way as the index CCI (see live_data.fetch_sector_etf_cci).
# Sector level only — industries inside a sector get no ETF proxy.
# ---------------------------------------------------------------------------
SECTOR_ETF_MAP = {
    "Electronic Technology":  "SMH",   # VanEck Semiconductor (~$20B+)
    "Technology Services":    "IGV",   # iShares Expanded Tech-Software (~$10B)
    "Health Technology":      "XBI",   # SPDR S&P Biotech (~$7B)
    "Health Services":        "XLV",   # Health Care Select Sector SPDR (~$35B)
    "Finance":                "XLF",   # Financial Select Sector SPDR (~$40B)
    "Energy Minerals":        "XLE",   # Energy Select Sector SPDR (~$25B)
    "Non-Energy Minerals":    "XME",   # SPDR S&P Metals & Mining (~$2-3B)
    "Producer Manufacturing": "XLI",   # Industrial Select Sector SPDR (~$20B)
    "Industrial Services":    "IFRA",  # iShares U.S. Infrastructure (~$4.6B)
    "Consumer Durables":      "XHB",   # SPDR S&P Homebuilders (~$1.5B)
    "Consumer Non-Durables":  "XLP",   # Consumer Staples Select Sector SPDR (~$15B)
    "Consumer Services":      "IYC",   # iShares U.S. Consumer Services (~$1.2-1.6B)
    "Commercial Services":    "VIS",   # Vanguard Industrials (~$5B)
    "Distribution Services":  "AIRR",  # First Trust RBA American Industrial Renaissance (~$2-3B)
    "Retail Trade":           "XLY",   # Consumer Discretionary Select Sector SPDR (~$4-5B)
    "Communications":         "XLC",   # Communication Services Select Sector SPDR (~$20B)
    "Utilities":              "XLU",   # Utilities Select Sector SPDR (~$15B)
    "Process Industries":     "XLB",   # Materials Select Sector SPDR (~$5B)
    "Transportation":         "IYT",   # iShares U.S. Transportation (~$1B)
    "Miscellaneous":          "SPY",   # broad-market proxy
}

# ---------------------------------------------------------------------------
# Industry -> benchmark mapping
#
# Every industry gets ONE benchmark, resolved by this rule (see
# main.py:_industry_tv_symbol):
#   1. If the industry is in INDUSTRY_ETF_MAP below, chart that ETF. Only
#      ETFs that closely represent the specific industry are listed here
#      (SMH for Semiconductors, XBI for Biotechnology, KRE for Regional
#      Banks, ...). Broad sector ETFs (XLY, XLK, XLF, XLP, XLE, XLI, XLB,
#      XLC, XLV, XLU-sector-wide use, IYT, VIS, SPY, ...) are deliberately
#      NOT used as industry benchmarks — a sector ETF is not an industry.
#   2. Otherwise the backend builds a TradingView synthetic index: an
#      equal-weight arithmetic expression over the industry's top
#      INDUSTRY_CUSTOM_INDEX_SIZE constituents by market cap (passing the
#      universal filters), e.g. "AAPL/5+MSFT/5+NVDA/5+AVGO/5+CRM/5".
#   3. Fewer than IND_MIN_STOCKS filtered constituents -> no benchmark.
#
# The industry CCI used by the industry leadership score is the CCI(34) of
# the mapped ETF; industries without a mapped ETF fall back to their parent
# sector's ETF CCI (CCI only — never the benchmark chart).
# Keys are TradingView's own industry names (plus the synthetic demo names
# from INDUSTRY_POOL so demo mode behaves the same way).
#
# To extend: add a line here when a dedicated industry ETF exists. Nothing
# else to change — unmapped industries automatically get a custom index.
# ---------------------------------------------------------------------------

# Number of top-market-cap constituents in an equal-weight custom index.
# 5 keeps the TradingView expression short (fast to load/compute) while
# still representing the industry through its leaders.
INDUSTRY_CUSTOM_INDEX_SIZE = 5

INDUSTRY_ETF_MAP = {
    # --- TradingView live industry names (dedicated industry ETFs only) ---
    "Semiconductors":                 "SMH",   # VanEck Semiconductor
    "Electronic Production Equipment":"SMH",   # semi-cap equipment is SMH's core
    "Packaged Software":              "IGV",   # iShares Expanded Tech-Software
    "Internet Software/Services":     "FDN",   # First Trust Dow Jones Internet
    "Internet Retail":                "FDN",   # internet commerce names dominate FDN
    "Biotechnology":                  "XBI",   # SPDR S&P Biotech
    "Pharmaceuticals: Major":         "PPH",   # VanEck Pharmaceutical
    "Pharmaceuticals: Other":         "PJP",   # Invesco Dynamic Pharmaceuticals
    "Medical/Nursing Services":       "IHF",   # iShares U.S. Healthcare Providers
    "Hospital/Nursing Management":    "IHF",
    "Managed Health Care":            "IHF",
    "Medical Specialties":            "IHI",   # iShares U.S. Medical Devices
    "Major Banks":                    "KBE",   # SPDR S&P Bank
    "Regional Banks":                 "KRE",   # SPDR S&P Regional Banking
    "Investment Banks/Brokers":       "IAI",   # iShares U.S. Broker-Dealers
    "Investment Managers":            "IAI",   # asset managers are IAI's core
    "Insurance Brokers/Services":     "KIE",   # SPDR S&P Insurance
    "Property/Casualty Insurance":    "KIE",
    "Life/Health Insurance":          "KIE",
    "Multi-Line Insurance":           "KIE",
    "Aerospace & Defense":            "ITA",   # iShares U.S. Aerospace & Defense
    "Oil & Gas Production":           "XOP",   # SPDR S&P Oil & Gas E&P
    "Oil Refining/Marketing":         "CRAK",  # VanEck Oil Refiners
    "Oilfield Services/Equipment":    "OIH",   # VanEck Oil Services
    "Contract Drilling":              "OIH",   # drillers are a core OIH sleeve
    "Oil & Gas Pipelines":            "AMLP",  # Alerian MLP
    "Gold":                           "GDX",   # VanEck Gold Miners
    "Precious Metals":                "GDX",
    "Silver":                         "SIL",   # Global X Silver Miners
    "Steel":                          "SLX",   # VanEck Steel
    "Other Metals/Minerals":          "XME",   # SPDR S&P Metals & Mining
    "Homebuilding":                   "XHB",   # SPDR S&P Homebuilders
    "Airlines":                       "JETS",  # U.S. Global Jets
    "Marine Shipping":                "SEA",   # Invesco Shipping
    "Specialty Stores":               "XRT",   # SPDR S&P Retail (specialty-retail heavy)
    # Restaurants / Casinos-Gaming formerly used EATZ and BJK; both funds were
    # liquidated/relaunched in April 2026, so those industries now fall back
    # to an equal-weight custom index of their top members.
    "Hotels/Resorts/Cruiselines":     "PEJ",   # Invesco Leisure & Entertainment
    "Hotels/Resorts/Cruise lines":    "PEJ",   # TradingView's exact spelling
    "Movies/Entertainment":           "PEJ",
    "Major Telecommunications":       "IYZ",   # iShares U.S. Telecommunications
    "Wireless Telecommunications":    "IYZ",
    "Specialty Telecommunications":   "IYZ",
    "Real Estate Investment Trusts":  "XLRE",  # REITs are XLRE's universe
    "Forest Products":                "WOOD",  # iShares Global Timber & Forestry
    "Agricultural Commodities/Milling":"MOO",  # VanEck Agribusiness
    "Chemicals: Agricultural":        "MOO",   # fertilizer producers are MOO's core
    "Alternative Power Generation":   "QCLN",  # First Trust Nasdaq Clean Edge
    "Motor Vehicles":                 "CARZ",  # First Trust S-Network Future Vehicles
    "Data Processing Services":       "IPAY",  # payments/processors (V, MA, PYPL)
    "Food: Major Diversified":        "PBJ",   # Invesco Food & Beverage
    "Food: Meat/Fish/Dairy":          "PBJ",
    "Food: Specialty/Candy":          "PBJ",
    "Beverages: Non-Alcoholic":       "PBJ",
    "Beverages: Alcoholic":           "PBJ",
    # --- synthetic demo-mode names (INDUSTRY_POOL) ---
    "Software":                       "IGV",
    "Internet Services":              "FDN",
    "IT Services":                    "IGV",
    "Computer Hardware":              "IGM",
    "Pharmaceuticals":                "PPH",
    "Medical Devices":                "IHI",
    "Hospitals":                      "IHF",
    "Managed Care":                   "IHF",
    "Food Products":                  "PBJ",
    "Beverages":                      "PBJ",
    "Household Products":             "XLP",
    "Banks":                          "KBE",
    "Insurance":                      "KIE",
    "Capital Markets":                "IAI",
    "Oil & Gas":                      "XOP",
    "Metals & Mining":                "XME",
    "Machinery":                      "XLI",
    "Electrical Equipment":           "XLI",
    "Autos":                          "CARZ",
    "Leisure":                        "PEJ",
    "Business Services":              "VIS",
    "Staffing":                       "VIS",
    "Wholesale":                      "AIRR",
    "Specialty Retail":               "XRT",
    "E-Commerce":                     "FDN",
    "Chemicals":                      "XLB",
    "Telecom":                        "IYZ",
    "Media":                          "XLC",
    "Entertainment":                  "PEJ",
}

# Major indices tracked with the CCI(34) oscillator. Each entry is the
# dashboard label plus the yfinance symbol used for daily OHLC history.
INDEX_DEFS = [
    {"ticker": "SPY", "yf_symbol": "SPY"},
    {"ticker": "QQQ", "yf_symbol": "QQQ"},
    {"ticker": "DJI", "yf_symbol": "^DJI"},
    {"ticker": "IWM", "yf_symbol": "IWM"},
]
CCI_LENGTH = 34
CCI_EMA_LENGTH = 13

# Numeric score for each CCI rating; averaged across indices for the
# combined market rating and the 0-100 risk gauge.
CCI_RATING_SCORE = {"Bullish": 1.0, "Bullish (Caution)": 0.5, "Neutral": 0.0, "Bearish": -1.0}


def cci_rating(cci, cci_ema):
    """Classify a CCI(34) (yellow) vs its EMA (blue) pair:
    either line below 0 -> Bearish; both above 100 -> Bullish
    (Bullish (Caution) when the yellow line is above the blue line);
    otherwise Neutral."""
    if cci is None or cci_ema is None:
        return None
    if cci < 0 or cci_ema < 0:
        return "Bearish"
    if cci > 100 and cci_ema > 100:
        return "Bullish (Caution)" if cci > cci_ema else "Bullish"
    if cci > 100:
        return "Bullish (Caution)"
    return "Neutral"

# Synthetic industry names for demo mode (live mode uses TradingView's own
# "industry" classification). Each sector maps to a small pool.
INDUSTRY_POOL = {
    "Technology": ["Semiconductors", "Electronic Components", "Computer Hardware", "Software", "Internet Services", "IT Services"],
    "Defensive":  ["Pharmaceuticals", "Biotechnology", "Medical Devices", "Hospitals", "Managed Care", "Food Products", "Beverages", "Household Products", "Electric Utilities", "Gas Utilities"],
    "Cyclical":   ["Banks", "Insurance", "Capital Markets", "Oil & Gas", "Coal", "Metals & Mining", "Steel", "Machinery", "Aerospace & Defense", "Electrical Equipment", "Engineering & Construction", "Autos", "Homebuilding", "Leisure", "Restaurants", "Business Services", "Staffing", "Wholesale", "Specialty Retail", "E-Commerce", "Chemicals", "Airlines", "Railroads", "Trucking"],
    "Communication": ["Telecom", "Media", "Entertainment"],
}

NAME_POOL = [
    "ALPH", "NOVX", "GENE", "CRSP2", "VERA", "ARKB", "IMUN", "ONCX", "BIOX", "PHRM",
    "SNTL", "DFND", "ZTRO", "NETG", "CYBR", "SECR", "FWLL", "PXDF", "VULN", "IDNT",
    "CHIP", "WAFR", "LITH", "FABX", "GATE", "NODE", "CORE", "SILX", "PWRC", "ASIC",
    "BOTA", "ROBX", "AUTM", "VISN", "SENS", "NRLX", "COGN", "DEEP", "INFR", "MDLW",
    "TCSY", "CLDY", "DATX", "QUBT", "AEVA", "PLTR", "SNOW", "CRWD", "OKTA", "NET"
]


def _mk_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL lets API readers keep running while a sync/backfill writes (default
    # journal mode blocks every read for the whole write transaction, which is
    # what made the app freeze during syncs). synchronous=NORMAL is the safe
    # companion setting for WAL. busy_timeout covers writer-writer overlap.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(force=False):
    if force and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = _mk_conn()
    c = conn.cursor()
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS sector (
            id INTEGER PRIMARY KEY,
            name TEXT, ticker TEXT UNIQUE, sub TEXT, tags TEXT,
            color TEXT, notes TEXT DEFAULT '', conviction INTEGER DEFAULT 3
        );
        CREATE TABLE IF NOT EXISTS etf (
            ticker TEXT PRIMARY KEY, name TEXT, sector_id INTEGER, role TEXT, weighting TEXT
        );
        CREATE TABLE IF NOT EXISTS holding (
            etf_ticker TEXT, stock_ticker TEXT, weight_pct REAL, as_of_date TEXT
        );
        CREATE TABLE IF NOT EXISTS stock (
            ticker TEXT PRIMARY KEY, market_cap_musd REAL, price REAL,
            avg_volume REAL, chg_1d REAL, chg_1w REAL, chg_1m REAL, chg_3m REAL, chg_6m REAL,
            rs_rating REAL, rs_vs_spy_1m REAL, pct_from_52w_high REAL, pct_from_52w_low REAL,
            volume_ratio REAL, above_20d INTEGER, above_50d INTEGER, above_200d INTEGER,
            momentum_20d REAL, days_since_new_high INTEGER, is_new_high_today INTEGER,
            sector_id INTEGER, ema5 REAL, ema10 REAL, ema20 REAL, ema50 REAL, ema200 REAL,
            dist_high_1m REAL, dist_high_3m REAL, ext_ema10 REAL,
            volatility_d REAL, atr REAL, industry TEXT, recommend_all REAL,
            above_100ema INTEGER
        );
        CREATE TABLE IF NOT EXISTS sector_snapshot (
            sector_id INTEGER, dt TEXT, price REAL, chg_1d REAL, chg_1w REAL, chg_1m REAL, chg_3m REAL,
            chg_6m REAL,
            breadth_pct_above_50ma REAL, avg_rs_rating REAL, pct_new_highs REAL,
            concentration_index REAL, avg_volume_ratio REAL, rs_vs_spy_1m REAL,
            score REAL, score_qullamaggie REAL, score_bonde REAL, state TEXT,
            etf_pct_from_52w_high REAL, ema10_above_20 INTEGER, above_50ema INTEGER
        );
        CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT, sector_id INTEGER, ts TEXT, note TEXT
        );
        CREATE TABLE IF NOT EXISTS trade (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, ticker TEXT,
            sector_id INTEGER, risk_pct REAL
        );
        CREATE TABLE IF NOT EXISTS sync_status (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            mode TEXT DEFAULT 'demo',
            last_synced TEXT,
            report_json TEXT
        );
        CREATE TABLE IF NOT EXISTS index_cci (
            ticker TEXT PRIMARY KEY, dt TEXT, price REAL, chg_1d REAL,
            cci34 REAL, cci_ema REAL, rating TEXT,
            chg_1w REAL, chg_1m REAL, chg_3m REAL, chg_ytd REAL, chg_1y REAL
        );
        -- Per-sector CCI: CCI(34) + EMA(13) of each sector's proxy ETF
        -- (SECTOR_ETF_MAP). The strategy engines use THIS as their CCI input.
        CREATE TABLE IF NOT EXISTS sector_etf_cci (
            sector_id INTEGER PRIMARY KEY, etf TEXT, dt TEXT,
            cci34 REAL, cci_ema REAL, rating TEXT
        );
        -- Raw values scraped from TradingView's sector/industry market pages
        -- (the exact numbers shown on the website).
        CREATE TABLE IF NOT EXISTS sector_page (
            dt TEXT, name TEXT, slug TEXT, chg_1d REAL, market_cap_usd REAL,
            div_yield_pct REAL, volume REAL, industries_count INTEGER, stocks_count INTEGER,
            PRIMARY KEY (dt, name)
        );
        -- Watchlist: user-saved tickers tagged 'breakout' or 'ep'.
        CREATE TABLE IF NOT EXISTS watchlist (
            ticker TEXT PRIMARY KEY,
            category TEXT NOT NULL DEFAULT 'breakout'
                CHECK(category IN ('breakout','ep')),
            added_at TEXT
        );
        -- Per-industry CCI: CCI(34) + EMA(13) of each mapped industry's
        -- benchmark ETF (INDUSTRY_ETF_MAP). The industry leadership score
        -- uses THIS as its CCI input for industries with > 25 stocks.
        CREATE TABLE IF NOT EXISTS industry_etf_cci (
            industry TEXT PRIMARY KEY, etf TEXT, dt TEXT,
            cci34 REAL, cci_ema REAL, rating TEXT
        );
        CREATE TABLE IF NOT EXISTS industry_page (
            dt TEXT, sector_id INTEGER, name TEXT, slug TEXT, chg_1d REAL,
            chg_1w REAL, chg_1m REAL, chg_3m REAL, chg_6m REAL,
            market_cap_usd REAL, div_yield_pct REAL, volume REAL, stocks_count INTEGER,
            PRIMARY KEY (dt, sector_id, name)
        );
        -- Per-day per-industry snapshot: breadth (% of stocks above the
        -- 20/50/200-day MAs), performance and the leadership score, written
        -- once per live sync so the frontend can chart breadth over time and
        -- rotation deltas.
        CREATE TABLE IF NOT EXISTS industry_snapshot (
            dt TEXT, industry TEXT, sector_id INTEGER,
            chg_1d REAL, chg_1w REAL, chg_1m REAL, chg_3m REAL, chg_6m REAL,
            breadth_20 REAL, breadth_50 REAL, breadth_200 REAL,
            pct_new_highs REAL, vol_ratio REAL,
            leadership_score REAL, leadership_rank INTEGER,
            stocks_count INTEGER,
            PRIMARY KEY (dt, industry)
        );
        -- MA-pullback green-candle signal per industry benchmark ETF
        -- (detected from daily OHLC at sync time; synthesized in demo mode).
        CREATE TABLE IF NOT EXISTS industry_ma_signal (
            dt TEXT, industry TEXT, etf TEXT, detected INTEGER,
            body_ratio REAL, close_pos REAL, vol_ratio REAL, bonus REAL,
            PRIMARY KEY (dt, industry)
        );
        """
    )
    # Idempotent migrations for existing databases
    for stmt in (
        "ALTER TABLE stock ADD COLUMN chg_6m REAL",
        "ALTER TABLE stock ADD COLUMN ema10 REAL",
        "ALTER TABLE stock ADD COLUMN ema5 REAL",
        "ALTER TABLE stock ADD COLUMN ema200 REAL",        "ALTER TABLE stock ADD COLUMN ema20 REAL",
        "ALTER TABLE stock ADD COLUMN ema50 REAL",
        "ALTER TABLE sector_snapshot ADD COLUMN chg_6m REAL",
        "ALTER TABLE sector_snapshot ADD COLUMN score_qullamaggie REAL",
        "ALTER TABLE sector_snapshot ADD COLUMN score_bonde REAL",
        "ALTER TABLE sector_snapshot ADD COLUMN etf_pct_from_52w_high REAL",
        "ALTER TABLE sector_snapshot ADD COLUMN ema10_above_20 INTEGER",
        "ALTER TABLE sector_snapshot ADD COLUMN above_50ema INTEGER",
        "ALTER TABLE stock ADD COLUMN dist_high_1m REAL",
        "ALTER TABLE stock ADD COLUMN dist_high_3m REAL",
        "ALTER TABLE stock ADD COLUMN ext_ema10 REAL",
        "ALTER TABLE stock ADD COLUMN volatility_d REAL",
        "ALTER TABLE stock ADD COLUMN atr REAL",
        "ALTER TABLE stock ADD COLUMN industry TEXT",
        "ALTER TABLE stock ADD COLUMN recommend_all REAL",
        "ALTER TABLE stock ADD COLUMN chg_ytd REAL",
        "ALTER TABLE stock ADD COLUMN chg_1y REAL",
        "ALTER TABLE stock ADD COLUMN recommend_ma REAL",
        "ALTER TABLE stock ADD COLUMN recommend_other REAL",
        "ALTER TABLE stock ADD COLUMN recommend_all_1w REAL",
        "ALTER TABLE stock ADD COLUMN recommend_ma_1w REAL",
        "ALTER TABLE stock ADD COLUMN recommend_other_1w REAL",
        "ALTER TABLE stock ADD COLUMN adr_pct REAL",
        "ALTER TABLE index_cci ADD COLUMN chg_1w REAL",
        "ALTER TABLE index_cci ADD COLUMN chg_1m REAL",
        "ALTER TABLE index_cci ADD COLUMN chg_3m REAL",
        "ALTER TABLE index_cci ADD COLUMN chg_ytd REAL",
        "ALTER TABLE index_cci ADD COLUMN chg_1y REAL",
        "ALTER TABLE industry_page ADD COLUMN chg_1w REAL",
        "ALTER TABLE industry_page ADD COLUMN chg_1m REAL",
        "ALTER TABLE industry_page ADD COLUMN chg_3m REAL",
        "ALTER TABLE industry_page ADD COLUMN chg_6m REAL",
        "ALTER TABLE stock ADD COLUMN volatility_w REAL",
        "ALTER TABLE stock ADD COLUMN volatility_m REAL",
        "ALTER TABLE stock ADD COLUMN open_price REAL",
        "ALTER TABLE stock ADD COLUMN day_high REAL",
        "ALTER TABLE stock ADD COLUMN day_low REAL",
        "ALTER TABLE stock ADD COLUMN chg_from_open REAL",
        "ALTER TABLE stock ADD COLUMN gap_pct REAL",
        "ALTER TABLE stock ADD COLUMN pm_chg REAL",
        "ALTER TABLE stock ADD COLUMN pm_vol REAL",
        "ALTER TABLE stock ADD COLUMN volume_today REAL",
        "ALTER TABLE stock ADD COLUMN above_100ema INTEGER",
    ):
        try:
            c.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists
    c.execute("INSERT OR IGNORE INTO sync_status (id, mode) VALUES (1, 'demo')")
    # Idempotently refresh sector colors from the current palette so existing
    # (e.g. live-mode) databases adopt palette updates without a resync.
    for s_idx in range(1, len(SECTOR_DEFS) + 1):
        c.execute(
            "UPDATE sector SET color=? WHERE id=?",
            (SECTOR_COLORS[(s_idx - 1) % len(SECTOR_COLORS)], s_idx),
        )
    conn.commit()
    conn.close()


def _rand_stock_metrics():
    price = round(random.choice([
        random.uniform(0.5, 2.9),      # some penny names -> filtered out
        random.uniform(3, 15),
        random.uniform(15, 80),
        random.uniform(80, 400),
    ]), 2)
    mcap = round(random.choice([
        random.uniform(50, 950),        # sub-$500M -> filtered out
        random.uniform(1000, 8000),
        random.uniform(8000, 60000),
        random.uniform(60000, 400000),
    ]), 1)
    avg_vol = round(random.choice([
        random.uniform(0.1, 0.9) * 1_000_000,
        random.uniform(1.0, 8.0) * 1_000_000,
        random.uniform(8.0, 30.0) * 1_000_000,
    ]), 0)
    rs = round(random.uniform(1, 99), 1)
    m = {
        "market_cap_musd": mcap,
        "price": price,
        "avg_volume": avg_vol,
        "chg_1d": round(random.uniform(-6, 6), 2),
        "chg_1w": round(random.uniform(-14, 16), 2),
        "chg_1m": round(random.uniform(-30, 40), 2),
        "chg_3m": round(random.uniform(-45, 55), 2),
        "chg_6m": round(random.uniform(-55, 70), 2),
        "rs_rating": rs,
        "rs_vs_spy_1m": round(random.uniform(-25, 30), 2),
        "pct_from_52w_high": round(-random.uniform(0, 55), 1),
        "pct_from_52w_low": round(random.uniform(5, 140), 1),
        "volume_ratio": round(random.uniform(0.4, 4.5), 2),
        "above_20d": random.random() > 0.4,
        "above_50d": random.random() > 0.45,
        "above_200d": random.random() > 0.5,
        "above_100ema": random.random() > 0.45,
        "momentum_20d": round(random.uniform(-25, 35), 2),
        "days_since_new_high": random.randint(0, 90),
        "is_new_high_today": random.random() > 0.88,
        # TradingView analyst rating (0 = strong sell .. 1 = strong buy)
        "recommend_all": round(random.uniform(0.1, 0.9), 3),
    }
    # Plausible EMAs correlated with momentum: positive momentum -> ema10 > ema20 > ema50 and price > ema50
    mom = (m["chg_1w"] + m["chg_1m"]) / 2  # recent momentum in %
    base_gap = mom * 0.004                 # fraction gap between price and ema50
    m["ema50"] = round(price * (1 - base_gap) * (1 + random.uniform(-0.01, 0.01)), 2)
    m["ema20"] = round(price * (1 - base_gap * 0.66) * (1 + random.uniform(-0.005, 0.005)), 2)
    m["ema10"] = round(price * (1 - base_gap * 0.33) * (1 + random.uniform(-0.003, 0.003)), 2)
    m["ema5"] = round(price * (1 - base_gap * 0.16) * (1 + random.uniform(-0.002, 0.002)), 2)
    m["ema200"] = round(price * (1 - base_gap * 2.2) * (1 + random.uniform(-0.03, 0.03)), 2)
    # EP extras: intraday range / gap / pre-market, kept consistent with chg_1d
    prev_close = price / (1 + m["chg_1d"] / 100.0) if (1 + m["chg_1d"] / 100.0) else price
    gap = round(random.uniform(-3, 4), 2)
    open_price = round(prev_close * (1 + gap / 100.0), 2)
    m["gap_pct"] = round((open_price / prev_close - 1) * 100, 2) if prev_close else 0.0
    m["open_price"] = open_price
    m["chg_from_open"] = round((price / open_price - 1) * 100, 2) if open_price else 0.0
    hi = max(price, open_price)
    lo = min(price, open_price)
    m["day_high"] = round(hi * (1 + random.uniform(0, 0.02)), 2)
    m["day_low"] = round(lo * (1 - random.uniform(0, 0.02)), 2)
    m["volume_today"] = round(avg_vol * m["volume_ratio"], 0)
    m["pm_chg"] = round(m["gap_pct"] + random.uniform(-1.5, 1.5), 2)
    m["pm_vol"] = round(m["volume_today"] * random.uniform(0.05, 0.3), 0)
    return m


def generate_universe():
    """Populate sectors, ETFs, holdings, and stocks with synthetic demo data."""
    conn = _mk_conn()
    c = conn.cursor()
    today = date.today().isoformat()

    for s_idx, sdef in enumerate(SECTOR_DEFS, start=1):
        color = SECTOR_COLORS[(s_idx - 1) % len(SECTOR_COLORS)]
        c.execute(
            """INSERT OR IGNORE INTO sector (id, name, ticker, sub, tags, color, conviction)
               VALUES (?,?,?,?,?,?,?)""",
            (s_idx, sdef["name"], sdef["ticker"], sdef["sub"], sdef["tags"], color, random.randint(2, 5)),
        )
        # Keep stored color in sync with the current palette (INSERT OR IGNORE
        # leaves stale colors in existing databases).
        c.execute("UPDATE sector SET color=? WHERE id=?", (color, s_idx))
        etf_name = sdef["ticker"] + " ETF"
        c.execute(
            "INSERT OR REPLACE INTO etf (ticker, name, sector_id, role, weighting) VALUES (?,?,?,?,?)",
            (sdef["ticker"], etf_name, s_idx, "primary", "cap"),
        )
        n_holdings = random.randint(18, 30)
        pool = random.sample(NAME_POOL, min(n_holdings, len(NAME_POOL)))
        raw_weights = [random.uniform(1, 12) ** 1.8 for _ in pool]
        total = sum(raw_weights)
        for stock_ticker, w in zip(pool, raw_weights):
            weight_pct = round(w / total * 100, 2)
            c.execute(
                "INSERT INTO holding (etf_ticker, stock_ticker, weight_pct, as_of_date) VALUES (?,?,?,?)",
                (sdef["ticker"], stock_ticker, weight_pct, today),
            )
            if not c.execute("SELECT 1 FROM stock WHERE ticker=?", (stock_ticker,)).fetchone():
                m = _rand_stock_metrics()
                industry = random.choice(INDUSTRY_POOL.get(sdef["sub"], ["Diversified"]))
                c.execute(
                    """INSERT INTO stock (ticker, market_cap_musd, price, avg_volume, chg_1d, chg_1w, chg_1m, chg_3m, chg_6m,
                       rs_rating, rs_vs_spy_1m, pct_from_52w_high, pct_from_52w_low, volume_ratio,
                       above_20d, above_50d, above_200d, momentum_20d, days_since_new_high, is_new_high_today, sector_id,
                       ema10, ema20, ema50, ema5, ema200, volatility_d, industry, recommend_all, volatility_w, volatility_m,
                       open_price, day_high, day_low, chg_from_open, gap_pct, pm_chg, pm_vol, volume_today, above_100ema)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        stock_ticker, m["market_cap_musd"], m["price"], m["avg_volume"],
                        m["chg_1d"], m["chg_1w"], m["chg_1m"], m["chg_3m"], m["chg_6m"],
                        m["rs_rating"], m["rs_vs_spy_1m"], m["pct_from_52w_high"], m["pct_from_52w_low"],
                        m["volume_ratio"], int(m["above_20d"]), int(m["above_50d"]), int(m["above_200d"]),
                        m["momentum_20d"], m["days_since_new_high"], int(m["is_new_high_today"]), s_idx,
                        m["ema10"], m["ema20"], m["ema50"], m["ema5"], m["ema200"],
                        round(random.uniform(1.5, 9.0), 2), industry, m["recommend_all"],
                        round(random.uniform(1.0, 8.0), 2), round(random.uniform(1.5, 12.0), 2),
                        m["open_price"], m["day_high"], m["day_low"], m["chg_from_open"],
                        m["gap_pct"], m["pm_chg"], m["pm_vol"], m["volume_today"],
                        int(m["above_100ema"])
                    ),
                )
    # A handful of synthetic EP-style movers so the EP section has demo content
    # (ordinary random stocks rarely pass the hard EP filters).
    for i in range(8):
        ep_ticker = "EPD%d" % (i + 1)
        if c.execute("SELECT 1 FROM stock WHERE ticker=?", (ep_ticker,)).fetchone():
            continue
        m = _rand_stock_metrics()
        m["chg_1d"] = round(random.uniform(13, 45), 2)
        m["volume_ratio"] = round(random.uniform(3, 15), 2)
        m["avg_volume"] = round(random.uniform(1.2, 20) * 1_000_000, 0)
        m["market_cap_musd"] = round(random.uniform(350, 9000), 1)
        m["price"] = round(random.uniform(4, 250), 2)
        prev_close = m["price"] / (1 + m["chg_1d"] / 100.0)
        m["gap_pct"] = round(random.uniform(3, 25), 2)
        m["open_price"] = round(prev_close * (1 + m["gap_pct"] / 100.0), 2)
        m["chg_from_open"] = round((m["price"] / m["open_price"] - 1) * 100, 2)
        m["day_high"] = round(max(m["price"], m["open_price"]) * 1.01, 2)
        m["day_low"] = round(min(m["open_price"], prev_close) * 0.99, 2)
        m["volume_today"] = round(m["avg_volume"] * m["volume_ratio"], 0)
        m["pm_chg"] = round(m["gap_pct"] + random.uniform(-2, 3), 2)
        m["pm_vol"] = round(m["volume_today"] * random.uniform(0.1, 0.35), 0)
        s_idx = random.randint(1, len(SECTOR_DEFS))
        sdef = SECTOR_DEFS[s_idx - 1]
        industry = random.choice(INDUSTRY_POOL.get(sdef["sub"], ["Diversified"]))
        vol_m = round(random.uniform(1.5, 4.5), 2) if i % 2 == 0 else round(random.uniform(6, 14), 2)
        c.execute(
            """INSERT INTO stock (ticker, market_cap_musd, price, avg_volume, chg_1d, chg_1w, chg_1m, chg_3m, chg_6m,
               rs_rating, rs_vs_spy_1m, pct_from_52w_high, pct_from_52w_low, volume_ratio,
               above_20d, above_50d, above_200d, momentum_20d, days_since_new_high, is_new_high_today, sector_id,
               ema10, ema20, ema50, ema5, ema200, volatility_d, industry, recommend_all, volatility_w, volatility_m,
               open_price, day_high, day_low, chg_from_open, gap_pct, pm_chg, pm_vol, volume_today, adr_pct, above_100ema)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ep_ticker, m["market_cap_musd"], m["price"], m["avg_volume"],
                m["chg_1d"], m["chg_1w"], m["chg_1m"], m["chg_3m"], m["chg_6m"],
                m["rs_rating"], m["rs_vs_spy_1m"], m["pct_from_52w_high"], m["pct_from_52w_low"],
                m["volume_ratio"], int(m["above_20d"]), int(m["above_50d"]), int(m["above_200d"]),
                m["momentum_20d"], m["days_since_new_high"], int(m["is_new_high_today"]), s_idx,
                m["ema10"], m["ema20"], m["ema50"], m["ema5"], m["ema200"],
                round(random.uniform(1.5, 9.0), 2), industry, m["recommend_all"],
                round(random.uniform(1.0, 8.0), 2), vol_m,
                m["open_price"], m["day_high"], m["day_low"], m["chg_from_open"],
                m["gap_pct"], m["pm_chg"], m["pm_vol"], m["volume_today"],
                round(random.uniform(3.0, 6.0), 2), int(m["above_100ema"])
            ),
        )
    # Insert benchmark ticker
    if not c.execute("SELECT 1 FROM stock WHERE ticker=?", (BENCHMARK_TICKER,)).fetchone():
        m = _rand_stock_metrics()
        # Realistic SPY quote (~740) so demo mode doesn't show absurd prices.
        m["price"] = round(740 * random.uniform(0.97, 1.03), 2)
        mom = (m["chg_1w"] + m["chg_1m"]) / 2
        base_gap = mom * 0.004
        m["ema50"] = round(m["price"] * (1 - base_gap), 2)
        m["ema20"] = round(m["price"] * (1 - base_gap * 0.66), 2)
        m["ema10"] = round(m["price"] * (1 - base_gap * 0.33), 2)
        m["ema5"] = round(m["price"] * (1 - base_gap * 0.16), 2)
        m["ema200"] = round(m["price"] * (1 - base_gap * 2.2), 2)
        m["market_cap_musd"] = 4000000
        m["avg_volume"] = 80000000
        c.execute(
            """INSERT INTO stock (ticker, market_cap_musd, price, avg_volume, chg_1d, chg_1w, chg_1m, chg_3m, chg_6m,
               rs_rating, rs_vs_spy_1m, pct_from_52w_high, pct_from_52w_low, volume_ratio,
               above_20d, above_50d, above_200d, momentum_20d, days_since_new_high, is_new_high_today, sector_id,
               ema10, ema20, ema50, ema5, ema200, above_100ema)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                BENCHMARK_TICKER, m["market_cap_musd"], m["price"], m["avg_volume"],
                m["chg_1d"], m["chg_1w"], m["chg_1m"], m["chg_3m"], m["chg_6m"],
                50, 0, m["pct_from_52w_high"], m["pct_from_52w_low"],
                m["volume_ratio"], int(m["above_20d"]), int(m["above_50d"]), int(m["above_200d"]),
                m["momentum_20d"], m["days_since_new_high"], int(m["is_new_high_today"]), None,
                m["ema10"], m["ema20"], m["ema50"], m["ema5"], m["ema200"], int(m["above_100ema"])
            ),
        )

    # Demo CCI oscillator ratings for the major indices
    for idef in INDEX_DEFS:
        cci = round(random.uniform(-180, 220), 1)
        ema = round(cci - random.uniform(-60, 60), 1)
        c.execute(
            "INSERT OR REPLACE INTO index_cci (ticker, dt, price, chg_1d, cci34, cci_ema, rating,"
            " chg_1w, chg_1m, chg_3m, chg_ytd, chg_1y) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (idef["ticker"], today, round(random.uniform(100, 700), 2),
             round(random.uniform(-1.5, 1.5), 2), cci, ema, cci_rating(cci, ema),
             round(random.uniform(-3, 3), 2), round(random.uniform(-5, 5), 2),
             round(random.uniform(-10, 12), 2), round(random.uniform(-8, 20), 2),
             round(random.uniform(-15, 30), 2)),
        )

    # Demo sector CCI: synthetic CCI(34)/EMA(13) for each sector's proxy ETF
    for s_idx, sdef in enumerate(SECTOR_DEFS, start=1):
        etf = SECTOR_ETF_MAP.get(sdef["name"])
        if not etf:
            continue
        cci = round(random.uniform(-180, 220), 1)
        ema = round(cci - random.uniform(-60, 60), 1)
        c.execute(
            "INSERT OR REPLACE INTO sector_etf_cci (sector_id, etf, dt, cci34, cci_ema, rating)"
            " VALUES (?,?,?,?,?,?)",
            (s_idx, etf, today, cci, ema, cci_rating(cci, ema)),
        )

    conn.commit()

    # Build 60 days of sector_snapshot history (synthetic random walk with diverse states)
    c.execute("DELETE FROM sector_snapshot")
    # Starting regimes: strong, weak, and middle so demo shows all four rotation states
    starts = [
        {"score": 70, "breadth": 75, "rs": 70, "drift": 0.35},   # leader
        {"score": 30, "breadth": 30, "rs": 35, "drift": -0.35},  # lagging
        {"score": 55, "breadth": 55, "rs": 55, "drift": 0.25},   # emerging
        {"score": 50, "breadth": 50, "rs": 50, "drift": -0.25},  # fading
        {"score": 60, "breadth": 60, "rs": 60, "drift": 0.15},   # leader-ish
        {"score": 40, "breadth": 40, "rs": 40, "drift": -0.15}, # lagging-ish
        {"score": 58, "breadth": 58, "rs": 58, "drift": 0.30},   # emerging
        {"score": 48, "breadth": 48, "rs": 48, "drift": -0.30},  # fading
        {"score": 72, "breadth": 72, "rs": 72, "drift": 0.10},   # leader
        {"score": 28, "breadth": 28, "rs": 28, "drift": -0.10},  # lagging
        {"score": 62, "breadth": 62, "rs": 62, "drift": 0.20},   # emerging
        {"score": 38, "breadth": 38, "rs": 38, "drift": -0.20},  # lagging
        {"score": 68, "breadth": 68, "rs": 68, "drift": 0.05},   # leader
        {"score": 32, "breadth": 32, "rs": 32, "drift": -0.05},  # lagging
        {"score": 52, "breadth": 52, "rs": 52, "drift": 0.40},   # emerging
    ]
    for s_idx, sdef in enumerate(SECTOR_DEFS, start=1):
        cfg = random.choice(starts)  # unbiased: no predetermined leader
        drift = cfg["drift"]
        breadth = cfg["breadth"]
        rs = cfg["rs"]
        score = cfg["score"]
        conc = random.uniform(8, 16)
        price = random.uniform(40, 200)
        scores = []
        for i in range(60, 0, -1):
            d = (date.today() - timedelta(days=i)).isoformat()
            # mild mean reversion + noise + drift; drift amplified near the end
            effective_drift = drift * (1.6 if i <= 7 else 1.0)
            mean_revert = (50 - score) * 0.05
            breadth = min(95, max(5, breadth + random.uniform(-4, 4) + effective_drift))
            rs = min(99, max(1, rs + random.uniform(-2.5, 2.5) + effective_drift * 0.5))
            conc = min(45, max(5, conc + random.uniform(-1.2, 1.2)))
            pct_new_highs = max(0, min(100, breadth * 0.6 + random.uniform(-8, 8)))
            score = min(100, max(0, score + random.uniform(-3, 3) + effective_drift + mean_revert))
            scores.append((d, score, breadth, rs))
            price = price * (1 + random.uniform(-0.01, 0.01) + effective_drift * 0.001)
            # New snapshot columns correlated with score: high-score sectors sit near
            # their 52w high with EMAs aligned; low-score sectors are beaten down.
            etf_pct_from_high = round(-(25 - 0.24 * score) + random.uniform(-2, 2), 1)
            ema10_above_20 = int(random.random() < max(0.05, min(0.95, score / 100)))
            above_50ema = int(random.random() < max(0.05, min(0.95, score / 100)))
            c.execute(
                """INSERT INTO sector_snapshot (sector_id, dt, price, chg_1d, chg_1w, chg_1m, chg_3m,
                   chg_6m, breadth_pct_above_50ma, avg_rs_rating, pct_new_highs, concentration_index,
                   avg_volume_ratio, rs_vs_spy_1m, score, state,
                   etf_pct_from_52w_high, ema10_above_20, above_50ema)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (s_idx, d, round(price, 2), round(random.uniform(-2, 2), 2), round(random.uniform(-4, 5), 2),
                 round(random.uniform(-8, 10), 2), round(random.uniform(-12, 15), 2),
                 round(random.uniform(-18, 22), 2),
                 round(breadth, 1), round(rs, 1), round(pct_new_highs, 1), round(conc, 2),
                 round(random.uniform(0.8, 1.8), 2), round(random.uniform(-5, 8), 2), round(score, 1), "neutral",
                 etf_pct_from_high, ema10_above_20, above_50ema),
            )
    # Canonical sector score: CCI-based (50% performance + 50% CCI). The
    # performance component (15% 1W / 50% 1M / 35% 3M) is min-max normalized
    # across sectors per snapshot date; the CCI component is each sector's
    # proxy-ETF CCI rating factor. score_qullamaggie keeps the Qullamaggie
    # weekly-scan score on the latest snapshot; the legacy score_bonde column
    # is repurposed to store the normalized performance component.
    cci_by_sector = {
        r["sector_id"]: f for r in c.execute("SELECT sector_id, rating FROM sector_etf_cci").fetchall()
        for f in [cci_rating_factor(r["rating"])] if f is not None
    }
    dts = [r[0] for r in c.execute("SELECT DISTINCT dt FROM sector_snapshot").fetchall()]
    for d in dts:
        rows = c.execute(
            "SELECT sector_id, chg_1w, chg_1m, chg_3m FROM sector_snapshot WHERE dt=?", (d,)
        ).fetchall()
        stats = [{"sector_id": r["sector_id"], "perf_1w": r["chg_1w"],
                  "perf_1m": r["chg_1m"], "perf_3m": r["chg_3m"]} for r in rows]
        perf_scores = sector_performance_scores(stats)
        final = cci_sector_scores(stats, 50.0, cci_by_sector)
        for sid, sc in final.items():
            c.execute(
                "UPDATE sector_snapshot SET score=?, score_bonde=? WHERE sector_id=? AND dt=?",
                (sc, perf_scores.get(sid), sid, d),
            )
    latest_stats = []
    for s_idx in range(1, len(SECTOR_DEFS) + 1):
        row = c.execute(
            "SELECT * FROM sector_snapshot WHERE sector_id=? ORDER BY dt DESC LIMIT 1", (s_idx,)
        ).fetchone()
        if row:
            latest_stats.append({
                "sector_id": s_idx, "perf_1w": row["chg_1w"], "perf_1m": row["chg_1m"],
                "perf_3m": row["chg_3m"], "perf_6m": row["chg_6m"],
                "breadth": row["breadth_pct_above_50ma"], "rs_vs_spy": row["rs_vs_spy_1m"],
            })
    q_scores = qullamaggie_scan_scores(latest_stats)
    for st in latest_stats:
        sid = st["sector_id"]
        c.execute(
            """UPDATE sector_snapshot
               SET score_qullamaggie=?
               WHERE sector_id=? AND dt=(SELECT MAX(dt) FROM sector_snapshot WHERE sector_id=?)""",
            (q_scores[sid], sid, sid),
        )
    # Reclassify the last snapshot (now the combined score) using 5-day velocity
    # to produce emerging/fading states
    for s_idx in range(1, len(SECTOR_DEFS) + 1):
        rows = c.execute("SELECT * FROM sector_snapshot WHERE sector_id=? ORDER BY dt ASC", (s_idx,)).fetchall()
        if len(rows) >= 6:
            last = dict(rows[-1])
            prev = dict(rows[-6])
            velocity = last["score"] - prev["score"]
            state = classify_sector_state(last["score"], last["breadth_pct_above_50ma"], last["avg_rs_rating"], last["score"] - velocity)
            c.execute("UPDATE sector_snapshot SET state=? WHERE sector_id=? AND dt=?", (state, s_idx, last["dt"]))
    conn.commit()

    # Demo industry_snapshot history + MA-pullback signal rows so the
    # Scores leaderboards work fully offline.
    _generate_demo_industry_extras(conn)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

def apply_filters(rows):
    """Universal filter: market cap >= $500M, avg 30d volume >= 1M,
    ADR >= 2%, price >= $3 (rows that predate a column pass through so demo
    data stays usable)."""
    return [
        r for r in rows
        if r["market_cap_musd"] >= MIN_MARKET_CAP_MUSD
        and r["avg_volume"] >= MIN_AVG_VOLUME
        and (r.get("adr_pct") is None or r["adr_pct"] >= MIN_ADR_PCT)
        and (r.get("price") is None or r["price"] >= MIN_PRICE)
    ]


def _percentile_rank(values, v):
    if not values:
        return 50.0
    below = sum(1 for x in values if x <= v)
    return round(below / len(values) * 100, 1)


# ---------------------------------------------------------------------------
# Strategy framework
#
# One scanner shell, one strategy engine: Qullamaggie. CCI is a COMPULSORY
# input in the stock composite. Sector ranking is fully CCI-based (see
# strategy_sector_scores): 50% performance + 50% CCI.
# ---------------------------------------------------------------------------
STRATEGY_DEFS = {
    "qullamaggie": {
        "label": "Qullamaggie",
        "w": {"rs": 0.26, "mom1m": 0.16, "high": 0.16, "vol": 0.12,
              "above20": 0.08, "above50": 0.04, "above200": 0.00,
              "breakout": 0.08, "cci": 0.10},
        "ext_cap": 14.0, "ext_knee": 18.0, "ext_slope": 1.5,
        "vol_cap": 10.0, "vol_knee": 7.0, "vol_slope": 1.0,
    },
}
STRATEGY_DEFAULT = "qullamaggie"


def cci_rating_factor(rating):
    """Map one CCI rating to a 0-100 factor: Bearish -> 0, Neutral -> 50,
    Bullish (Caution) -> 75, Bullish -> 100."""
    score = CCI_RATING_SCORE.get(rating)
    return round(50 + 50 * score, 1) if score is not None else None


def sector_cci_factors(conn):
    """Per-sector CCI factor (0-100) from each sector's proxy ETF CCI(34)
    rating (sector_etf_cci table). Sectors without an ETF CCI row simply
    have no entry — callers fall back to the market-wide CCI factor."""
    try:
        rows = conn.execute("SELECT sector_id, rating FROM sector_etf_cci").fetchall()
    except Exception:
        return {}
    out = {}
    for r in rows:
        f = cci_rating_factor(r["rating"])
        if f is not None:
            out[r["sector_id"]] = f
    return out


def industry_cci_factors(conn):
    """Per-industry CCI factor (0-100) from each industry's benchmark ETF
    CCI(34) rating (industry_etf_cci table). Industries without an ETF CCI
    row simply have no entry — callers fall back to the parent sector's CCI,
    then to the market-wide CCI factor."""
    try:
        rows = conn.execute(
            "SELECT industry, etf, rating, cci34, cci_ema FROM industry_etf_cci"
        ).fetchall()
    except Exception:
        return {}
    out = {}
    for r in rows:
        f = cci_rating_factor(r["rating"])
        if f is not None:
            out[r["industry"]] = {
                "factor": f, "rating": r["rating"], "etf": r["etf"],
                "cci34": r["cci34"], "cci_ema": r["cci_ema"],
            }
    return out


# ---------------------------------------------------------------------------
# Industry leadership ranking
#
# Every industry with at least 3 stocks is included. Two ranking methods:
#   - Industries with MORE than 25 stocks (they have a benchmark ETF /
#     industry-level CCI): score = 65% performance + 35% CCI.
#   - Industries with 25 stocks or fewer (no industry benchmark): score =
#     performance only, weighted 1M > 3M > 1W.
# The performance component is 50% 1M + 35% 3M + 15% 1W (1M highest
# priority, 3M slightly less, 1W lowest), min-max normalized across all
# eligible industries to 0-100 before combining.
# ---------------------------------------------------------------------------
IND_MIN_STOCKS = 3
IND_BENCH_MIN_STOCKS = 25
IND_W_PERF = 0.65
IND_W_CCI = 0.35


def industry_leadership_scores(rows, industry_cci=None, sector_cci=None,
                               market_cci=50.0):
    """Compute the industry leadership score for a set of industry rows.

    rows: [{"industry", "stock_count", "chg_1w", "chg_1m", "chg_3m",
            "sector_id", ...}, ...] (as produced by _industry_rows).
    industry_cci: {industry_name: {"factor": 0-100, ...}} from
        industry_cci_factors(conn).
    sector_cci: {sector_id: 0-100} from sector_cci_factors(conn).
    Returns {industry_name: {"leadership_score", "perf_component",
    "cci_factor", "benchmark_etf", "has_benchmark"}} — only industries with
    >= IND_MIN_STOCKS stocks get an entry.
    """
    industry_cci = industry_cci or {}
    sector_cci = sector_cci or {}
    market = market_cci if market_cci is not None else 50.0
    eligible = [r for r in rows if (r.get("stock_count") or 0) >= IND_MIN_STOCKS]
    raws = {}
    for r in eligible:
        raws[r["industry"]] = (
            PERF_W_1W * (r.get("chg_1w") or 0)
            + PERF_W_1M * (r.get("chg_1m") or 0)
            + PERF_W_3M * (r.get("chg_3m") or 0)
        )
    if not raws:
        return {}
    mn, mx = min(raws.values()), max(raws.values())
    span = (mx - mn) or 1.0
    out = {}
    for r in eligible:
        name = r["industry"]
        perf = round((raws[name] - mn) / span * 100, 1)
        big = (r.get("stock_count") or 0) > IND_BENCH_MIN_STOCKS
        # benchmark_etf identifies the chart benchmark for EVERY industry
        # (has_benchmark separately controls whether CCI enters the score).
        etf = INDUSTRY_ETF_MAP.get(name)
        if big:
            ic = industry_cci.get(name)
            cci = (ic["factor"] if ic else
                   sector_cci.get(r.get("sector_id"), market))
            score = round(IND_W_PERF * perf + IND_W_CCI * cci, 1)
        else:
            cci = None
            score = perf  # performance only
        out[name] = {
            "leadership_score": score,
            "perf_component": perf,
            "cci_factor": cci,
            "benchmark_etf": etf,
            "has_benchmark": big,
        }
    return out


# ---------------------------------------------------------------------------
# Industry leaderboard scoring ("Scores" page) — two-stage 100-point system
#
# Stage 1: an eligibility STATUS gate per industry (actionable / emerging /
#   extended / watchlist / avoid). Stage 2: a 0-100 Leadership Score built
#   from percentile-ranked components across the industry universe
#   (industries with >= IND_MIN_STOCKS filtered stocks):
#     sustained_rs  : 0.60*RS(3M) pct + 0.40*RS(6M) pct   (RS = ret - SPY ret)
#     recent_mom    : 0.35*RS(1W) pct + 0.65*RS(1M) pct, plus up to +5 bonus
#                     points when 1W and 1M RS are both positive and improving
#                     vs the prior industry_snapshot
#     breadth       : 0.20*(%>20MA) + 0.60*(%>100EMA) + 0.20*(%new highs) —
#                     dominated by % of stocks above the 100 EMA,
#                     confidence-adjusted by min(1, N/10) for small industries
#     trend_quality : 100/75/50/25/0 rubric from member EMA alignment
#                     (ext_ema20/ext_ema50), breadth_200 and the snapshot
#                     chg_1m trend — no hard caps
#     rotation      : 0.60*(score-change pct) + 0.40*(rank-improvement pct)
#                     from industry_snapshot history; acceleration bonus only
#                     when recent momentum is positive
#     volume        : 100/70/40/0-25 rubric from vol_ratio vs price direction
#     opportunity   : 100/70/40/0 extension rubric evolved from the old
#                     extension penalty (ext_ema20/ext_ema50)
# The default weight profile is "Swing Trading"; "Position Trading" shifts
# weight to sustained RS / trend, "Early Rotation" to recent momentum /
# rotation. Statuses: avoid is capped at 39; extended keeps its score but is
# excluded from the Actionable Now list (0.65*Leadership + 0.35*Opportunity).
# ---------------------------------------------------------------------------
LEAD_PROFILES = {
    "swing": {"label": "Swing Trading",
              "w": {"sustained_rs": 25, "recent_mom": 15, "breadth": 40,
                    "trend": 8, "rotation": 4, "volume": 3,
                    "opportunity": 5}},
    "position": {"label": "Position Trading",
                 "w": {"sustained_rs": 30, "recent_mom": 10, "breadth": 40,
                       "trend": 10, "rotation": 2, "volume": 3,
                       "opportunity": 5}},
    "early_rotation": {"label": "Early Rotation",
                       "w": {"sustained_rs": 15, "recent_mom": 25,
                             "breadth": 40, "trend": 5, "rotation": 10,
                             "volume": 2, "opportunity": 3}},
}
LEAD_PROFILE_DEFAULT = "swing"
LEAD_EXT_EMA20_KNEE = 9.0    # % above EMA20 -> "extended leader" territory
LEAD_EXT_EMA20_CLIMAX = 15.0 # % above EMA20 -> climactic
EXT_EMA50_HARD = 18.0        # % above EMA50 -> excessively extended
PATTERN_BONUS = 12.0         # legacy demo bonus kept on industry_ma_signal rows
LEAD_LIST_LIMIT = 15


def detect_ma_pullback_signal(bars):
    """Detect an MA-pullback strong-green-candle signal in daily OHLC bars.

    bars: list of {"dt", "open", "high", "low", "close", "volume"} sorted
    ascending by date (volume may be None/0). Looks at the LAST bar only:
    during an uptrend (EMA10 > EMA20, price above EMA20 a week back) the
    price pulled back into the EMA10–EMA20 zone from above within the last
    5 sessions, and the last bar is a strong green candle: body > 1.6x the
    20-day average body, close in the top 25% of the candle range, volume
    > 1.2x the 20-day average (volume check skipped when volume missing).

    Returns {"detected", "dt", "body_ratio", "close_pos", "vol_ratio"} or
    None when there is not enough history (< 40 bars).
    """
    if not bars or len(bars) < 40:
        return None
    closes = [b["close"] for b in bars]

    def ema(vals, span):
        k = 2.0 / (span + 1)
        out = [vals[0]]
        for v in vals[1:]:
            out.append(out[-1] + k * (v - out[-1]))
        return out

    ema10 = ema(closes, 10)
    ema20 = ema(closes, 20)
    j = len(bars) - 1
    last = bars[j]

    # Prior uptrend: EMA10 above EMA20, and price sat above the EMA20 a
    # week ago (pullback must come FROM ABOVE).
    if not (ema10[j - 1] > ema20[j - 1] and closes[j - 5] > ema20[j - 5]):
        return {"detected": False, "dt": last["dt"],
                "body_ratio": None, "close_pos": None, "vol_ratio": None}

    # Pullback into the zone between EMA10 and EMA20 within the last 5
    # sessions (low dips to/below EMA10 but holds around the EMA20).
    pulled_back = any(
        bars[k]["low"] <= ema10[k] and bars[k]["low"] >= ema20[k] * 0.98
        for k in range(max(0, j - 5), j)
    )
    if not pulled_back:
        return {"detected": False, "dt": last["dt"],
                "body_ratio": None, "close_pos": None, "vol_ratio": None}

    bodies = [abs(bars[k]["close"] - bars[k]["open"]) for k in range(j - 20, j)]
    avg_body = (sum(bodies) / len(bodies)) or 1e-9
    body = last["close"] - last["open"]
    body_ratio = round(body / avg_body, 2)
    rng = (last["high"] - last["low"]) or 1e-9
    close_pos = round((last["close"] - last["low"]) / rng, 2)
    vols = [bars[k]["volume"] for k in range(j - 20, j)
            if bars[k].get("volume")]
    vol_ratio = (round(last["volume"] / (sum(vols) / len(vols)), 2)
                 if vols and last.get("volume") else None)

    detected = (body > 0
                and body_ratio > 1.6
                and close_pos >= 0.75
                and (vol_ratio is None or vol_ratio > 1.2))
    return {"detected": bool(detected), "dt": last["dt"],
            "body_ratio": body_ratio, "close_pos": close_pos,
            "vol_ratio": vol_ratio}


def latest_ma_signals(conn, within=5):
    """Most recent industry_ma_signal row per industry, restricted to rows
    dated within the last `within` signal dates. Returns
    {industry: {dt, detected, body_ratio, close_pos, vol_ratio, bonus, etf}}.
    """
    try:
        dts = [r[0] for r in conn.execute(
            "SELECT DISTINCT dt FROM industry_ma_signal ORDER BY dt DESC LIMIT ?",
            (within,)).fetchall()]
        if not dts:
            return {}
        rows = conn.execute(
            "SELECT * FROM industry_ma_signal WHERE dt >= ?", (dts[-1],)).fetchall()
    except Exception:
        return {}
    out = {}
    for r in rows:
        cur = out.get(r["industry"])
        if cur is None or r["dt"] > cur["dt"] or (r["dt"] == cur["dt"] and r["detected"] and not cur["detected"]):
            out[r["industry"]] = dict(r)
    return out


def _industry_trend_ok(conn, name, ext_ema20, ext_ema50, chg_1w):
    """Uptrend check: member-EMA alignment (price > EMA20 > EMA50, proxied by
    the average extension over each EMA: ext_ema20 > 0 and
    ext_ema50 > ext_ema20) AND the industry's SMA20 rising vs 5 trading days
    ago — approximated by the 1M performance of the latest industry_snapshot
    being no worse than 5 snapshots back (falls back to chg_1w > 0 when
    fewer than 6 snapshots exist)."""
    if ext_ema20 is None or ext_ema50 is None:
        return False
    aligned = ext_ema20 > 0 and ext_ema50 > ext_ema20
    rising = None
    try:
        rows = conn.execute(
            """SELECT chg_1m FROM industry_snapshot
               WHERE industry=? ORDER BY dt DESC LIMIT 6""", (name,)).fetchall()
        vals = [r["chg_1m"] for r in rows if r["chg_1m"] is not None]
        if len(rows) >= 6 and rows[0]["chg_1m"] is not None and rows[5]["chg_1m"] is not None:
            rising = rows[0]["chg_1m"] >= rows[5]["chg_1m"]
    except Exception:
        rising = None
    if rising is None:
        rising = (chg_1w or 0) > 0
    return bool(aligned and rising)


def _lead_snapshot_history(conn):
    """Per-industry industry_snapshot history helpers for the leaderboard:
    {industry: {"prev": {chg_1w, chg_1m, chg_3m}, "score_chg_5d",
                "rank_5d", "rank_20d", "rank_now", "chg_1m_prev"}}
    score_chg_5d = latest snapshot leadership_score minus the score 5
    snapshot dates back; rank_5d/rank_20d = leadership_rank 5/20 dates back;
    rank_now = latest snapshot leadership_rank. Empty dict without history."""
    try:
        dts = [r[0] for r in conn.execute(
            "SELECT DISTINCT dt FROM industry_snapshot ORDER BY dt DESC LIMIT 21"
        ).fetchall()]
    except Exception:
        return {}
    if not dts:
        return {}
    latest = dts[0]

    def rows_at(dt):
        return {r["industry"]: dict(r) for r in conn.execute(
            """SELECT industry, chg_1w, chg_1m, chg_3m, leadership_score,
                      leadership_rank
               FROM industry_snapshot WHERE dt=?""", (dt,)).fetchall()}

    cur = rows_at(latest)
    prev = rows_at(dts[1]) if len(dts) > 1 else {}
    d5 = rows_at(dts[5]) if len(dts) > 5 else {}
    d20 = rows_at(dts[20]) if len(dts) > 20 else {}
    out = {}
    for name, c in cur.items():
        p = prev.get(name) or {}
        o5 = d5.get(name) or {}
        o20 = d20.get(name) or {}
        sc = c.get("leadership_score")
        so = o5.get("leadership_score")
        out[name] = {
            "prev": {"chg_1w": p.get("chg_1w"), "chg_1m": p.get("chg_1m"),
                     "chg_3m": p.get("chg_3m")},
            "score_chg_5d": round(sc - so, 1) if sc is not None and so is not None else None,
            "rank_now": c.get("leadership_rank"),
            "rank_5d": o5.get("leadership_rank"),
            "rank_20d": o20.get("leadership_rank"),
            "chg_1m_prev": p.get("chg_1m"),
        }
    return out


def _lead_trend_quality(ext_ema20, ext_ema50, breadth_50, breadth_200,
                        chg_1m, chg_1m_prev):
    """100/75/50/25/0 trend rubric. ext_ema20/ext_ema50 are the members'
    average % extension over their EMA20/EMA50, so ext_ema50 > ext_ema20 > 0
    approximates price > EMA20 > EMA50 alignment; chg_1m >= chg_1m_prev
    approximates a rising 20MA (falls back to chg_1m >= 0 without history)."""
    if ext_ema20 is None or ext_ema50 is None:
        return 50.0
    improving = chg_1m >= chg_1m_prev if (chg_1m is not None and chg_1m_prev is not None) \
        else (chg_1m or 0) >= 0
    aligned = ext_ema20 > 0 and ext_ema50 > ext_ema20
    b50 = breadth_50 if breadth_50 is not None else 50.0
    b200 = breadth_200 if breadth_200 is not None else 50.0
    if aligned and b50 >= 55 and b200 >= 50 and improving:
        return 100.0
    if ext_ema50 > 0 and improving:
        return 75.0
    if ext_ema50 < 0:
        # Below the 50MA: 0 only when breadth is deteriorating too.
        return 0.0 if (b50 < 30 and not improving) else 25.0
    return 50.0


def _lead_volume_score(vol_ratio, chg_1w):
    """100/70/40/0-25 volume-confirmation rubric."""
    vr = vol_ratio if vol_ratio is not None else 1.0
    w = chg_1w or 0.0
    if vr > 1.0 and w > 0:
        return 100.0
    if vr >= 1.2 and w < 0:
        # Heavy volume while falling: worse the harder it falls.
        return 25.0 if w > -3 else 0.0
    if w >= 0:
        return 70.0
    return 40.0


def _lead_opportunity_score(ext_ema20, ext_ema50, breadth_20, chg_1w):
    """Opportunity/extension rubric (evolution of the old extension penalty):
    100 = constructive consolidation/pullback near the 10/20EMA zone with
    participation; 70 = healthy but slightly extended; 40 = very extended;
    0 = climactic or breaking down."""
    e20 = ext_ema20 if ext_ema20 is not None else 0.0
    e50 = ext_ema50 if ext_ema50 is not None else 0.0
    b20 = breadth_20 if breadth_20 is not None else 50.0
    if e50 > EXT_EMA50_HARD or e20 > LEAD_EXT_EMA20_CLIMAX:
        return 0.0
    if e20 < -5 and (chg_1w or 0) < 0:
        return 0.0  # breaking down through the EMAs
    if e20 > LEAD_EXT_EMA20_KNEE:
        return 40.0
    if e20 > 4:
        return 70.0
    if -3 <= e20 <= 4 and b20 >= 35:
        return 100.0
    return 70.0


def _lead_reason_chips(r):
    """Explainable reason chips for one scored industry row."""
    chips = []
    c = r["components"]
    if (r.get("breadth_50") or 0) >= 60:
        chips.append("Broad participation")
    if (r.get("breadth_50") or 100) < 40:
        chips.append("Weak breadth")
    if c["sustained_rs"] >= 70:
        chips.append("Sustained RS leader")
    if r["rs"]["rs_1w"] > 0 and r["rs"]["rs_1m"] > 0:
        chips.append("RS improving")
    if (r["rs"]["rs_1m"] or 0) < 0:
        chips.append("RS lagging")
    if (r.get("ext_ema50") or 0) < 0:
        chips.append("Below 50MA")
    if (r.get("ext_ema20") or 0) > LEAD_EXT_EMA20_KNEE or (r.get("ext_ema50") or 0) > EXT_EMA50_HARD:
        chips.append("Extended")
    if c["opportunity"] >= 100:
        chips.append("Pullback setup")
    if (r.get("pct_new_highs") or 0) >= 20:
        chips.append("New highs expanding")
    if (r.get("vol_ratio") or 1) > 1.2 and (r.get("chg_1w") or 0) > 0:
        chips.append("Volume confirming")
    if (r.get("rank_chg_5d") or 0) >= 3:
        chips.append("Rotating up")
    return chips[:5]


def industry_leaderboard_scores(conn, limit=LEAD_LIST_LIMIT, profile=LEAD_PROFILE_DEFAULT):
    """Build the /api/leaderboards payload: the two-stage 100-point industry
    ranking (eligibility status gate + Leadership Score). See the section
    comment above for the component formulas and weight profiles."""
    weights = LEAD_PROFILES.get(profile, LEAD_PROFILES[LEAD_PROFILE_DEFAULT])["w"]
    rows = [dict(r) for r in conn.execute(
        """SELECT industry, sector_id, price, ema20, ema50,
                  chg_1w, chg_1m, chg_3m, chg_6m,
                  above_20d, above_50d, above_200d, above_100ema, volume_ratio,
                  dist_high_3m, pct_from_52w_high
           FROM stock
           WHERE ticker != ? AND industry IS NOT NULL AND industry != ''
             AND market_cap_musd >= ? AND avg_volume >= ?
             AND (adr_pct IS NULL OR adr_pct >= ?)
             AND price >= ?""",
        (BENCHMARK_TICKER, MIN_MARKET_CAP_MUSD, MIN_AVG_VOLUME, MIN_ADR_PCT,
         MIN_PRICE),
    ).fetchall()]
    by_industry = {}
    for r in rows:
        by_industry.setdefault(r["industry"], []).append(r)

    # SPY horizon returns for the RS baseline (SPY sits in the stock table).
    spy = conn.execute(
        "SELECT chg_1w, chg_1m, chg_3m, chg_6m FROM stock WHERE ticker=?",
        (BENCHMARK_TICKER,)).fetchone()
    spy = dict(spy) if spy else {}

    sector_names = {r["id"]: r["name"] for r in conn.execute(
        "SELECT id, name FROM sector").fetchall()}
    signals = latest_ma_signals(conn)
    history = _lead_snapshot_history(conn)

    def avgf(members, key):
        vals = [m[key] for m in members if m.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    def avg_ext(members, ema_key):
        vals = [(m["price"] / m[ema_key] - 1) * 100
                for m in members
                if m.get("price") and m.get(ema_key)]
        return round(sum(vals) / len(vals), 2) if vals else None

    def pct_of(members, cond):
        return round(sum(1 for m in members if cond(m)) / len(members) * 100, 1)

    def near_high(m):
        d = m.get("dist_high_3m")
        if d is None:
            d = m.get("pct_from_52w_high")
        return d is not None and d >= -5

    aggs = []
    for name, members in by_industry.items():
        if len(members) < IND_MIN_STOCKS:
            continue
        sids = [m.get("sector_id") for m in members if m.get("sector_id") is not None]
        chg_1w = avgf(members, "chg_1w")
        chg_1m = avgf(members, "chg_1m")
        chg_3m = avgf(members, "chg_3m")
        chg_6m = avgf(members, "chg_6m")
        ext20 = avg_ext(members, "ema20")
        ext50 = avg_ext(members, "ema50")
        b20 = pct_of(members, lambda m: m.get("above_20d"))
        b50 = pct_of(members, lambda m: (m.get("above_100ema") if m.get("above_100ema") is not None else m.get("above_50d")))
        b200 = (pct_of(members, lambda m: m.get("above_200d"))
                if any(m.get("above_200d") is not None for m in members) else None)
        hist = history.get(name) or {}
        prev = hist.get("prev") or {}
        aggs.append({
            "industry": name,
            "sector_id": max(set(sids), key=sids.count) if sids else None,
            "stocks": len(members),
            "chg_1w": chg_1w, "chg_1m": chg_1m, "chg_3m": chg_3m,
            "chg_6m": chg_6m,
            "rs_1w": round((chg_1w or 0) - (spy.get("chg_1w") or 0), 2),
            "rs_1m": round((chg_1m or 0) - (spy.get("chg_1m") or 0), 2),
            "rs_3m": round((chg_3m or 0) - (spy.get("chg_3m") or 0), 2),
            "rs_6m": round((chg_6m or 0) - (spy.get("chg_6m") or 0), 2),
            "breadth_20": b20, "breadth_50": b50, "breadth_200": b200,
            "pct_new_highs": pct_of(members, near_high),
            "vol_ratio": avgf(members, "volume_ratio"),
            "ext_ema20": ext20, "ext_ema50": ext50,
            "score_chg_5d": hist.get("score_chg_5d"),
            "rank_5d": hist.get("rank_5d"), "rank_20d": hist.get("rank_20d"),
            "rank_now": hist.get("rank_now"),
            "chg_1m_prev": prev.get("chg_1m"),
            "prev_1w": prev.get("chg_1w"), "prev_1m": prev.get("chg_1m"),
        })
    empty = {"generated_at": datetime.now().isoformat(), "universe": 0,
             "profile": profile,
             "profiles": [{"id": k, "label": v["label"]} for k, v in LEAD_PROFILES.items()],
             "rows": [], "lists": {"leadership": [], "actionable": [],
                                   "rotation": [], "risk": []},
             "sustaining": [], "sustaining_all": [], "recent": [], "pullback": []}
    if not aggs:
        return empty

    # Percentile universes for the cross-industry components.
    rs1w_vals = [a["rs_1w"] for a in aggs]
    rs1m_vals = [a["rs_1m"] for a in aggs]
    rs3m_vals = [a["rs_3m"] for a in aggs]
    rs6m_vals = [a["rs_6m"] for a in aggs]
    schg_vals = [a["score_chg_5d"] for a in aggs if a["score_chg_5d"] is not None]
    # Rank improvement: positive when the industry's snapshot rank improved
    # (dropped in number) vs 5 snapshot dates back.
    for a in aggs:
        a["rank_impr_5d"] = (a["rank_5d"] - a["rank_now"]
                             if a["rank_5d"] is not None and a["rank_now"] is not None
                             else None)
    rimpr_vals = [a["rank_impr_5d"] for a in aggs if a["rank_impr_5d"] is not None]

    out_rows = []
    for a in aggs:
        n = a["stocks"]
        # --- components (0-100 each unless noted) ---
        c_rs = 0.60 * _percentile_rank(rs3m_vals, a["rs_3m"]) \
            + 0.40 * _percentile_rank(rs6m_vals, a["rs_6m"])
        c_recent = 0.35 * _percentile_rank(rs1w_vals, a["rs_1w"]) \
            + 0.65 * _percentile_rank(rs1m_vals, a["rs_1m"])
        # Recent-momentum bonus (score points, max +5): 1W and 1M RS both
        # positive and improving vs the prior snapshot.
        mom_bonus = 0.0
        if a["rs_1w"] > 0 and a["rs_1m"] > 0:
            imp_w = a["prev_1w"] is None or (a["chg_1w"] or 0) >= a["prev_1w"]
            imp_m = a["prev_1m"] is None or (a["chg_1m"] or 0) >= a["prev_1m"]
            mom_bonus = 5.0 if (imp_w and imp_m) else (2.5 if (imp_w or imp_m) else 0.0)
        breadth_raw = (0.20 * (a["breadth_20"] or 0)
                       + 0.60 * (a["breadth_50"] or 0)
                       + 0.20 * (a["pct_new_highs"] or 0))
        conf_adj = min(1.0, n / 10.0)
        c_breadth = breadth_raw * conf_adj
        c_trend = _lead_trend_quality(a["ext_ema20"], a["ext_ema50"],
                                      a["breadth_50"], a["breadth_200"],
                                      a["chg_1m"], a["chg_1m_prev"])
        p_schg = (_percentile_rank(schg_vals, a["score_chg_5d"])
                  if schg_vals and a["score_chg_5d"] is not None else 50.0)
        p_rimpr = (_percentile_rank(rimpr_vals, a["rank_impr_5d"])
                   if rimpr_vals and a["rank_impr_5d"] is not None else 50.0)
        c_rotation = 0.60 * p_schg + 0.40 * p_rimpr
        # Acceleration bonus only when recent momentum is positive.
        if a["rs_1w"] > 0 and a["rs_1m"] > 0 and (a["score_chg_5d"] or 0) > 0:
            c_rotation = min(100.0, c_rotation + 10.0)
        c_volume = _lead_volume_score(a["vol_ratio"], a["chg_1w"])
        c_opp = _lead_opportunity_score(a["ext_ema20"], a["ext_ema50"],
                                        a["breadth_20"], a["chg_1w"])
        comps = {"sustained_rs": round(c_rs, 1), "recent_mom": round(c_recent, 1),
                 "breadth": round(c_breadth, 1), "trend": c_trend,
                 "rotation": round(c_rotation, 1), "volume": c_volume,
                 "opportunity": c_opp}
        breakdown = {k: {"points": round(weights[k] * comps[k] / 100, 1),
                         "max": weights[k]}
                     for k in weights}
        score = sum(b["points"] for b in breakdown.values()) + mom_bonus

        # --- stage 1: eligibility status ---
        ext20, ext50 = a["ext_ema20"], a["ext_ema50"]
        b50 = a["breadth_50"] if a["breadth_50"] is not None else 50.0
        excessively_ext = ((ext20 is not None and ext20 > LEAD_EXT_EMA20_KNEE)
                           or (ext50 is not None and ext50 > EXT_EMA50_HARD))
        weak_multi = c_rs < 40 and c_recent < 40
        if a["rs_1m"] < 0 and b50 < 40 and weak_multi:
            status = "avoid"
            score = min(score, 39.0)
        elif excessively_ext and a["rs_1m"] > 0:
            status = "extended"
        elif (ext50 is not None and ext50 > 0 and b50 >= 50
              and a["rs_1m"] > 0 and not excessively_ext):
            status = "actionable"
        elif (ext50 is not None and ext50 < 0) or b50 < 40:
            status = "watchlist" if (a["rs_1w"] > 0 or (a["score_chg_5d"] or 0) > 0) else "avoid"
            if status == "avoid":
                score = min(score, 39.0)
        else:
            status = "emerging"

        # --- five-state classification ---
        sustained_mid = c_rs >= 45
        recent_pos, recent_strong = c_recent >= 50, c_recent >= 70
        if sustained_mid and recent_pos:
            state = "Leading"
        elif sustained_mid and not recent_pos:
            state = "Fading"
        elif not sustained_mid and recent_strong:
            state = "Emerging"
        elif not sustained_mid and recent_pos:
            state = "Recovering"
        else:
            state = "Lagging"

        confidence = ("High" if n >= 25 and a["breadth_50"] is not None
                      else "Medium" if n >= 10 else "Low")

        sig = signals.get(a["industry"])
        sid = a["sector_id"]
        out_rows.append({
            "industry": a["industry"],
            "sector": sector_names.get(sid),
            "sector_id": sid,
            "color": SECTOR_COLORS[(sid - 1) % len(SECTOR_COLORS)] if sid else None,
            "stocks": n,
            "chg_1w": a["chg_1w"], "chg_1m": a["chg_1m"], "chg_3m": a["chg_3m"],
            "chg_6m": a["chg_6m"],
            "rs": {"rs_1w": a["rs_1w"], "rs_1m": a["rs_1m"],
                   "rs_3m": a["rs_3m"], "rs_6m": a["rs_6m"]},
            "breadth_20": a["breadth_20"], "breadth_50": a["breadth_50"],
            "breadth_200": a["breadth_200"],
            "pct_new_highs": a["pct_new_highs"], "vol_ratio": a["vol_ratio"],
            "ext_ema20": ext20, "ext_ema50": ext50,
            "extension": {"ema20": ext20, "ema50": ext50},
            "trend_ok": _industry_trend_ok(conn, a["industry"], ext20, ext50, a["chg_1w"]),
            "components": comps,
            "breakdown": breakdown,
            "mom_bonus": mom_bonus,
            "score": round(min(100.0, max(0.0, score)), 1),
            "leadership_score": round(min(100.0, max(0.0, score)), 1),
            "opportunity_score": round(c_opp, 1),
            "state": state, "status": status, "confidence": confidence,
            "rank_chg_5d": (a["rank_5d"] - a["rank_now"]
                            if a["rank_5d"] is not None and a["rank_now"] is not None else None),
            "rank_chg_20d": (a["rank_20d"] - a["rank_now"]
                             if a["rank_20d"] is not None and a["rank_now"] is not None else None),
            "score_chg_5d": a["score_chg_5d"],
            "pattern": {
                "detected": bool(sig and sig.get("detected")),
                "date": sig["dt"] if sig else None,
                "body_ratio": sig.get("body_ratio") if sig else None,
                "close_pos": sig.get("close_pos") if sig else None,
                "vol_ratio": sig.get("vol_ratio") if sig else None,
            },
        })

    for r in out_rows:
        r["actionable_score"] = round(
            0.65 * r["leadership_score"] + 0.35 * r["opportunity_score"], 1)
        r["reasons"] = _lead_reason_chips(r)

    def rank_assign(rows, key):
        ordered = sorted(rows, key=lambda r: (-r[key], r["industry"]))
        for i, r in enumerate(ordered):
            r[key + "_rank"] = i + 1
        return ordered

    by_leadership = rank_assign(out_rows, "leadership_score")
    by_opp = rank_assign(out_rows, "opportunity_score")
    by_rot = sorted(out_rows, key=lambda r: (-r["components"]["rotation"], r["industry"]))
    for i, r in enumerate(by_rot):
        r["rotation_rank"] = i + 1
    # Risk: low trend quality + weak breadth + extension = high risk.
    for r in out_rows:
        r["risk_score"] = round(
            100 - (0.45 * r["components"]["trend"]
                   + 0.45 * r["components"]["breadth"]
                   + 0.10 * r["components"]["opportunity"]), 1)
    by_risk = sorted(out_rows, key=lambda r: (r["risk_score"], r["industry"]))
    for i, r in enumerate(by_risk):
        r["risk_rank"] = i + 1

    actionable = sorted((r for r in out_rows if r["status"] == "actionable"),
                        key=lambda r: (-r["actionable_score"], r["industry"]))
    recent_sorted = sorted(out_rows,
                           key=lambda r: (-r["components"]["recent_mom"], r["industry"]))
    pullback = sorted((r for r in out_rows if r["pattern"]["detected"]),
                      key=lambda r: (-r["leadership_score"],
                                     -(r["pattern"]["body_ratio"] or 0)))[:limit]
    return {
        "generated_at": datetime.now().isoformat(),
        "universe": len(out_rows),
        "profile": profile,
        "profiles": [{"id": k, "label": v["label"]} for k, v in LEAD_PROFILES.items()],
        "weights": weights,
        "rows": by_leadership,
        "lists": {
            "leadership": by_leadership[:limit],
            "actionable": actionable[:limit],
            "rotation": by_rot[:limit],
            "risk": by_risk[:limit],
        },
        # Backward-compatible aliases (sustaining == leadership ranking).
        "sustaining": by_leadership[:limit],
        "sustaining_all": by_leadership,
        "recent": recent_sorted[:limit],
        "pullback": pullback,
    }


def _generate_demo_industry_extras(conn):
    """Demo-mode synthesis for the leaderboards: ~30 days of industry_snapshot
    history (random-walked backwards from the current stock aggregates so
    the trend filter and rotation deltas have something to chew on) and
    MA-pullback signal rows from a synthetic OHLC random walk per industry
    benchmark ETF run through the real detector."""
    c = conn.cursor()
    stocks = [dict(r) for r in c.execute(
        """SELECT industry, sector_id, chg_1w, chg_1m, chg_3m, chg_6m,
                  above_20d, above_50d, above_200d, above_100ema, volume_ratio
           FROM stock
           WHERE ticker != ? AND industry IS NOT NULL AND industry != ''
             AND market_cap_musd >= ? AND avg_volume >= ?
             AND (adr_pct IS NULL OR adr_pct >= ?)
             AND price >= ?""",
        (BENCHMARK_TICKER, MIN_MARKET_CAP_MUSD, MIN_AVG_VOLUME, MIN_ADR_PCT,
         MIN_PRICE),
    ).fetchall()]
    by_industry = {}
    for r in stocks:
        by_industry.setdefault(r["industry"], []).append(r)

    def avgf(members, key):
        vals = [m[key] for m in members if m.get(key) is not None]
        return sum(vals) / len(vals) if vals else 0.0

    base = {}
    for name, members in by_industry.items():
        sids = [m.get("sector_id") for m in members if m.get("sector_id") is not None]
        base[name] = {
            "sector_id": max(set(sids), key=sids.count) if sids else None,
            "stock_count": len(members),
            "chg_1w": avgf(members, "chg_1w"), "chg_1m": avgf(members, "chg_1m"),
            "chg_3m": avgf(members, "chg_3m"), "chg_6m": avgf(members, "chg_6m"),
            "breadth_20": sum(1 for m in members if m.get("above_20d")) / len(members) * 100,
            "breadth_50": sum(1 for m in members if (m.get("above_100ema") if m.get("above_100ema") is not None else m.get("above_50d"))) / len(members) * 100,
            "breadth_200": sum(1 for m in members if m.get("above_200d")) / len(members) * 100,
            "vol_ratio": avgf(members, "volume_ratio") or 1.0,
        }

    # industry_snapshot history: walk each industry's aggregates backwards
    # with mean-reverting noise so some industries trend and some don't.
    c.execute("DELETE FROM industry_snapshot")
    hist = {}
    for name, b in base.items():
        drift = random.uniform(-0.6, 0.6)
        w1, m1, m3 = b["chg_1w"], b["chg_1m"], b["chg_3m"]
        b20, b50 = b["breadth_20"], b["breadth_50"]
        series = []
        for i in range(30):
            series.append((round(w1, 2), round(m1, 2), round(m3, 2),
                           round(min(95, max(5, b20)), 1),
                           round(min(95, max(5, b50)), 1)))
            w1 += random.uniform(-0.9, 0.9) - drift
            m1 += random.uniform(-0.7, 0.7) - drift
            m3 += random.uniform(-0.5, 0.5) - drift * 0.5
            b20 += random.uniform(-4, 4) - drift * 2
            b50 += random.uniform(-3, 3) - drift * 1.5
        hist[name] = list(reversed(series))  # oldest first
    for i in range(30):
        d = (date.today() - timedelta(days=29 - i)).isoformat()
        day_rows = []
        for name, series in hist.items():
            w1, m1, m3, b20, b50 = series[i]
            day_rows.append({"industry": name, "sector_id": base[name]["sector_id"],
                             "stock_count": base[name]["stock_count"],
                             "chg_1w": w1, "chg_1m": m1, "chg_3m": m3,
                             "breadth_20": b20, "breadth_50": b50,
                             "breadth_200": base[name]["breadth_200"],
                             "vol_ratio": base[name]["vol_ratio"]})
        scores = industry_leadership_scores(day_rows)
        ranked = sorted((r for r in day_rows if scores.get(r["industry"])),
                        key=lambda r: scores[r["industry"]]["leadership_score"],
                        reverse=True)
        ranks = {r["industry"]: n + 1 for n, r in enumerate(ranked)}
        for r in day_rows:
            ls = scores.get(r["industry"])
            c.execute(
                """INSERT OR REPLACE INTO industry_snapshot
                   (dt, industry, sector_id, chg_1d, chg_1w, chg_1m, chg_3m, chg_6m,
                    breadth_20, breadth_50, breadth_200, pct_new_highs, vol_ratio,
                    leadership_score, leadership_rank, stocks_count)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (d, r["industry"], r["sector_id"], None, r["chg_1w"], r["chg_1m"],
                 r["chg_3m"], None, r["breadth_20"], r["breadth_50"], r["breadth_200"],
                 None, r["vol_ratio"],
                 ls["leadership_score"] if ls else None,
                 ranks.get(r["industry"]), r["stock_count"]),
            )

    # MA-pullback signals: synthetic 90-session OHLC random walk per industry
    # ETF; a few industries get a deliberately planted pullback+green-candle
    # pattern so the demo leaderboard shows live-looking detections.
    c.execute("DELETE FROM industry_ma_signal")
    names = sorted(base.keys())
    for idx, name in enumerate(names):
        etf = INDUSTRY_ETF_MAP.get(name)
        price = random.uniform(30, 300)
        drift = random.uniform(-0.15, 0.25) / 100
        bars = []
        for i in range(90):
            d = (date.today() - timedelta(days=89 - i)).isoformat()
            o = price
            c2 = price * (1 + random.uniform(-0.015, 0.015) + drift)
            h = max(o, c2) * (1 + random.uniform(0, 0.008))
            l = min(o, c2) * (1 - random.uniform(0, 0.008))
            v = random.uniform(0.7, 1.4) * 1_000_000
            bars.append({"dt": d, "open": round(o, 2), "close": round(c2, 2),
                         "high": round(h, 2), "low": round(l, 2), "volume": round(v)})
            price = c2
        # Plant a textbook pattern in ~1/4 of industries: 10 sessions of
        # uptrend, a 3-session pullback, then a big green candle on volume.
        if idx % 4 == 0:
            base_p = bars[-12]["close"]
            p = base_p
            for k in range(-12, -4):
                p = p * 1.012
                bars[k] = {"dt": bars[k]["dt"], "open": round(p / 1.008, 2),
                           "close": round(p, 2), "high": round(p * 1.004, 2),
                           "low": round(p / 1.012 * 0.998, 2),
                           "volume": round(random.uniform(0.8, 1.2) * 1_000_000)}
            # pullback: lows drift down into the EMA10-EMA20 zone
            p_down = p
            for k in range(-4, -1):
                p_down = p_down * 0.994
                o = p_down * 1.002
                bars[k] = {"dt": bars[k]["dt"], "open": round(o, 2),
                           "close": round(p_down, 2), "high": round(o * 1.002, 2),
                           "low": round(p_down * 0.988, 2),
                           "volume": round(random.uniform(0.7, 1.0) * 1_000_000)}
            # strong green candle: ~3x average body, closes near the high,
            # on elevated volume
            o = p_down * 0.995
            c2 = o * 1.03
            bars[-1] = {"dt": bars[-1]["dt"], "open": round(o, 2),
                        "close": round(c2, 2), "high": round(c2 * 1.002, 2),
                        "low": round(o * 0.998, 2),
                        "volume": round(1_000_000 * 1.6)}
        # Score each of the last 5 sessions with the real detector.
        for back in range(5, 0, -1):
            res = detect_ma_pullback_signal(bars[:-back + 1] if back > 1 else bars)
            if res is None:
                continue
            sig_dt = bars[-back]["dt"]
            c.execute(
                """INSERT OR REPLACE INTO industry_ma_signal
                   (dt, industry, etf, detected, body_ratio, close_pos, vol_ratio, bonus)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (sig_dt, name, etf, int(res["detected"]), res["body_ratio"],
                 res["close_pos"], res["vol_ratio"],
                 PATTERN_BONUS if res["detected"] else 0.0),
            )


def compute_industry_snapshots(conn, dt, strategy="qullamaggie"):
    """Aggregate the freshly-synced `stock` rows into one industry_snapshot
    row per industry for `dt` and INSERT OR REPLACE them. Mirrors the
    aggregation done by main.py's _industry_aggregate / _enrich_industry_rows
    (simple averages, breadth from above_20d/above_50d/above_200d, leadership
    score via industry_leadership_scores). Returns the list of snapshot dicts.
    The `strategy` arg is accepted for signature compatibility with the sector
    snapshots; the industry leadership score is strategy-independent.
    """
    rows = [dict(r) for r in conn.execute(
        """SELECT * FROM stock
           WHERE ticker != ? AND industry IS NOT NULL AND industry != ''
             AND market_cap_musd >= ? AND avg_volume >= ?
             AND (adr_pct IS NULL OR adr_pct >= ?)
             AND price >= ?""",
        (BENCHMARK_TICKER, MIN_MARKET_CAP_MUSD, MIN_AVG_VOLUME, MIN_ADR_PCT,
         MIN_PRICE),
    ).fetchall()]
    by_industry = {}
    for r in rows:
        by_industry.setdefault(r["industry"], []).append(r)

    def avgf(members, key, digits=2):
        vals = [r[key] for r in members if r.get(key) is not None]
        return round(sum(vals) / len(vals), digits) if vals else None

    def pct(members, cond):
        return round(sum(1 for r in members if cond(r)) / len(members) * 100, 1)

    def near_high(r):
        d = r.get("dist_high_3m")
        if d is None:
            d = r.get("pct_from_52w_high")
        return d is not None and d >= -5

    has_200d = any(r.get("above_200d") is not None for r in rows)
    out = []
    for name, members in by_industry.items():
        sids = [m.get("sector_id") for m in members if m.get("sector_id") is not None]
        out.append({
            "industry": name,
            "sector_id": max(set(sids), key=sids.count) if sids else None,
            "stock_count": len(members),
            "chg_1d": avgf(members, "chg_1d"),
            "chg_1w": avgf(members, "chg_1w"),
            "chg_1m": avgf(members, "chg_1m"),
            "chg_3m": avgf(members, "chg_3m"),
            "chg_6m": avgf(members, "chg_6m"),
            "breadth_20": pct(members, lambda r: r["above_20d"]),
            "breadth_50": pct(members, lambda r: (r["above_100ema"] if r.get("above_100ema") is not None else r["above_50d"])),
            "breadth_200": pct(members, lambda r: r["above_200d"]) if has_200d else None,
            "pct_new_highs": pct(members, near_high),
            "vol_ratio": avgf(members, "volume_ratio"),
        })

    ind_cci = industry_cci_factors(conn)
    sector_cci = sector_cci_factors(conn)
    scores = industry_leadership_scores(out, ind_cci, sector_cci, cci_market_factor(conn))
    for row in out:
        ls = scores.get(row["industry"])
        row["leadership_score"] = ls["leadership_score"] if ls else None
    ranked = sorted(
        (r for r in out if r["leadership_score"] is not None),
        key=lambda r: r["leadership_score"], reverse=True)
    for i, r in enumerate(ranked):
        r["leadership_rank"] = i + 1
    for r in out:
        r.setdefault("leadership_rank", None)

    for r in out:
        conn.execute(
            """INSERT OR REPLACE INTO industry_snapshot
               (dt, industry, sector_id, chg_1d, chg_1w, chg_1m, chg_3m, chg_6m,
                breadth_20, breadth_50, breadth_200, pct_new_highs, vol_ratio,
                leadership_score, leadership_rank, stocks_count)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (dt, r["industry"], r["sector_id"], r["chg_1d"], r["chg_1w"], r["chg_1m"],
             r["chg_3m"], r["chg_6m"], r["breadth_20"], r["breadth_50"], r["breadth_200"],
             r["pct_new_highs"], r["vol_ratio"], r["leadership_score"],
             r["leadership_rank"], r["stock_count"]),
        )
    return out


def cci_market_factor(conn):
    """Compulsory CCI input for the stock composite: the average CCI(34)
    rating across the major indices (SPY/QQQ/DJI/IWM) mapped to 0-100
    (Bearish -> 0, Neutral -> 50, Bullish -> 100)."""
    try:
        rows = conn.execute("SELECT rating FROM index_cci").fetchall()
    except Exception:
        return 50.0
    scores = [CCI_RATING_SCORE[r["rating"]] for r in rows
              if r["rating"] in CCI_RATING_SCORE]
    if not scores:
        return 50.0
    return round(50 + 50 * sum(scores) / len(scores), 1)


def score_and_rank(holdings_with_stock, strategy=STRATEGY_DEFAULT, cci_factor=50.0):
    """Composite setup score (0-100) over the shared factor framework, using the
    Qullamaggie strategy weights. CCI (market regime) is a compulsory input
    (fixed 10% weight); the remaining factors are 1M/3M momentum leadership,
    tightness near highs, trend alignment and volume, minus extension and
    volatility penalties. Classifies leader/neutral/laggard by decile."""
    if strategy not in STRATEGY_DEFS:
        strategy = STRATEGY_DEFAULT
    cfg = STRATEGY_DEFS[strategy]
    W = cfg["w"]
    filtered = apply_filters(holdings_with_stock)
    excluded_count = len(holdings_with_stock) - len(filtered)

    if not filtered:
        return [], excluded_count

    mom1m_vals = [r["chg_1m"] for r in filtered]
    high_vals = [r["pct_from_52w_high"] for r in filtered]
    vol_vals = [r["volume_ratio"] for r in filtered]

    def breakout_points(r):
        # Proximity to the 1M/3M high: full points within 3%, fading to 0 at 15%+ below.
        dists = [d for d in (r.get("dist_high_1m"), r.get("dist_high_3m")) if d is not None]
        if dists:
            dist = max(dists)  # closest to a pivot high
        else:
            dist = r["pct_from_52w_high"]
        if dist is None:
            return 50.0
        return max(0.0, min(100.0, (15 + dist) / 15 * 100))  # dist<=0

    def extension_penalty(r):
        # Chasing risk: penalize extension above the EMA10 past the knee.
        ext = r.get("ext_ema10")
        if ext is None:
            return 0.0
        return min(cfg["ext_cap"], max(0.0, (ext - cfg["ext_knee"]) * cfg["ext_slope"]))

    def volatility_penalty(r):
        vol = r.get("volatility_d")
        if vol is None:
            return 0.0
        return min(cfg["vol_cap"], max(0.0, (vol - cfg["vol_knee"]) * cfg["vol_slope"]))

    cci_pts = cci_factor if cci_factor is not None else 50.0  # compulsory CCI input

    for r in filtered:
        factors = {
            "rs": (r["rs_rating"] or 50.0),
            "mom1m": _percentile_rank(mom1m_vals, r["chg_1m"]),
            "high": _percentile_rank(high_vals, r["pct_from_52w_high"]),
            "vol": _percentile_rank(vol_vals, r["volume_ratio"]),
            "above20": 100 if r["above_20d"] else 0,
            "above50": 100 if r["above_50d"] else 0,
            "above200": 100 if r.get("above_200d") else 0,
            "breakout": breakout_points(r),
            "cci": cci_pts,
        }
        score = sum(W[k] * factors[k] for k in W)
        score -= extension_penalty(r) + volatility_penalty(r)
        r["score"] = round(min(100.0, max(0.0, score)), 2)
        # contributing factors for the strategy-specific composite display
        r["composite_factors"] = {k: round(factors[k], 1) for k in factors}

    filtered.sort(key=lambda r: (-r["score"], r.get("ticker") or r.get("stock_ticker") or ""))
    n = len(filtered)
    decile = max(1, round(n * 0.1))
    for i, r in enumerate(filtered):
        if i < decile:
            r["classification"] = "leader"
        elif i >= n - decile:
            r["classification"] = "laggard"
        else:
            r["classification"] = "neutral"
        r["rank"] = i + 1

    return filtered, excluded_count


def concentration_index(filtered_holdings):
    """Herfindahl-style index on weight * |return| contribution, 0-100 scale."""
    contribs = [abs(r["weight_pct"] * r["chg_1m"]) for r in filtered_holdings]
    total = sum(contribs) or 1
    shares = [c / total for c in contribs]
    hhi = sum(s ** 2 for s in shares) * 100
    return round(hhi, 2)


def classify_sector_state(score, breadth, avg_rs, prev_score=None):
    """Classify a sector's rotation state for swing-trading rotation analysis."""
    score = score or 0
    breadth = breadth or 0
    avg_rs = avg_rs or 0
    velocity = (score - prev_score) if prev_score is not None else 0

    if score >= 65 and breadth >= 55 and avg_rs >= 60:
        return "leader"
    if score <= 35 and (breadth <= 45 or avg_rs <= 45):
        return "lagging"
    if velocity >= 2 and score >= 50 and avg_rs >= 50:
        return "emerging"
    if velocity <= -2 and score < 60 and avg_rs < 60:
        return "fading"
    if score >= 55 and avg_rs >= 55:
        return "leader"
    if score <= 45 and avg_rs <= 45:
        return "lagging"
    if velocity >= 1.5 and score >= 45 and avg_rs >= 45:
        return "emerging"
    if velocity <= -1.5 and score < 65 and avg_rs < 65:
        return "fading"
    return "neutral"


def sector_composite_score(perf_3m, breadth, pct_new_highs, avg_vol_ratio, concentration):
    """DEPRECATED legacy composite — kept only so older snapshot columns stay
    interpretable. The canonical sector score is now CCI-based (see
    cci_sector_scores): 50% performance + 50% CCI."""
    perf_score = min(100.0, max(0.0, (perf_3m + 20) / 60 * 100))
    vol_score = min(100.0, max(0.0, (avg_vol_ratio - 0.8) * 100))
    score = (
        0.50 * perf_score
        + 0.25 * (breadth or 0)
        + 0.15 * (pct_new_highs or 0)
        + 0.10 * vol_score
    )
    conc_penalty = max(0, (concentration - 25) * 0.3)
    return round(min(100, max(0, score - conc_penalty)), 1)


def qullamaggie_scan_scores(stats_list):
    """Qullamaggie-style weekly sector scan ("Sunday routine"), 0-100 per sector.

    Cross-sector point system (needs every sector's stats to rank top 3):
      top 3 by 1M performance:                      +3
      top 3 by 3M performance:                      +3
      top 3 by 6M performance:                      +2
      acceleration bonus (1M*12 > 3M*4, 1M > 0):    +2
      1M performance negative:                      -3 (eliminate)
      1W performance positive:                      +1
      daily-chart confirmation (breadth >= 50):     +1
      RS vs SPY positive (true leadership):         +1
    Points are normalized to 0-100 by the maximum attainable (13).

    stats_list: [{"sector_id", "perf_1w", "perf_1m", "perf_3m", "perf_6m",
                  "breadth", "rs_vs_spy"}, ...]
    Returns {sector_id: score}.
    """
    def top3(key):
        ranked = sorted(stats_list, key=lambda s: s.get(key) or -999, reverse=True)
        return {s["sector_id"] for s in ranked[:3] if (s.get(key) or 0) > 0}

    t1, t3, t6 = top3("perf_1m"), top3("perf_3m"), top3("perf_6m")
    out = {}
    for s in stats_list:
        sid = s["sector_id"]
        p1 = s.get("perf_1m") or 0
        p3 = s.get("perf_3m") or 0
        pts = 0
        if sid in t1:
            pts += 3
        if sid in t3:
            pts += 3
        if sid in t6:
            pts += 2
        if p1 > 0 and p1 * 12 > p3 * 4:  # accelerating: 1M annualized beats 3M annualized
            pts += 2
        if p1 < 0:
            pts -= 3
        if (s.get("perf_1w") or 0) > 0:
            pts += 1
        if (s.get("breadth") or 0) >= 50:
            pts += 1
        if (s.get("rs_vs_spy") or 0) > 0:
            pts += 1
        out[sid] = round(max(0, pts) / 13 * 100, 1)
    return out


def rotation_health_score(breadth, concentration, dispersion, avg_rs):
    """0-100: high breadth + low concentration + healthy dispersion + strong RS."""
    conc_inv = max(0, 100 - concentration)
    score = 0.35 * breadth + 0.25 * conc_inv + 0.20 * min(100, dispersion) + 0.20 * avg_rs
    return round(min(100, max(0, score)), 1)


# ---------------------------------------------------------------------------
# CCI-based sector ranking (the canonical sector score)
#
# Everything in the sector score is determined by performance and CCI:
#   Final Score = 50% Performance + 50% CCI
# Performance component (weighted, then min-max normalized across sectors to
# 0-100 before combining):
#   1 week: 15%   1 month: 50%   3 months: 35%
# The CCI component (0-100) is the CCI(34) rating factor of the sector's proxy
# ETF (SECTOR_ETF_MAP); sectors without an ETF CCI value fall back to the
# market-wide CCI factor (average across SPY/QQQ/DJI/IWM).
# ---------------------------------------------------------------------------
PERF_W_1W = 0.15
PERF_W_1M = 0.50
PERF_W_3M = 0.35
SECTOR_W_PERF = 0.50
SECTOR_W_CCI = 0.50


def performance_component(s):
    """Raw weighted sector performance: 15% 1W + 50% 1M + 35% 3M (in %)."""
    return (PERF_W_1W * (s.get("perf_1w") or 0)
            + PERF_W_1M * (s.get("perf_1m") or 0)
            + PERF_W_3M * (s.get("perf_3m") or 0))


def sector_performance_scores(stats_list):
    """Min-max normalize the weighted performance component across sectors to
    0-100 (best sector = 100, worst = 0).

    stats_list: [{"sector_id", "perf_1w", "perf_1m", "perf_3m", ...}, ...]
    Returns {sector_id: 0-100}.
    """
    raws = {s["sector_id"]: performance_component(s) for s in stats_list}
    if not raws:
        return {}
    mn, mx = min(raws.values()), max(raws.values())
    span = (mx - mn) or 1.0
    return {sid: round((v - mn) / span * 100, 1) for sid, v in raws.items()}


def cci_sector_scores(stats_list, cci_factor=50.0, cci_by_sector=None):
    """Final sector score: 50% normalized performance + 50% CCI (0-100)."""
    perf = sector_performance_scores(stats_list)
    fallback = cci_factor if cci_factor is not None else 50.0
    cci_by_sector = cci_by_sector or {}
    return {sid: round(SECTOR_W_PERF * p + SECTOR_W_CCI * cci_by_sector.get(sid, fallback), 1)
            for sid, p in perf.items()}


def strategy_sector_scores(stats_list, strategy, cci_factor=50.0, cci_by_sector=None):
    """CCI-based sector composite, 0-100 per sector (50% performance + 50% CCI).

    The performance component (15% 1W / 50% 1M / 35% 3M) is min-max normalized
    across sectors to 0-100 before combining. The CCI input is the SECTOR CCI —
    the CCI(34) rating of that sector's proxy ETF (SECTOR_ETF_MAP), passed via
    cci_by_sector; sectors without an ETF CCI value fall back to the
    market-wide cci_factor (average CCI rating across SPY/QQQ/DJI/IWM).

    stats_list: [{"sector_id", "perf_1w", "perf_1m", "perf_3m", ...}, ...]
    Returns {sector_id: score}.
    """
    return cci_sector_scores(stats_list, cci_factor, cci_by_sector)


def classify_sector_state_strategy(score, breadth, avg_rs, prev_score=None,
                                   strategy=STRATEGY_DEFAULT):
    """Rotation-state classification (Qullamaggie-flavored thresholds: rewards
    early emerging moves more readily)."""
    score = score or 0
    breadth = breadth or 0
    avg_rs = avg_rs or 0
    velocity = (score - prev_score) if prev_score is not None else 0
    if score >= 60 and breadth >= 50 and avg_rs >= 55:
        return "leader"
    if score <= 30:
        return "lagging"
    if velocity >= 1.5 and score >= 40:
        return "emerging"
    if velocity <= -2:
        return "fading"
    return "neutral"


# ---------------------------------------------------------------------------
# EP (Episodic Pivot) scanner + Watchlist ranking
# ---------------------------------------------------------------------------

# EP qualification: the scanner is deliberately inclusive — quality is
# expressed through ranking and classification, not hard rejection. Hard
# gates: a bullish day, price >= $3, enough volatility to trade (effective
# ADR >= 2%) and a substantial move vs the stock's own volatility. Market
# cap ~$0.5B, liquidity and catalyst quality are SOFT: they move the score
# and the classification, they do not exclude a name from the list.
EP_MIN_MARKET_CAP_MUSD = 500.0      # soft baseline — below this scores/tags down
EP_MIN_ADR_PCT = 2.0                # effective ADR >= 2% (fallback: Volatility.D)
EP_MIN_PRICE = 3.0                  # share price >= $3
EP_MIN_CHG_1D = 8.0                 # reference "big day" (reasons/KPIs only)
EP_MIN_AVG_VOLUME = 500_000         # soft liquidity baseline
EP_MIN_REL_VOLUME = 2.0             # reference rel-volume for confirmed quality
# Adaptive move bar — a candidate needs ONE of: a meaningful gap up, a large
# green expansion candle / powerful intraday move, or a heavy-volume range
# day. "Substantial" scales with the stock's own ADR (floored in %) and the
# thresholds ease up to 15% on weak market days (see _ep_market_ease).
EP_GAP_ADR_MULT = 0.8               # gap >= max(EP_GAP_MIN_PCT, 0.8*ADR)
EP_GAP_MIN_PCT = 3.0
EP_CANDLE_ADR_MULT = 1.5            # day move >= max(EP_CANDLE_MIN_PCT, 1.5*ADR)
EP_CANDLE_MIN_PCT = 6.0
EP_VOL_ASSIST_MIN_RV = 2.5          # heavy-volume assist: chg >= 1x ADR on >= 2.5x rel vol
# Prior consolidation: the stock was quiet before it exploded. Primary signal
# is monthly volatility (TradingView Volatility.M, in %): below this threshold
# the month was tight. Fallback when volatility_m is missing: daily volatility
# (Volatility.D) below EP_CONSOL_VOL_D_MAX.
EP_CONSOL_VOL_M_MAX = 7.0
EP_CONSOL_VOL_D_MAX = 3.5

# Live news catalysts: fetched only for the biggest movers (bounded, cached)
EP_NEWS_MAX_SYMBOLS = 60

# Absolute 100-point score. Sector/industry strength is a first-class ranking
# factor: the sector bonus swings -10..+18 on top of 90 base points.
#   expansion 25 + volume 20 + continuation 15 + catalyst 10
#   + structure 15 + risk/liquidity 5 = 90 base  (+ sector bonus)
EP_CTYPE_SCORE = {"earnings": 10, "guidance": 9, "fda": 9, "mna": 9,
                  "contract": 8, "analyst": 6, "other": 6, "legal": 4,
                  "macro": 4, "offering": 0}
EP_SECTOR_BONUS_MAX = 18
EP_SECTOR_PENALTY_MAX = -10
EP_SECTOR_NEUTRAL = 40.0     # combined sector/industry score at which bonus = 0
EP_SCORE_CONFIRMED = 68
EP_SCORE_POSSIBLE = 45

# Watchlist ranking formula:
#   Final = performance*75% + ADR*20% + EMA proximity*5%
#   (performance = 1W*15% + 1M*42.5% + 3M*42.5%; EMA proximity = closeness to
#    the nearest of the 10/20/50 EMA)
# every input min-max normalized across the watchlist to 0-100 first.
WL_W_PERF = 0.75
WL_W_ADR = 0.20
WL_W_EMA = 0.05
WL_P_W_1W = 0.15
WL_P_W_1M = 0.425
WL_P_W_3M = 0.425


def _minmax_map(rows, getter):
    """Min-max normalize a numeric field across rows to 0-100.
    Rows with a missing value get None (caller substitutes 50)."""
    vals = [getter(r) for r in rows]
    vals = [v for v in vals if v is not None]
    if not vals:
        return {}
    mn, mx = min(vals), max(vals)
    span = (mx - mn) or 1.0
    out = {}
    for r in rows:
        v = getter(r)
        key = r.get("ticker") or r.get("stock_ticker")
        out[key] = round((v - mn) / span * 100, 1) if v is not None else None
    return out


def _ep_consolidated(r):
    """Was the stock consolidating (quiet) before the move?"""
    vm = r.get("volatility_m")
    if vm is not None:
        return vm < EP_CONSOL_VOL_M_MAX
    vd = r.get("volatility_d")
    if vd is not None:
        return vd < EP_CONSOL_VOL_D_MAX
    return False


def _ep_effective_adr(r):
    """The stock's normal daily move in %: ADR when present, else daily
    volatility, else a 4% default. Drives every adaptive threshold."""
    adr = r.get("adr_pct")
    if adr and adr > 0:
        return float(adr)
    vd = r.get("volatility_d")
    if vd and vd > 0:
        return float(vd)
    return 4.0


def _ep_move_assessment(r, market_ease=1.0):
    """Adaptive substantial-move test. A candidate needs ONE of:
      'gap'    — meaningful gap up (pre-market or opening gap vs ADR)
      'candle' — large green expansion candle / powerful intraday move
      'volume' — heavy-volume range day (>= 1x ADR on >= 2.5x rel volume)
    Thresholds scale with the stock's effective ADR (floored) and ease on
    weak market days. Returns (qualifies, kind, thresholds)."""
    adr = _ep_effective_adr(r)
    gap = max(r.get("gap_pct") or 0, r.get("pm_chg") or 0, 0)
    chg = max(r.get("chg_1d") or 0, 0)
    cfo = max(r.get("chg_from_open") or 0, 0)
    thr_gap = max(EP_GAP_MIN_PCT, EP_GAP_ADR_MULT * adr) * market_ease
    thr_candle = max(EP_CANDLE_MIN_PCT, EP_CANDLE_ADR_MULT * adr) * market_ease
    thr = {"gap": round(thr_gap, 1), "candle": round(thr_candle, 1),
           "adr": round(adr, 1)}
    if gap >= thr_gap:
        return True, "gap", thr
    if chg >= thr_candle or cfo >= thr_candle:
        return True, "candle", thr
    if (r.get("volume_ratio") or 0) >= EP_VOL_ASSIST_MIN_RV \
            and chg >= max(4.0, adr) * market_ease:
        return True, "volume", thr
    return False, None, thr


def _ep_market_ease(conn):
    """Weak market days make substantial moves rarer and more significant:
    ease the adaptive thresholds up to 15% when the major indices are red."""
    try:
        rows = conn.execute(
            "SELECT chg_1d FROM index_cci WHERE chg_1d IS NOT NULL").fetchall()
    except Exception:
        return 1.0
    vals = [r["chg_1d"] for r in rows if r["chg_1d"] is not None]
    if not vals:
        return 1.0
    avg = sum(vals) / len(vals)
    return round(max(0.85, min(1.0, 1.0 + min(avg, 0.0) * 0.10)), 3)


def _ep_pct_dist(price, level):
    """Percent distance of price above a level (None-safe)."""
    if price and level:
        return round((price / level - 1) * 100, 1)
    return None


def _ep_risk_level(r):
    """Simple invalidation price: min(day low, price - 1.0*ATR)."""
    price = r.get("price")
    if not price:
        return None
    atr = r.get("atr")
    if not atr and r.get("adr_pct"):
        atr = price * r["adr_pct"] / 100.0
    stop = price - atr if atr else price
    if r.get("day_low"):
        stop = min(stop, r["day_low"])
    return round(stop, 2)


def _ep_catalyst_points(cat):
    """0-10: verified catalyst scaled by type quality; unverified 2-4;
    offering/dilution 0; unavailable 0. Catalysts confirm the score — their
    absence never disqualifies a candidate."""
    if not cat:
        return 0
    status = cat.get("status")
    ctype = cat.get("ctype") or "other"
    if status == "verified":
        return EP_CTYPE_SCORE.get(ctype, 6)
    if status == "unverified":
        if ctype == "offering":
            return 0
        return 2 if cat.get("promo") else 4
    return 0


def _ep_expansion_points(r):
    """0-25: gap-up magnitude vs ADR (<=13) + day candle / intraday move vs
    ADR (<=12). Adaptive — what counts as big scales with the stock's own
    volatility. Gap-and-fade is heavily discounted."""
    adr = _ep_effective_adr(r)
    gap = max(r.get("gap_pct") or 0, r.get("pm_chg") or 0, 0)
    chg = max(r.get("chg_1d") or 0, 0)
    cfo = max(r.get("chg_from_open") or 0, 0)
    candle = max(chg, cfo)
    pts = min(13.0, gap / adr * 6.5) + min(12.0, candle / adr * 5.0)
    if (r.get("chg_from_open") or 0) < -4:
        pts *= 0.4
    return round(min(25.0, pts))


def _ep_volume_points(r):
    """0-20: relative volume (<=14) + dollar-volume tiers (<=6). Any
    above-average volume contributes; explosive volume scores highest."""
    vr = r.get("volume_ratio") or 0
    vr_pts = 14 if vr >= 8 else 12 if vr >= 5 else 10 if vr >= 3 \
        else 8 if vr >= 2 else 5 if vr >= 1.3 else 2 if vr >= 1.0 else 0
    dv = r.get("dollar_vol") or 0
    dv_pts = 6 if dv >= 100e6 else 5 if dv >= 50e6 else 4 if dv >= 20e6 \
        else 2 if dv >= 10e6 else 1 if dv >= 5e6 else 0
    return min(20, vr_pts + dv_pts)


def _ep_structure_points(r):
    """0-15: consolidation / basing before the move (<=6), constructive
    position vs ema20 — a base breakout, not a late-stage spike (<=4),
    proximity to the 52w high (<=2), constructive prior trend (<=3)."""
    pts = 0
    vm, vd = r.get("volatility_m"), r.get("volatility_d")
    if vm is not None:
        pts += 6 if vm < 5 else 4 if vm < EP_CONSOL_VOL_M_MAX \
            else 2 if vm < 10 else 0
    elif vd is not None:
        pts += 6 if vd < 2.5 else 4 if vd < EP_CONSOL_VOL_D_MAX \
            else 2 if vd < 5 else 0
    d20 = r.get("dist_ema20")
    if d20 is not None:
        pts += 4 if d20 <= 5 else 3 if d20 <= 12 else 1 if d20 <= 20 else 0
    p52 = r.get("pct_from_52w_high")
    if p52 is not None:
        pts += 2 if p52 >= -15 else 1 if p52 >= -30 else 0
    c1m, c3m = r.get("chg_1m"), r.get("chg_3m")
    if c1m is not None and c1m > 0:
        pts += 1
        if c1m <= 30:
            pts += 1      # building energy, not already a repeated spike
    if c3m is not None and c3m > 0:
        pts += 1
    return min(15, pts)


def _ep_continuation_points(r):
    """0-15: how well the stock held up after the open — higher price since
    the open and closes near the day high score higher."""
    rp = r.get("range_pos")
    cfo = r.get("chg_from_open")
    adr = _ep_effective_adr(r)
    pts = 7 if rp is not None and rp >= 80 else 4 if rp is not None and rp >= 60 \
        else 2 if rp is not None and rp >= 40 else 0
    if cfo is not None and cfo > 0:
        pts += 3
        # gained at least a full ADR since the open
        pts += min(5, round(cfo / adr * 5))
    return min(15, pts)


def _ep_risk_points(r):
    """0-5: price >= $3, a reasonable ATR-based stop distance, basic liquidity."""
    price = r.get("price") or 0
    stop = r.get("risk_level")
    pts = 2 if price >= EP_MIN_PRICE else 0
    adr = _ep_effective_adr(r)
    if price and stop:
        stop_pct = (price - stop) / price * 100
        pts += 2 if stop_pct <= 1.5 * adr else 1 if stop_pct <= 2.5 * adr else 0
    if (r.get("dollar_vol") or 0) >= 10e6:
        pts += 1
    return min(5, pts)


def _ep_sector_bonus(sector_score, industry_score=None):
    """-10..+18: EPs in strong sectors/industries rank much higher; weak or
    deteriorating ones are down-ranked. Blends the CCI sector score (70%)
    with the industry leadership score (30%) when both are available."""
    if sector_score is None and industry_score is None:
        return 0
    if sector_score is None:
        combined = industry_score
    elif industry_score is None:
        combined = sector_score
    else:
        combined = 0.7 * sector_score + 0.3 * industry_score
    combined = max(0.0, min(100.0, combined))
    bonus = round((combined - EP_SECTOR_NEUTRAL) * 0.30)
    return max(EP_SECTOR_PENALTY_MAX, min(EP_SECTOR_BONUS_MAX, bonus))


def _ep_penalties(r, cat, sector_bonus=0):
    """Human-readable negatives for the candidate."""
    out = []
    status = (cat or {}).get("status")
    ctype = (cat or {}).get("ctype")
    if status == "unverified":
        out.append("weak/unverified catalyst (stale or low-quality source)")
    elif status != "verified":
        out.append("no catalyst found")
    if ctype == "offering":
        out.append("dilution/offering headline")
    if (cat or {}).get("promo"):
        out.append("promotional activity in headline/source")
    if sector_bonus <= -5:
        out.append("weak/deteriorating sector (%+d)" % sector_bonus)
    if (r.get("dollar_vol") or 0) < 10e6:
        out.append("low liquidity (dollar volume < $10M)")
    if (r.get("chg_from_open") or 0) < -4:
        out.append("gap-and-fade (down >4% from open)")
    if (r.get("dist_ema20") or 0) > 20:
        out.append("extended chart (>20% above ema20)")
    if (r.get("chg_1w") or 0) > 40 and (r.get("chg_1m") or 0) > 40:
        out.append("repeated spikes (1W and 1M both > +40%)")
    elif (r.get("volatility_m") or 0) > 12:
        out.append("repeated spikes (high monthly volatility)")
    if (r.get("price") or 0) < EP_MIN_PRICE:
        out.append("low price (< $%g)" % EP_MIN_PRICE)
    if (r.get("market_cap_musd") or 0) < EP_MIN_MARKET_CAP_MUSD:
        out.append("low market cap (< $%gM)" % EP_MIN_MARKET_CAP_MUSD)
    if (r.get("volatility_d") or 0) > 15:
        out.append("high volatility")
    return out


def _ep_tags(r, cat, sector_bonus):
    """Positive labels for the candidate."""
    out = []
    kind = r.get("move_kind")
    if kind == "gap":
        out.append("gap up")
    elif kind == "candle":
        out.append("expansion candle")
    elif kind == "volume":
        out.append("heavy volume day")
    if (cat or {}).get("status") == "verified":
        out.append("verified catalyst")
    if (r.get("gap_pct") or 0) >= 4:
        out.append("strong gap")
    if (r.get("volume_ratio") or 0) >= EP_MIN_REL_VOLUME:
        out.append("high relative volume")
    if (r.get("dollar_vol") or 0) >= 50e6:
        out.append("high liquidity")
    if r.get("consolidated"):
        out.append("tight base")
    p52 = r.get("pct_from_52w_high")
    if p52 is not None and p52 >= -10:
        out.append("near 52w high")
    if sector_bonus >= 8:
        out.append("strong sector")
    if (r.get("range_pos") or 0) >= 80:
        out.append("closes near high")
    if (r.get("rs_rating") or 0) >= 80:
        out.append("high RS")
    return out


def _ep_checklist(r, cat, sector_bonus=0):
    """Pass/caution/fail checklist across the EP dimensions (adaptive bars)."""
    status = (cat or {}).get("status")
    vr = r.get("volume_ratio") or 0
    dv = r.get("dollar_vol") or 0
    gap = max(r.get("gap_pct") or 0, r.get("pm_chg") or 0)
    cfo = r.get("chg_from_open") or 0
    rp = r.get("range_pos")
    price = r.get("price") or 0
    stop = r.get("risk_level")
    adr = _ep_effective_adr(r)
    stop_pct = ((price - stop) / price * 100) if (price and stop) else None
    move_ok = gap >= max(EP_GAP_MIN_PCT, EP_GAP_ADR_MULT * adr) \
        or max(r.get("chg_1d") or 0, cfo) >= max(EP_CANDLE_MIN_PCT, EP_CANDLE_ADR_MULT * adr)
    return [
        {"label": "Catalyst",
         "state": "pass" if status == "verified" else "caution" if status == "unverified" else "fail",
         "detail": (cat or {}).get("headline") or "no news found"},
        {"label": "Relative volume",
         "state": "pass" if vr >= EP_MIN_REL_VOLUME else "caution" if vr >= 1.3 else "fail",
         "detail": "%.1fx vs 10d avg" % vr},
        {"label": "Liquidity",
         "state": "pass" if dv >= 15e6 else "caution" if dv >= 5e6 else "fail",
         "detail": "$%.1fM traded" % (dv / 1e6)},
        {"label": "Move quality",
         "state": "pass" if move_ok and cfo >= -2 else "fail" if cfo < -5 else "caution",
         "detail": "gap %+.1f%%, 1d %+.1f%%, from open %+.1f%% (ADR %.1f%%)"
                   % (gap, r.get("chg_1d") or 0, cfo, adr)},
        {"label": "Structure",
         "state": "pass" if r.get("consolidated") or (r.get("dist_ema20") or 999) <= 12
                  else "caution" if (r.get("dist_ema20") or 0) <= 20 else "fail",
         "detail": "Vol.M %s%%, %s%% above ema20" % (r.get("volatility_m"), r.get("dist_ema20"))},
        {"label": "Continuation",
         "state": "pass" if (rp or 0) >= 70 and cfo > 0 else "caution" if cfo >= 0 else "fail",
         "detail": "range pos %s%%, from open %+.1f%%" % (rp, cfo)},
        {"label": "Sector strength",
         "state": "pass" if sector_bonus >= 8 else "caution" if sector_bonus >= 0 else "fail",
         "detail": "sector/industry bonus %+d" % sector_bonus},
        {"label": "Risk",
         "state": "pass" if price >= EP_MIN_PRICE and stop_pct is not None and stop_pct <= 1.5 * adr
                  else "caution" if price >= EP_MIN_PRICE else "fail",
         "detail": "stop $%s (%.1f%% below price)" % (stop, stop_pct or 0)},
    ]


def _ep_classify(r, cat, score):
    """classification, confidence, missing[], reject_reason for a candidate.

    Buckets (preserved): Confirmed EP (textbook: verified catalyst + volume +
    high score), Possible EP (strong score, imperfect confirmations), News
    Spike (speculative: offering/promo/thin unverified news), Momentum Mover
    (substantial move with no verified news). Only an outright gap-and-fade
    disaster is rejected — the move bar already guarantees a real move."""
    status = (cat or {}).get("status")
    ctype = (cat or {}).get("ctype")
    promo = bool((cat or {}).get("promo"))
    vr = r.get("volume_ratio") or 0
    dv = r.get("dollar_vol") or 0
    mc = r.get("market_cap_musd") or 0
    cfo = r.get("chg_from_open") or 0

    missing = []
    if status != "verified":
        missing.append("verified catalyst")
    if vr < EP_MIN_REL_VOLUME:
        missing.append("relative volume >= %gx" % EP_MIN_REL_VOLUME)
    if dv < 20e6:
        missing.append("dollar volume >= $20M")
    if mc < EP_MIN_MARKET_CAP_MUSD:
        missing.append("market cap >= $%gM" % EP_MIN_MARKET_CAP_MUSD)
    if score < EP_SCORE_CONFIRMED:
        missing.append("ep_score >= %g" % EP_SCORE_CONFIRMED)

    if status == "verified" and vr >= EP_MIN_REL_VOLUME and dv >= 15e6 \
            and score >= EP_SCORE_CONFIRMED:
        cls = "confirmed"
    elif ctype == "offering" or promo:
        cls = "speculative"
    elif cfo < -6:
        # gap-and-fade: never an EP candidate no matter how good the rest looks
        cls = "momentum" if score >= EP_SCORE_POSSIBLE else "rejected"
    elif score >= EP_SCORE_POSSIBLE \
            and (status in ("verified", "unverified") or score >= 55):
        cls = "possible"
    elif status == "unverified":
        cls = "speculative"
    else:
        cls = "momentum"

    n_missing = len(missing)
    if cls == "confirmed" and n_missing <= 1:
        confidence = "high"
    elif cls in ("confirmed", "possible") and n_missing <= 3:
        confidence = "medium"
    elif cls == "momentum" and score >= EP_SCORE_POSSIBLE:
        confidence = "medium"
    else:
        confidence = "low"

    reject_reason = None
    if cls == "rejected":
        reject_reason = "gap-and-fade (%.1f%% from open) with weak confirmations (score %g)" \
                        % (cfo, score)
    return cls, confidence, missing, reject_reason


def _ep_finalize(r, sector_score=None, industry_score=None):
    """Score + classify one EP candidate row in place (absolute 100-pt system
    plus the -10..+18 sector/industry bonus)."""
    r["consolidated"] = _ep_consolidated(r)
    r["risk_level"] = _ep_risk_level(r)
    r["dist_ema20"] = _ep_pct_dist(r.get("price"), r.get("ema20"))
    r["dist_ema50"] = _ep_pct_dist(r.get("price"), r.get("ema50"))
    cat = r.get("catalyst")
    parts = {
        "catalyst": _ep_catalyst_points(cat),
        "expansion": _ep_expansion_points(r),
        "volume": _ep_volume_points(r),
        "structure": _ep_structure_points(r),
        "continuation": _ep_continuation_points(r),
        "risk": _ep_risk_points(r),
    }
    bonus = _ep_sector_bonus(sector_score, industry_score)
    r["score_parts"] = parts
    r["sector_bonus"] = bonus
    r["ep_score"] = max(0, min(100, sum(parts.values()) + bonus))
    r["penalties"] = _ep_penalties(r, cat, bonus)
    r["tags"] = _ep_tags(r, cat, bonus)
    cls, conf, missing, reject = _ep_classify(r, cat, r["ep_score"])
    r["classification"] = cls
    r["confidence"] = conf
    r["missing"] = missing
    r["reject_reason"] = reject
    r["checklist"] = _ep_checklist(r, cat, bonus)
    r["trend"] = {"chg_1w": r.get("chg_1w"), "chg_1m": r.get("chg_1m"),
                  "chg_3m": r.get("chg_3m"), "chg_6m": r.get("chg_6m"),
                  "ytd": r.get("chg_ytd")}
    reasons = []
    thr = r.get("move_thresholds") or {}
    kind = r.get("move_kind")
    gap_move = max(r.get("gap_pct") or 0, r.get("pm_chg") or 0)
    if kind == "gap":
        reasons.append("gap up %+.1f%% (adaptive bar %.1f%% vs %.1f%% ADR)"
                       % (gap_move, thr.get("gap", 0), thr.get("adr", 0)))
    elif kind == "candle":
        reasons.append("expansion candle %+.1f%% (adaptive bar %.1f%% vs %.1f%% ADR)"
                       % (max(r.get("chg_1d") or 0, r.get("chg_from_open") or 0),
                          thr.get("candle", 0), thr.get("adr", 0)))
    elif kind == "volume":
        reasons.append("heavy-volume range day %+.1f%% on %.1fx rel volume"
                       % (r.get("chg_1d") or 0, r.get("volume_ratio") or 0))
    if cat and cat.get("status") == "verified":
        reasons.append("verified catalyst (%s): %s" % (cat.get("ctype"), cat.get("headline")))
    if (r.get("volume_ratio") or 0) >= EP_MIN_REL_VOLUME:
        reasons.append("rel vol %gx (>= %gx)" % (r["volume_ratio"], EP_MIN_REL_VOLUME))
    if (r.get("chg_1d") or 0) >= EP_MIN_CHG_1D:
        reasons.append("chg %+g%% (>= +%g%%)" % (r["chg_1d"], EP_MIN_CHG_1D))
    if r["consolidated"]:
        reasons.append("tight prior consolidation")
    if bonus > 0:
        reasons.append("strong sector/industry (bonus %+g)" % bonus)
    elif bonus <= -5:
        reasons.append("weak sector/industry (penalty %+g)" % bonus)
    if not reasons:
        reasons.append("unusual activity (score %g/100)" % r["ep_score"])
    r["reasons"] = reasons
    return r


def ep_score_rows(rows):
    """Attach ep_score (0-100, absolute catalyst-driven system) + consolidated
    flag. Used by the watchlist where no live catalyst is fetched (catalyst
    part scores 0)."""
    for r in rows:
        _ep_derive(r)
        _ep_finalize(r)
    return rows


def _ep_unavailable_catalyst():
    return {"headline": None, "source": None, "ctype": None,
            "age_h": None, "status": "unavailable", "promo": False}


def ep_scan(conn):
    """EP scanner: broad admission, rank-don't-reject. Universe = US-listed
    stocks & ETFs (NYSE/NASDAQ/AMEX, enforced by the live scan) priced >= $3
    with effective ADR >= 2%, up on the day, showing a substantial move —
    a meaningful gap up, a large green expansion candle / powerful intraday
    move, or a heavy-volume range day. "Substantial" is adaptive: thresholds
    scale with each stock's own ADR and ease up to 15% on weak market days.

    Everything meeting the bar is scored (expansion / volume / continuation /
    catalyst / structure + a -10..+18 sector/industry bonus) and ranked by
    ep_score desc. Market cap ~$0.5B, liquidity and catalyst quality shape
    the score and the Confirmed/Possible/Momentum/News-Spike classification
    instead of hard-excluding names, so active days yield a healthy watchlist.

    Returns {"candidates": [...], "sectors": [...], "generated_at": ...}."""
    rows = conn.execute(
        """SELECT s.*, sec.name AS sector_name
           FROM stock s LEFT JOIN sector sec ON sec.id = s.sector_id
           WHERE s.price IS NOT NULL AND s.chg_1d > 0""",
    ).fetchall()

    ease = _ep_market_ease(conn)
    cands = []
    for row in rows:
        d = dict(row)
        if (d.get("price") or 0) < EP_MIN_PRICE:
            continue
        if _ep_effective_adr(d) < EP_MIN_ADR_PCT:
            continue
        ok, kind, thr = _ep_move_assessment(d, ease)
        if not ok:
            continue
        d["move_kind"] = kind
        d["move_thresholds"] = thr
        _ep_derive(d)
        cands.append(d)

    # Canonical CCI-based sector scores (50% performance 15/50/35 across
    # 1W/1M/3M + 50% sector-ETF CCI) — drives the sector bonus.
    snaps = conn.execute(
        """SELECT t.* FROM sector_snapshot t
           WHERE t.dt = (SELECT MAX(dt) FROM sector_snapshot WHERE sector_id = t.sector_id)"""
    ).fetchall()
    stats = [{
        "sector_id": s["sector_id"],
        "perf_1w": s["chg_1w"], "perf_1m": s["chg_1m"], "perf_3m": s["chg_3m"],
    } for s in snaps]
    scores = cci_sector_scores(stats, cci_market_factor(conn), sector_cci_factors(conn))
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM sector")}
    colors = {r["id"]: r["color"] for r in conn.execute("SELECT id, color FROM sector")}
    avg_chg = {s["sector_id"]: s["chg_1d"] for s in snaps}

    # Industry leadership scores (0-100) from the latest industry snapshot —
    # blended 30/70 with the sector score inside the sector bonus.
    try:
        ind_scores = {r["industry"]: r["leadership_score"] for r in conn.execute(
            """SELECT industry, leadership_score FROM industry_snapshot
               WHERE dt = (SELECT MAX(dt) FROM industry_snapshot)
               AND leadership_score IS NOT NULL""")}
    except Exception:
        ind_scores = {}

    # Live news catalysts for the biggest movers only (bounded thread pool,
    # ~10-min in-memory cache inside live_data).
    top = sorted(cands, key=lambda r: -(max(r.get("gap_pct") or 0, r.get("pm_chg") or 0)
                                        + abs(r.get("chg_1d") or 0)))[:EP_NEWS_MAX_SYMBOLS]
    news = {}
    if top:
        try:
            from live_data import fetch_tv_news_batch
            news = fetch_tv_news_batch([r["ticker"] for r in top])
        except Exception:
            news = {}

    for r in cands:
        cat = news.get(r["ticker"]) or _ep_unavailable_catalyst()
        r["catalyst"] = cat
        _ep_finalize(r, scores.get(r.get("sector_id")),
                     ind_scores.get(r.get("industry")))

    cands.sort(key=lambda r: (-r["ep_score"], r.get("ticker") or ""))
    for i, r in enumerate(cands):
        r["ep_rank"] = i + 1

    by_sector = {}
    for r in cands:
        by_sector.setdefault(r.get("sector_id"), []).append(
            {"ticker": r["ticker"], "ep_score": r["ep_score"],
             "ep_rank": r["ep_rank"], "consolidated": r["consolidated"],
             "classification": r["classification"],
             "chg_1d": r["chg_1d"], "volume_ratio": r["volume_ratio"]})
    leading = []
    for sid, sc in sorted(scores.items(), key=lambda kv: -kv[1])[:10]:
        leading.append({
            "sector_id": sid,
            "name": names.get(sid, "Sector %s" % sid),
            "color": colors.get(sid),
            "score": sc,
            "avg_chg": avg_chg.get(sid),
            "ep_candidates": by_sector.get(sid, []),
        })
    return {
        "candidates": cands,
        "sectors": leading,
        "criteria": {
            "universe": "US-listed stocks & ETFs (NYSE/NASDAQ/AMEX)",
            "min_price": EP_MIN_PRICE,
            "min_adr_pct": EP_MIN_ADR_PCT,
            "min_market_cap_musd_soft": EP_MIN_MARKET_CAP_MUSD,
            "min_avg_volume_soft": EP_MIN_AVG_VOLUME,
            "min_rel_volume_quality": EP_MIN_REL_VOLUME,
            "adaptive_move_bar": {
                "gap": "gap >= max(%g%%, %gx ADR)" % (EP_GAP_MIN_PCT, EP_GAP_ADR_MULT),
                "candle": "day move >= max(%g%%, %gx ADR)" % (EP_CANDLE_MIN_PCT, EP_CANDLE_ADR_MULT),
                "vol_assist": "chg >= 1x ADR on >= %gx rel volume" % EP_VOL_ASSIST_MIN_RV,
                "market_ease": ease,
            },
            "consolidation_vol_m_max": EP_CONSOL_VOL_M_MAX,
            "score_parts": {"expansion": 25, "volume": 20, "continuation": 15,
                            "catalyst": 10, "structure": 15, "risk": 5,
                            "sector_bonus": "%d..+%d" % (EP_SECTOR_PENALTY_MAX, EP_SECTOR_BONUS_MAX)},
            "score_confirmed": EP_SCORE_CONFIRMED,
            "score_possible": EP_SCORE_POSSIBLE,
        },
        "generated_at": datetime.now().isoformat(),
    }


def _ep_derive(r):
    """Attach derived EP metrics (dollar volume, $ gain, range position, prev
    close, ORB / momentum / pre-market breakout scores) to a stock row."""
    price = r.get("price")
    chg = r.get("chg_1d")
    vol_t = r.get("volume_today")
    if price and vol_t:
        r["dollar_vol"] = round(price * vol_t, 0)
    if price and chg is not None:
        r["dollar_gain"] = round(price * chg / (100.0 + chg), 2) if (100.0 + chg) else None
        r["prev_close"] = round(price - (r["dollar_gain"] or 0), 2)
    hi, lo = r.get("day_high"), r.get("day_low")
    if price is not None and hi and lo and hi > lo:
        r["range_pos"] = round((price - lo) / (hi - lo) * 100, 1)
    # Intraday momentum: change from open weighted by close position in range
    cfo = r.get("chg_from_open")
    if cfo is not None:
        rp = (r.get("range_pos") if r.get("range_pos") is not None else 50.0) / 100.0
        r["momentum_score"] = round(cfo * (0.5 + rp), 2)
    # Opening-range breakout proxy: strong from open, closing near the day
    # high, on heavy relative volume
    if cfo is not None and r.get("range_pos") is not None and r.get("volume_ratio") is not None:
        r["orb_score"] = round(cfo * 0.6 + (r["range_pos"] - 50) * 0.2
                               + min(r["volume_ratio"], 10) * 1.5, 2)
    # Pre-market breakout proxy: pre-market gain carried into a positive gap
    pm = r.get("pm_chg")
    if pm is not None:
        r["pm_break_score"] = round(pm + max(r.get("gap_pct") or 0, 0) * 0.5, 2)
    return r


def ep_dashboard(conn):
    """Everything the EP section needs in one call: EP candidates, 16 sortable
    rankings over the whole universe, and aggregated analytics for charts."""
    base = ep_scan(conn)
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM sector")}
    colors = {r["id"]: r["color"] for r in conn.execute("SELECT id, color FROM sector")}

    rows = [dict(r) for r in conn.execute(
        """SELECT s.*, sec.name AS sector_name
           FROM stock s LEFT JOIN sector sec ON sec.id = s.sector_id
           WHERE s.sector_id IS NOT NULL AND s.price IS NOT NULL"""
    ).fetchall()]
    for r in rows:
        _ep_derive(r)
    for r in base["candidates"]:
        _ep_derive(r)

    # Ranking universe: stocks showing any unusual activity today
    movers = [r for r in rows
              if (r.get("chg_1d") or 0) > 2 or (r.get("volume_ratio") or 0) >= 1.5
              or (r.get("gap_pct") or 0) > 2]

    def slim(r, *keys):
        out = {"ticker": r["ticker"], "price": r.get("price"),
               "sector_name": r.get("sector_name"), "industry": r.get("industry"),
               "chg_1d": r.get("chg_1d"), "volume_ratio": r.get("volume_ratio")}
        for k in keys:
            out[k] = r.get(k)
        return out

    def top(key, n=10, filt=None, keys=()):
        pool = [r for r in rows if r.get(key) is not None]
        if filt:
            pool = [r for r in pool if filt(r)]
        pool.sort(key=lambda r: (-r[key], r["ticker"]))
        return [slim(r, key, *keys) for r in pool[:n]]

    def group_strength(field, id_field=None):
        agg = {}
        for r in movers:
            k = r.get(field)
            if not k:
                continue
            a = agg.setdefault(k, {"n": 0, "chg": 0.0, "rv": 0.0, "dv": 0.0})
            a["n"] += 1
            a["chg"] += r.get("chg_1d") or 0
            a["rv"] += r.get("volume_ratio") or 0
            a["dv"] += r.get("dollar_vol") or 0
        out = []
        for k, a in agg.items():
            out.append({
                "name": k, "count": a["n"],
                "avg_chg": round(a["chg"] / a["n"], 2),
                "avg_relvol": round(a["rv"] / a["n"], 2),
                "dollar_vol": round(a["dv"], 0),
                "strength": round(a["chg"] / a["n"] * 0.6 + min(a["rv"] / a["n"], 10) * 4
                                  + min(a["n"], 20) * 0.5, 2),
            })
        out.sort(key=lambda x: -x["strength"])
        return out[:12]

    rankings = {
        "pct_gain":       {"label": "Biggest % Gain",          "unit": "%",  "key": "chg_1d",
                           "rows": top("chg_1d")},
        "dollar_gain":    {"label": "Biggest $ Gain",          "unit": "$",  "key": "dollar_gain",
                           "rows": top("dollar_gain")},
        "gain_from_open": {"label": "Biggest Gain From Open",  "unit": "%",  "key": "chg_from_open",
                           "rows": top("chg_from_open")},
        "pm_gain":        {"label": "Biggest Pre-Market Gain", "unit": "%",  "key": "pm_chg",
                           "rows": top("pm_chg", filt=lambda r: (r.get("pm_chg") or 0) > 0)},
        "gap_up":         {"label": "Biggest Gap-Up",          "unit": "%",  "key": "gap_pct",
                           "rows": top("gap_pct", filt=lambda r: (r.get("gap_pct") or 0) > 0)},
        "rel_volume":     {"label": "Highest Relative Volume", "unit": "x",  "key": "volume_ratio",
                           "rows": top("volume_ratio")},
        "total_volume":   {"label": "Highest Total Volume",    "unit": "sh", "key": "volume_today",
                           "rows": top("volume_today")},
        "pm_volume":      {"label": "Highest Pre-Market Volume", "unit": "sh", "key": "pm_vol",
                           "rows": top("pm_vol", filt=lambda r: (r.get("pm_vol") or 0) > 0)},
        "dollar_volume":  {"label": "Highest Dollar Volume",   "unit": "$",  "key": "dollar_vol",
                           "rows": top("dollar_vol")},
        "rel_strength":   {"label": "Strongest Relative Strength", "unit": "", "key": "rs_rating",
                           "rows": top("rs_rating")},
        "intraday_momentum": {"label": "Strongest Intraday Momentum", "unit": "", "key": "momentum_score",
                           "rows": top("momentum_score", filt=lambda r: (r.get("momentum_score") or 0) > 0)},
        "orb":            {"label": "Strongest Opening-Range Breakout", "unit": "", "key": "orb_score",
                           "rows": top("orb_score", filt=lambda r: (r.get("orb_score") or 0) > 0)},
        "pm_breakout":    {"label": "Strongest Pre-Market Breakout", "unit": "", "key": "pm_break_score",
                           "rows": top("pm_break_score", filt=lambda r: (r.get("pm_break_score") or 0) > 0)},
    }
    rankings["sector_strength"] = {"label": "Strongest Sector", "unit": "", "key": "strength",
                                   "rows": group_strength("sector_name")}
    rankings["industry_strength"] = {"label": "Strongest Industry Group", "unit": "", "key": "strength",
                                     "rows": group_strength("industry")}

    # --- analytics aggregates for the charts tab ---
    def hist(vals, edges):
        out = []
        for i in range(len(edges) - 1):
            lo, hi = edges[i], edges[i + 1]
            out.append({"bucket": ("%g–%g" % (lo, hi)) if hi != float("inf") else ("&gt;%g" % lo),
                        "count": sum(1 for v in vals if v is not None and lo <= v < hi)})
        return out

    analytics = {
        "chg_hist": hist([r.get("chg_1d") for r in movers],
                         [0, 3, 6, 10, 15, 25, float("inf")]),
        "gap_hist": hist([r.get("gap_pct") for r in movers],
                         [float("-inf"), 0, 2, 5, 10, 20, float("inf")]),
        "relvol_hist": hist([r.get("volume_ratio") for r in movers],
                            [0, 1, 2, 3, 5, 10, float("inf")]),
        "scatter": [{"ticker": r["ticker"], "gap_pct": r.get("gap_pct"),
                     "volume_ratio": r.get("volume_ratio"), "chg_1d": r.get("chg_1d"),
                     "sector_name": r.get("sector_name")}
                    for r in movers[:250]],
        "sector_strength": rankings["sector_strength"]["rows"],
        "industry_strength": rankings["industry_strength"]["rows"],
        "cands_by_sector": [
            {"sector_id": sid, "name": names.get(sid, "?"), "color": colors.get(sid),
             "count": len([c for c in base["candidates"] if c.get("sector_id") == sid])}
            for sid in sorted({c.get("sector_id") for c in base["candidates"] if c.get("sector_id")})
        ],
    }

    cands = base["candidates"]

    def n_where(pred):
        return sum(1 for c in cands if pred(c))

    confirmed = n_where(lambda c: c["classification"] == "confirmed")
    possible = n_where(lambda c: c["classification"] == "possible")
    verified = n_where(lambda c: (c.get("catalyst") or {}).get("status") == "verified")
    def _basic(c):
        # Core quality bar (soft criteria shown in the funnel — not gates):
        # ~$0.5B cap, ADR >= 2%, price >= $3, $10M+ traded, rel vol >= 1.5x.
        return ((c.get("market_cap_musd") or 0) >= EP_MIN_MARKET_CAP_MUSD
                and (c.get("adr_pct") or 0) >= EP_MIN_ADR_PCT
                and (c.get("price") or 0) >= EP_MIN_PRICE
                and (c.get("dollar_vol") or 0) >= 10e6
                and (c.get("volume_ratio") or 0) >= 1.5)

    passed_basic = n_where(_basic)
    verified_basic = n_where(
        lambda c: _basic(c) and (c.get("catalyst") or {}).get("status") == "verified")

    base["rankings"] = rankings
    base["analytics"] = analytics
    base["meta"] = {
        "candidates": len(cands),
        "movers": len(movers),
        "universe": len(rows),
        "time": base["generated_at"],
        "confirmed": confirmed,
        "possible": possible,
    }
    base["kpis"] = {
        "confirmed": confirmed,
        "high_quality_catalyst": verified,
        "strong_volume": n_where(lambda c: (c.get("volume_ratio") or 0) >= EP_MIN_REL_VOLUME),
        "expansion": n_where(lambda c: c.get("move_kind") in ("gap", "candle")),
        "watchlist": confirmed + possible,
        "rejected": n_where(lambda c: c["classification"] == "rejected"),
    }
    base["funnel"] = [
        {"key": "universe", "label": "Universe", "count": len(rows)},
        {"key": "movers", "label": "Movers scanned", "count": len(cands)},
        {"key": "basic", "label": "Core quality bar", "count": passed_basic},
        {"key": "catalyst", "label": "Verified catalyst", "count": verified_basic},
        {"key": "confirmed", "label": "Confirmed EP", "count": confirmed},
    ]
    return base



def watchlist_entries(conn):
    """Watchlist rows joined with the latest stock data, with three rankings:

      watchlist_score — the user formula: performance 75% + ADR 20% + EMA
                        proximity 5% (performance = 1W 15% / 1M 42.5% /
                        3M 42.5%; EMA proximity = closeness to the nearest of
                        the 10/20/50 EMA), every input min-max normalized
                        across the watchlist.
      breakout_score  — the existing Qullamaggie setup composite (score_and_rank).
      ep_score        — the EP blend (chg/volume/ADR/tightness), computed for
                        every watchlisted stock regardless of EP thresholds.

    Each entry gets wl_rank, breakout_rank and ep_rank (1 = best)."""
    rows = conn.execute(
        """SELECT w.ticker, w.category, w.added_at, s.*, sec.name AS sector_name
           FROM watchlist w
           LEFT JOIN stock s ON s.ticker = w.ticker
           LEFT JOIN sector sec ON sec.id = s.sector_id
           ORDER BY w.added_at DESC"""
    ).fetchall()
    entries = [dict(r) for r in rows]
    if not entries:
        return []

    cci_by_sector = sector_cci_factors(conn)
    market_cci = cci_market_factor(conn)
    for r in entries:
        r["cci_factor"] = cci_by_sector.get(r.get("sector_id"), market_cci)

    def _ema_dist(r):
        price = r.get("price")
        if not price:
            return None
        dists = [abs(price / e - 1) * 100 for e in
                 (r.get("ema10"), r.get("ema20"), r.get("ema50")) if e]
        return min(dists) if dists else None

    for r in entries:
        r["ema_dist"] = _ema_dist(r)

    adr = _minmax_map(entries, lambda r: r.get("adr_pct"))
    p1w = _minmax_map(entries, lambda r: r.get("chg_1w"))
    p1m = _minmax_map(entries, lambda r: r.get("chg_1m"))
    p3m = _minmax_map(entries, lambda r: r.get("chg_3m"))
    # closer to an EMA = better, so normalize the negative distance
    prox = _minmax_map(entries, lambda r: -r["ema_dist"]
                       if r.get("ema_dist") is not None else None)
    for r in entries:
        t = r["ticker"]
        a = adr.get(t) if adr.get(t) is not None else 50.0
        w1 = p1w.get(t) if p1w.get(t) is not None else 50.0
        m1 = p1m.get(t) if p1m.get(t) is not None else 50.0
        m3 = p3m.get(t) if p3m.get(t) is not None else 50.0
        ep = prox.get(t) if prox.get(t) is not None else 50.0
        perf = WL_P_W_1W * w1 + WL_P_W_1M * m1 + WL_P_W_3M * m3
        r["norm"] = {"adr": a, "ema_prox": ep, "p1w": w1, "p1m": m1,
                     "p3m": m3, "perf": round(perf, 1)}
        r["watchlist_score"] = round(WL_W_PERF * perf + WL_W_ADR * a
                                     + WL_W_EMA * ep, 1)

    # Breakout composite over the watchlisted stocks (reuses the shared engine)
    scored, _ = score_and_rank([r for r in entries if r.get("price") is not None],
                               cci_factor=market_cci)
    bo = {r["ticker"]: r for r in scored}
    for r in entries:
        b = bo.get(r["ticker"])
        r["breakout_score"] = b["score"] if b else None

    ep_score_rows([r for r in entries if r.get("price") is not None])

    def rank_by(score_key, rank_key):
        ordered = sorted((r for r in entries if r.get(score_key) is not None),
                         key=lambda r: (-r[score_key], r["ticker"]))
        for i, r in enumerate(ordered):
            r[rank_key] = i + 1

    rank_by("watchlist_score", "wl_rank")
    rank_by("breakout_score", "breakout_rank")
    rank_by("ep_score", "ep_rank")
    entries.sort(key=lambda r: (r.get("wl_rank") or 9999, r["ticker"]))
    return entries
