@echo off
title AI Employee - Server Stop
color 0C
echo.
echo ============================================
echo   AI Employee - Stopping All Services
echo ============================================
echo.

cd /d "%~dp0"

python service_manager.py stop

echo.
echo All services stopped.
echo.
pause
