#!/bin/bash
echo "========================================"
echo "FINEX Financial Analysis System"
echo "========================================"
echo

# Switch to project root directory
cd "$(dirname "$0")/.."

# Check Python availability
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 not found. Please install Python 3.10+."
    exit 1
fi

# Check Python version (>= 3.10 required)
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYMAJOR=$(echo "$PYVER" | cut -d. -f1)
PYMINOR=$(echo "$PYVER" | cut -d. -f2)
if [ "$PYMAJOR" -lt 3 ] || { [ "$PYMAJOR" -eq 3 ] && [ "$PYMINOR" -lt 10 ]; }; then
    echo "[ERROR] Python 3.10+ required, got $PYVER"
    exit 1
fi

# Check .env file
if [ ! -f "agents/.env" ]; then
    if [ -f "agents/.env.example" ]; then
        echo "[INFO] .env not found, copying from .env.example..."
        cp "agents/.env.example" "agents/.env"
        echo "[IMPORTANT] Please edit agents/.env and fill in your API key before use!"
        echo "Press Enter after you finish editing .env..."
        ${EDITOR:-nano} "agents/.env"
    else
        echo "[ERROR] agents/.env not found and no .env.example available."
        exit 1
    fi
fi

# Check uv availability (required for MCP server)
if ! command -v uv &> /dev/null; then
    echo "[WARNING] uv not found. MCP server requires uv to start."
    echo "Installing uv..."
    pip install uv -q
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to install uv. Please install manually: pip install uv"
        exit 1
    fi
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt -q

# Start the server
echo
echo "Starting FINEX server on http://localhost:8100"
echo "Press Ctrl+C to stop the server"
echo
python -m uvicorn backend.server:app --host 0.0.0.0 --port 8100 --reload
