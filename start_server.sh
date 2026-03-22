#!/bin/bash
echo "========================================"
echo "FINEX Financial Analysis System"
echo "========================================"
echo

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r backend/requirements.txt -q

# Start the server
echo
echo "Starting FINEX server on http://localhost:8000"
echo "Press Ctrl+C to stop the server"
echo
python -m uvicorn backend.server:app --host 0.0.0.0 --port 8000 --reload