"""
test_connectivity.py
Run this on your own machine before your first live sync, to confirm your
network can reach the TradingView scanner API -- the app's only data source.
Usage:

    cd backend && python3 ../test_connectivity.py
"""
import sys
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RotationDesk/1.0)"}
TIMEOUT = 30

TV_SCAN_URL = "https://scanner.tradingview.com/america/scan"


def run():
    print("Checking connectivity to the TradingView scanner API...\n")
    body = {
        "columns": ["close", "sector", "Perf.3M"],
        "filter": [
            {"left": "market_cap_basic", "operation": "egreater", "right": 1e9},
            {"left": "average_volume_30d_calc", "operation": "egreater", "right": 1_000_000},
        ],
        "range": [0, 25],
        "sort": {"sortBy": "Perf.3M", "sortOrder": "desc"},
    }
    try:
        r = requests.post(TV_SCAN_URL, json=body, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        rows = data.get("data") or []
        sectors = sorted({(row.get("d") or [None, None])[1] for row in rows} - {None})
        if rows:
            print(f"  [PASS] TradingView scanner: {data.get('totalCount')} stocks pass the")
            print(f"         universal filters; sample returned {len(rows)} rows")
            print(f"         with sectors like: {', '.join(sectors[:5])}")
            return 0
        print("  [FAIL] TradingView scanner returned 0 rows")
    except Exception as e:
        print(f"  [FAIL] TradingView scanner: {type(e).__name__}: {e}")
    print("\nThe scanner is unreachable -- check firewall/VPN settings.")
    return 1


if __name__ == "__main__":
    sys.exit(run())
