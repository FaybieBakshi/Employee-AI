@echo off
title AI Employee - Server Start
color 0A
echo.
echo ============================================
echo   AI Employee - Starting All Services
echo ============================================
echo.

cd /d "%~dp0"

echo Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.13+
    pause
    exit /b 1
)

echo Starting services in background...
echo.
python service_manager.py start

echo.
echo ============================================
echo   All services started.
echo   Dashboard: http://localhost:8080
echo ============================================
echo.
echo Logs are in the logs\ folder.
echo To stop:   stop_server.bat
echo To status: python service_manager.py status
echo.
pause
