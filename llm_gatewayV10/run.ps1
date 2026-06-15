# Start LLM Gateway V10 on port 8110 (Windows)
Set-Location $PSScriptRoot

$port = 8110
if ($env:GATEWAY_V10_PORT) { $port = $env:GATEWAY_V10_PORT }
elseif ($env:GATEWAY_V9_PORT) { $port = $env:GATEWAY_V9_PORT }

$url = "http://127.0.0.1:$port"
Write-Host ""
Write-Host "  LLM Gateway V10" -ForegroundColor Cyan
Write-Host "  Dashboard:  $url" -ForegroundColor Green
Write-Host "  Help:       $url/help" -ForegroundColor Green
Write-Host ""
Write-Host "  Run the orchestrator in a SECOND terminal:" -ForegroundColor Yellow
Write-Host "    cd ..\code" -ForegroundColor Gray
Write-Host '    uv run python flow.py "your question"' -ForegroundColor Gray
Write-Host ""
Write-Host "  (This window shows API logs only - agent output appears in the other terminal.)" -ForegroundColor DarkGray
Write-Host ""

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Write-Host "  Tip: copy .env.example to .env and add your API keys." -ForegroundColor Yellow
        Write-Host ""
    }
}

$env:UV_LINK_MODE = "copy"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

function Test-GatewayVenv {
    if (-not (Test-Path $python)) { return $false }
    & $python -c "import fastapi, uvicorn" 2>$null
    return $LASTEXITCODE -eq 0
}

if (-not (Test-GatewayVenv)) {
    Write-Host "  Setting up gateway dependencies (no dev/test packages)..." -ForegroundColor Yellow
    uv sync --no-dev
    if (-not (Test-GatewayVenv)) {
        Write-Host ""
        Write-Host "  ERROR: Could not prepare .venv." -ForegroundColor Red
        Write-Host "  Close other terminals/editors using this folder, then run:" -ForegroundColor Yellow
        Write-Host "    Remove-Item -Recurse -Force .venv" -ForegroundColor Gray
        Write-Host "    .\run.ps1" -ForegroundColor Gray
        Write-Host ""
        exit 1
    }
}

# Avoid WinError 10048 if the gateway is already up or the port is taken.
$gatewayUp = $false
try {
    $health = Invoke-WebRequest -Uri "$url/v1/routers" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
    $gatewayUp = ($health.StatusCode -eq 200)
} catch {
    $gatewayUp = $false
}

if ($gatewayUp) {
    Write-Host "  Gateway already running on port $port." -ForegroundColor Green
    Write-Host "  Reusing it. Stop the other terminal if you need a fresh start." -ForegroundColor DarkGray
    Write-Host ""
    try { Start-Process $url } catch { }
    exit 0
}

$listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.OwningProcess -gt 0 } |
    Select-Object -ExpandProperty OwningProcess -Unique)

if ($listeners.Count -gt 0) {
    Write-Host "  ERROR: port $port is already in use (not this gateway)." -ForegroundColor Red
    foreach ($listenerPid in $listeners) {
        $proc = Get-Process -Id $listenerPid -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host ('    PID {0} - {1} ({2})' -f $listenerPid, $proc.ProcessName, $proc.Path) -ForegroundColor Yellow
        }
    }
    Write-Host ""
    Write-Host "  Free the port, then re-run .\run.ps1:" -ForegroundColor Yellow
    Write-Host '    Get-NetTCPConnection -LocalPort 8110 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }' -ForegroundColor Gray
    Write-Host ""
    exit 1
}

try {
    Start-Process $url
} catch {
    Write-Host "  Open $url in your browser to see the dashboard." -ForegroundColor Yellow
}

& $python main.py
