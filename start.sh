#!/bin/bash
export PREFECT_API_URL="http://127.0.0.1:4200/api"

# Kill the whole process group on Ctrl+C / exit so Prefect server,
# serve_flows.py, and their Python grandchildren shut down together
# instead of being orphaned and continuing to log for minutes.
trap 'trap - INT TERM EXIT; kill -TERM 0 2>/dev/null; wait 2>/dev/null; exit' INT TERM EXIT

# Start Prefect server in the background
uv run prefect server start &
PREFECT_PID=$!

# Wait for the server to be ready
sleep 3

# Start flow server in the background
uv run serve_flows.py &
FLOWS_PID=$!

# Start the Flask app (foreground)
uv run main.py
