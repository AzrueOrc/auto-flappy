@echo off
cd /d "%~dp0"
set "GUI_PYTHON=pixel8a\.venv\Scripts\python.exe"
if not exist "%GUI_PYTHON%" set "GUI_PYTHON=..\flappy-autopilot\.venv\Scripts\python.exe"
if not exist "%GUI_PYTHON%" (
    echo Python GUI dependencies are not installed. See pixel8a\README.md.
    pause
    exit /b 1
)
"%GUI_PYTHON%" pixel8a\main.py
if errorlevel 1 pause
