@echo off
title AI Employee - Service Status
cd /d "%~dp0"
echo.
python service_manager.py status
echo.
pause
