@echo off
set PREFECT_API_URL=http://127.0.0.1:4200/api

:: Start Prefect server in the background
start /b uv run prefect server start
timeout /t 3 /nobreak >nul

:: Start flow server in the background
start /b uv run python serve_flows.py

:: Start the Flask app (foreground, Ctrl+C won't prompt Y/N)
cmd /c uv run python main.py

:: Clean up on exit (always runs after main.py stops)
taskkill /f /im prefect.exe 2>nul
taskkill /f /im python.exe /fi "WINDOWTITLE eq serve_flows*" 2>nul
