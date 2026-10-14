"""Vercel serverless entry point for the Sector Rotation Scanner.

Vercel's Python runtime looks for a module-level `app` (ASGI) in files under
/api. This wrapper points the SQLite DB at /tmp (the only writable path on
Vercel) and exposes the FastAPI app from backend/main.py unchanged.

The repository ships a pre-built backend/themes.db (real universe + ~7 weeks
of industry_snapshot history). On a cold start it is copied to /tmp so the
app serves real data immediately instead of a synthetic demo universe with an
empty breadth timeline; runtime syncs then update the writable /tmp copy.
"""
import os
import shutil
import sys

# Only /tmp is writable in the Vercel runtime; put the SQLite DB there.
os.environ.setdefault("THEMES_DB_PATH", "/tmp/themes.db")

_BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")

_seed_src = os.path.join(_BACKEND, "themes.db")
_seed_dst = os.environ["THEMES_DB_PATH"]
if _seed_dst != _seed_src and not os.path.exists(_seed_dst) and os.path.exists(_seed_src):
    try:
        shutil.copyfile(_seed_src, _seed_dst)
    except OSError:
        pass  # fall back to the bundled DB path behavior / demo init

sys.path.insert(0, _BACKEND)

from main import app  # noqa: E402,F401
