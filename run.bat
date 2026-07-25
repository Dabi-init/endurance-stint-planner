@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
if errorlevel 1 (
    echo.
    echo Launch failed. Copy the message above into a GitHub issue.
    pause
    exit /b 1
)
