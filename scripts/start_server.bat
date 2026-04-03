@echo off
echo ========================================
echo FINEX Financial Analysis System
echo ========================================
echo.

:: Check if virtual environment exists
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

:: Activate virtual environment
call venv\Scripts\activate.bat

:: Install dependencies
echo Installing dependencies...
pip install -r requirements.txt -q

:: Start the server
echo.
echo Starting FINEX server on http://localhost:8000
echo Press Ctrl+C to stop the server
echo.
python -m uvicorn backend.server:app --host 0.0.0.0 --port 8000

:: Keep window open if server stops
echo.
echo Server stopped. Press any key to exit...
pause >nul