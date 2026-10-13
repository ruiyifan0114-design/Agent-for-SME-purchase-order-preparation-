param([string]$Grep = "")

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDir = Join-Path $projectRoot (".e2e-runtime\run-" + [guid]::NewGuid().ToString("N"))
$databasePath = Join-Path $runtimeDir "procurement-e2e.db"
$backendLog = Join-Path $runtimeDir "backend.log"
$backendErrorLog = Join-Path $runtimeDir "backend-error.log"
$frontendLog = Join-Path $runtimeDir "frontend.log"
$frontendErrorLog = Join-Path $runtimeDir "frontend-error.log"

if (-not (Test-Path -LiteralPath $runtimeDir)) {
    New-Item -ItemType Directory -Path $runtimeDir | Out-Null
}
$resolvedRuntime = (Resolve-Path -LiteralPath $runtimeDir).Path
if (-not $databasePath.StartsWith($resolvedRuntime, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe E2E database path"
}
$occupied = Get-NetTCPConnection -State Listen -LocalPort 5173,8000 -ErrorAction SilentlyContinue
if ($occupied) { throw "E2E ports 5173 or 8000 are already in use" }

$env:DATABASE_URL = "sqlite:///$($databasePath.Replace('\', '/'))"
$env:ALLOW_API_KEYS = "true"
$env:BACKEND_URL = "http://127.0.0.1:8000"
$env:FRONTEND_URL = "http://127.0.0.1:5173"
$env:CORS_ORIGINS = '["http://127.0.0.1:5173"]'

Push-Location $projectRoot
$backend = $null
$frontend = $null
try {
    & ".\.venv\Scripts\python.exe" -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Alembic migration failed" }
    $backend = Start-Process -FilePath ".\.venv\Scripts\python.exe" `
        -ArgumentList "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000" `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $backendLog -RedirectStandardError $backendErrorLog
    $frontend = Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev" -WorkingDirectory (Join-Path $projectRoot "frontend") `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendErrorLog
    foreach ($attempt in 1..30) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/ready" | Out-Null
            Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:5173" | Out-Null
            break
        } catch {
            if ($attempt -eq 30) { throw "Local services did not become ready" }
            Start-Sleep -Seconds 1
        }
    }
    Push-Location (Join-Path $projectRoot "frontend")
    try {
        if ($Grep) { npm run test:e2e -- --grep $Grep }
        else { npm run test:e2e }
    } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "Playwright E2E failed" }
} finally {
    $listeners = Get-NetTCPConnection -State Listen -LocalPort 5173,8000 -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) { Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue }
    if ($frontend -and -not $frontend.HasExited) { Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue }
    if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue }
    Pop-Location
}
