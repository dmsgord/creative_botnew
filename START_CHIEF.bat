@echo off
title CHIEF BOT (Manager)

:: Go to current folder
cd /d "%~dp0"

:: Check venv
if not exist "venv" (
    echo [ERROR] Virtual environment 'venv' not found!
    echo Please run SETUP.bat first.
    pause
    exit
)

echo [OK] Found venv.
echo [OK] Starting CHIEF BOT...
echo -------------------------------------

:: Run Python
".\venv\Scripts\python.exe" run_chief.py

pause