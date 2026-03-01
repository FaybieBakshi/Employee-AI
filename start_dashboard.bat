@echo off
title AI Employee - Web Dashboard
color 0B
echo.
echo ============================================
echo   AI Employee - Web Dashboard
echo   http://localhost:8080
echo ============================================
echo.

cd /d "%~dp0"

echo Starting dashboard...
echo Open your browser at: http://localhost:8080
echo.
echo Dashboard auto-refreshes every 30 seconds.
echo Press Ctrl+C to stop.
echo ============================================
echo.

python web_dashboard.py --port 8080

pause
