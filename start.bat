@echo off
title AI Employee - Gold Tier
color 0A
echo.
echo ============================================
echo   Personal AI Employee - Gold Tier
echo   Hackathon 0 - 2026
echo ============================================
echo.

cd /d "%~dp0"

echo [1/3] Checking Python...
python --version
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.13+
    pause
    exit /b 1
)

echo [2/3] Checking dependencies...
python -c "import watchdog, dotenv, schedule, yaml" 2>nul
if errorlevel 1 (
    echo Installing dependencies...
    pip install watchdog python-dotenv schedule pyyaml
)

echo [3/3] Starting AI Employee...
echo.
echo Vault:    AI_Employee_Vault\
echo Watchers: fs + approval
echo Mode:     DRY_RUN (safe - no real actions)
echo.
echo Drop files into AI_Employee_Vault\Inbox\ to create tasks.
echo Run Claude Code and use /vault-manager to process them.
echo.
echo Press Ctrl+C to stop.
echo ============================================
echo.

python orchestrator.py --watchers fs,approval

pause
