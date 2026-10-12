@echo off
cd /d "%~dp0backend"

echo ==================================================
echo  Sector Rotation Scanner
echo  No API key needed -- this app only uses the free,
echo  keyless TradingView scanner API. There is nowhere
echo  to enter a key.
echo ==================================================
echo.

if not exist ".venv" (
  echo [1/3] First run: creating a Python virtual environment...
  python -m venv .venv
) else (
  echo [1/3] Virtual environment already exists, reusing it.
)
call .venv\Scripts\activate.bat

echo [2/3] Installing/checking dependencies (fastapi, uvicorn, requests).
echo       On the very first run this can
echo       take 1-3 minutes depending on your connection -- this is
echo       normal, NOT a hang. You will see pip's own progress below.
echo.
pip install -r requirements.txt
echo.
echo [3/3] Dependencies ready. Starting the server...
echo.
echo Once you see "Uvicorn running on http://0.0.0.0:8420" below,
echo open http://localhost:8420 in your browser.
echo Press Ctrl+C here to stop the server.
echo.
python -m uvicorn main:app --host 0.0.0.0 --port 8420

echo.
echo ==================================================
echo  The server has stopped.
echo  If it stopped immediately, scroll up to see the error
echo  (most common cause: another server is already running
echo  on port 8420 -- close the other window first).
echo ==================================================
pause
