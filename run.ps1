$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.11 or newer is required: https://www.python.org/downloads/"
}

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    Write-Host "Creating a private Python environment..."
    python -m venv .venv
}

Write-Host "Installing Pitwall Agent..."
& ".venv\Scripts\python.exe" -m pip install -e . -q

Write-Host "Checking the installation..."
& ".venv\Scripts\python.exe" -m pitwall doctor

Write-Host ""
Write-Host "Opening Pitwall Agent. Type exit when finished."
& ".venv\Scripts\python.exe" -m pitwall
