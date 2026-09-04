param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly
)

$ErrorActionPreference = "Stop"

if ($BackendOnly -and $FrontendOnly) { throw "Choose only one partial setup mode." }

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

# npm lifecycle variables point nested installs back at the root package unless cleared.
Get-ChildItem Env: | Where-Object Name -Like "npm_*" | ForEach-Object {
    Remove-Item -LiteralPath "Env:$($_.Name)"
}
$env:npm_config_cache = Join-Path (Split-Path -Parent $repoRoot) ".npm-cache"

if (-not $BackendOnly -and -not $FrontendOnly) {
    & npm.cmd install --prefer-offline --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "Root npm install failed." }
}

if (-not $FrontendOnly) {
    if (-not (Test-Path -LiteralPath backend\.venv\Scripts\python.exe)) {
        & python.exe -m venv backend\.venv
        if ($LASTEXITCODE -ne 0) { throw "Python virtual environment creation failed." }
    }

    & backend\.venv\Scripts\python.exe -m pip install --no-cache-dir -r backend\requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Backend dependency installation failed." }
}

if (-not $BackendOnly) {
    Push-Location -LiteralPath frontend
    try {
        & npm.cmd install --prefer-offline --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "Frontend npm install failed." }
    }
    finally {
        Pop-Location
    }
}
