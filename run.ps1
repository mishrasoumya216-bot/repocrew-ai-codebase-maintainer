# RepoCrew one-shot launcher (Windows 11 PowerShell).
# Creates the venv, installs deps, builds the frontend, builds the sandbox
# image if Docker is available, then starts the app on http://localhost:8000.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "== RepoCrew setup ==" -ForegroundColor Cyan

if (-not (Test-Path .venv)) {
    python -m venv .venv
}
$py = ".\.venv\Scripts\python.exe"

& $py -m pip install -q -r backend\requirements.txt

if (-not (Test-Path frontend\node_modules)) {
    Push-Location frontend; npm install; Pop-Location
}
Push-Location frontend; npm run build; Pop-Location

$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($docker) {
    Write-Host "Building repocrew-sandbox image..." -ForegroundColor Cyan
    docker build -t repocrew-sandbox .\sandbox
} else {
    Write-Host "Docker not found: running in local fallback (NOT isolated)" -ForegroundColor Yellow
}

if (-not (Test-Path .env)) { Copy-Item .env.example .env }

Write-Host "RepoCrew listening on http://localhost:8000" -ForegroundColor Green
& $py -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
