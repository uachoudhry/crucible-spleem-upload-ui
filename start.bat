call "c:\programdata\anaconda3\condabin\conda.bat" activate
cd /d "%~dp0"

:: Clear any orphaned uploader processes from a previous run before starting.
:: (Ctrl+C on Windows tends to leave the Prefect server / serve_flows worker
:: behind, which then holds port 4200 and causes "database is locked".)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kill_uploader.ps1"

set PREFECT_API_URL=http://127.0.0.1:4200/api

:: Start Prefect server in the background
start /b uv run prefect server start
timeout /t 3 /nobreak >nul

:: Start flow server in the background
start /b uv run python serve_flows.py

:: Start the Flask app (foreground, Ctrl+C won't prompt Y/N)
cmd /c uv run python main.py

:: Clean up on exit (always runs after main.py stops). Same script as the
:: pre-flight above: it also gets the serve_flows.py worker, which a bare
:: "taskkill /im prefect.exe" leaves running.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kill_uploader.ps1"
