# Start the Agent Desktop UI (FastAPI on AGENT_UI_PORT, default 8120).
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
            [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
}

$Port = if ($env:AGENT_UI_PORT) { $env:AGENT_UI_PORT } else { "8120" }
$Gateway = if ($env:LLM_GATEWAY_V10_URL) { $env:LLM_GATEWAY_V10_URL } else { "http://localhost:8110" }

Write-Host ""
Write-Host "  Agent Desktop UI" -ForegroundColor Cyan
Write-Host "  Gateway: $Gateway" -ForegroundColor Gray
Write-Host "  UI:      http://localhost:$Port" -ForegroundColor Green
Write-Host ""

try {
    $null = Invoke-WebRequest -Uri "$Gateway/v1/routers" -UseBasicParsing -TimeoutSec 3
    Write-Host "  Gateway: OK" -ForegroundColor Green
} catch {
    Write-Host "  Gateway: not reachable at $Gateway" -ForegroundColor Yellow
    Write-Host "  Start llm_gatewayV10 first: ..\llm_gatewayV10\run.ps1" -ForegroundColor Yellow
}

$cuaExe = $null
$cua = Get-Command cua-driver -ErrorAction SilentlyContinue
if ($cua) {
    $cuaExe = $cua.Source
} else {
    $cuaFallback = Join-Path $env:LOCALAPPDATA "Programs\Cua\cua-driver\bin\cua-driver.exe"
    if (Test-Path $cuaFallback) {
        $cuaExe = $cuaFallback
        $env:Path = "$(Split-Path $cuaFallback -Parent);$env:Path"
    }
}
if ($cuaExe) {
    try {
        & $cuaExe status 2>&1 | Out-Null
        Write-Host "  cua-driver: OK" -ForegroundColor Green
    } catch {
        Write-Host "  cua-driver: installed but daemon may be down" -ForegroundColor Yellow
        Write-Host "  Run: .\scripts\setup_cua_driver.ps1" -ForegroundColor Yellow
    }
} else {
    Write-Host "  cua-driver: not on PATH (computer presets need it)" -ForegroundColor Yellow
    Write-Host "  Run: .\scripts\setup_cua_driver.ps1" -ForegroundColor Yellow
}

Write-Host ""
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $py) {
  # Avoid `uv run` sync when OneDrive locks .venv package metadata.
  & $py -m uvicorn ui_server:app --host 127.0.0.1 --port $Port
} else {
  uv run uvicorn ui_server:app --host 127.0.0.1 --port $Port
}
