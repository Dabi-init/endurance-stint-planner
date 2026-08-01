[CmdletBinding()]
param(
    [switch]$DoctorOnly
)

$ErrorActionPreference = "Stop"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
$env:PIP_NO_CACHE_DIR = "1"
Set-Location -LiteralPath $PSScriptRoot

$pythonArgs = @()
$pythonCommand = $null
$pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pythonLauncher) {
    foreach ($selector in @("-3.14", "-3.13", "-3.12", "-3.11")) {
        & $pythonLauncher.Source $selector -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 15) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $pythonCommand = $pythonLauncher
            $pythonArgs = @($selector)
            break
        }
    }
}
if (-not $pythonCommand) {
    $pythonFallback = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonFallback) {
        & $pythonFallback.Source -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 15) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $pythonCommand = $pythonFallback
        }
    }
}
if (-not $pythonCommand) {
    throw "Python 3.11 through 3.14 is required: https://www.python.org/downloads/"
}
$pitwallPythonExe = $pythonCommand.Source

& $pitwallPythonExe @pythonArgs -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 15) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Pitwall requires Python 3.11 through 3.14." }

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    Write-Host "Creating a private Python environment..."
    & $pitwallPythonExe @pythonArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the private Python environment." }
}

& ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 15) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "The existing .venv uses an unsupported Python. Rename or remove only this project's .venv folder, then run run.bat again."
}

$projectHash = (Get-FileHash -LiteralPath "pyproject.toml" -Algorithm SHA256).Hash
$installMarker = ".venv\.pitwall-project-hash"
$needsInstall = -not (Test-Path -LiteralPath $installMarker)
if (-not $needsInstall) {
    $needsInstall = (Get-Content -LiteralPath $installMarker -Raw).Trim() -ne $projectHash
}
if (-not $needsInstall) {
    & ".venv\Scripts\python.exe" -c "import importlib.metadata as m, tomllib, pitwall, rich, typer; expected=tomllib.load(open('pyproject.toml','rb'))['project']['version']; raise SystemExit(0 if pitwall.__version__ == m.version('pitwall-agent') == expected else 1)" 2>$null
    $needsInstall = $LASTEXITCODE -ne 0
}
if (-not $needsInstall) {
    & ".venv\Scripts\python.exe" -m pip check --disable-pip-version-check 2>$null
    $needsInstall = $LASTEXITCODE -ne 0
}
if ($needsInstall) {
    Write-Host "Installing Pitwall Agent in its private environment..."
    & ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --no-cache-dir -e .
    if ($LASTEXITCODE -ne 0) { throw "Pitwall installation failed." }
    & ".venv\Scripts\python.exe" -m pip check --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw "Pitwall's installed dependencies are inconsistent." }
    & ".venv\Scripts\python.exe" -c "import importlib.metadata as m, tomllib, pitwall; expected=tomllib.load(open('pyproject.toml','rb'))['project']['version']; raise SystemExit(0 if pitwall.__version__ == m.version('pitwall-agent') == expected else 1)"
    if ($LASTEXITCODE -ne 0) { throw "Pitwall's installed version does not match this source folder." }
    Set-Content -LiteralPath $installMarker -Value $projectHash -Encoding ascii
} else {
    Write-Host "Pitwall Agent is already installed; skipping dependency download."
}

Write-Host "Checking the installation..."
& ".venv\Scripts\python.exe" -m pitwall doctor --core-only
if ($LASTEXITCODE -ne 0) { throw "Pitwall's health check failed." }

if ($DoctorOnly) {
    return
}

if (-not (Test-Path -LiteralPath ".pitwall\race.json")) {
    Write-Host ""
    Write-Host "First run: learn the basics and optionally create your race."
    & ".venv\Scripts\python.exe" -m pitwall welcome
    if ($LASTEXITCODE -ne 0) { throw "Pitwall welcome/setup failed." }
}

Write-Host ""
Write-Host "Opening Pitwall Agent. Type /help for commands or /exit when finished."
& ".venv\Scripts\python.exe" -m pitwall
if ($LASTEXITCODE -ne 0) {
    throw "Pitwall ended unexpectedly with exit code $LASTEXITCODE."
}
