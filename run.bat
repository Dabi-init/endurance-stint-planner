@echo off
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo Python is not installed or not on PATH.
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo On Windows, check "Add python.exe to PATH" during setup.
    pause
    exit /b 1
)

python -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)

python -m streamlit run app.py
if errorlevel 1 pause