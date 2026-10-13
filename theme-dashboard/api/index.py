"""Vercel serverless entry point for the Sector Rotation Scanner.

Vercel's Python runtime looks for a module-level `app` (ASGI) in files under
/api. This wrapper points the SQLite DB at /tmp (the only writable path on
Vercel) and exposes the FastAPI app from backend/main.py unchanged.
"""
import os
import sys

# Only /tmp is writable in the Vercel runtime; put the SQLite DB there.
os.environ.setdefault("THEMES_DB_PATH", "/tmp/themes.db")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from main import app  # noqa: E402,F401
