@echo off
title AI Employee - Gold Tier (Full)
color 0B
echo.
echo ============================================
echo   Personal AI Employee - Gold Tier (Full)
echo   Gmail + WhatsApp + Approval Watchers
echo ============================================
echo.

cd /d "%~dp0"

if not exist ".env" (
    echo ERROR: .env file not found!
    echo Run: copy .env.example .env
    echo Then fill in your API credentials.
    pause
    exit /b 1
)

echo Checking Gmail credentials...
if not exist "credentials\gmail_credentials.json" (
    echo WARNING: Gmail credentials not found.
    echo Run: python -m watchers.gmail_watcher --auth
    echo.
)

echo Starting full Gold Tier orchestrator...
echo Watchers: fs + gmail + approval + whatsapp
echo.

python orchestrator.py --watchers fs,gmail,approval,whatsapp

pause
