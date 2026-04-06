@echo off
echo ========================================
echo FINEX Financial Analysis System
echo ========================================
echo.

:: Switch to project root directory
cd /d "%~dp0.."

:: Check Python availability
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)

:: Check Python version (>= 3.10 required)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    set PYMAJOR=%%a
    set PYMINOR=%%b
)
if %PYMAJOR% lss 3 (
    echo [ERROR] Python 3.10+ required, got %PYVER%
    pause
    exit /b 1
)
if %PYMAJOR% equ 3 if %PYMINOR% lss 10 (
    echo [ERROR] Python 3.10+ required, got %PYVER%
    pause
    exit /b 1
)

:: Check .env file
if not exist "agents\.env" (
    if exist "agents\.env.example" (
        echo [INFO] .env not found, copying from .env.example...
        copy "agents\.env.example" "agents\.env" >nul
        echo [IMPORTANT] Please edit agents\.env and fill in your API key before use!
        echo.
        start notepad "agents\.env"
        echo Press any key after you finish editing .env ...
        pause >nul
    ) else (
        echo [ERROR] agents\.env not found and no .env.example available.
        echo Please create agents\.env with your API configuration.
        pause
        exit /b 1
    )
)

:: Check uv availability (required for MCP server)
where uv >nul 2>&1
if errorlevel 1 (
    echo [WARNING] uv not found. MCP server requires uv to start.
    echo Installing uv...
    pip install uv -q
    if errorlevel 1 (
        echo [ERROR] Failed to install uv. Please install manually: pip install uv
        pause
        exit /b 1
    )
)

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
