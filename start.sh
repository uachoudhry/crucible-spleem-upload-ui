#!/bin/bash
export PREFECT_API_URL="http://127.0.0.1:4200/api"

# Start Prefect server in the background
uv run prefect server start &
PREFECT_PID=$!

# Wait for the server to be ready
sleep 3

# Start flow server in the background
uv run serve_flows.py &
FLOWS_PID=$!

# Start the Flask app
uv run main.py

# Clean up on exit
kill -9 $FLOWS_PID $PREFECT_PID 2>/dev/null
