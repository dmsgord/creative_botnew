@echo off
title SETUP

cd /d "%~dp0"

echo [1/3] Checking environment...
if not exist "venv" (
    echo Creating venv...
    python -m venv venv
) else (
    echo venv exists.
)

echo [2/3] Installing libraries...
".\venv\Scripts\pip.exe" install -r requirements.txt --upgrade

echo.
echo [3/3] DONE!
echo You can now run START_MATE.bat and START_CHIEF.bat
pause