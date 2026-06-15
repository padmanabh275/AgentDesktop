# Install and verify cua-driver on Windows (Session 10 Computer-Use prerequisite).
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  Session 10 - cua-driver setup" -ForegroundColor Cyan
Write-Host ""

$cua = Get-Command cua-driver -ErrorAction SilentlyContinue
if (-not $cua) {
    Write-Host "  Installing cua-driver..." -ForegroundColor Yellow
    irm https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.ps1 | iex
} else {
    Write-Host "  cua-driver already on PATH: $($cua.Source)" -ForegroundColor Green
}

Write-Host ""
Write-Host "  Version:" -ForegroundColor Gray
& cua-driver --version

Write-Host ""
Write-Host "  Starting daemon (autostart kick)..." -ForegroundColor Yellow
& cua-driver autostart kick

Write-Host ""
Write-Host "  Checking permissions / doctor..." -ForegroundColor Yellow
& cua-driver doctor 2>&1 | Out-Host

Write-Host ""
Write-Host "  Done. Keep the daemon running for computer-use tasks." -ForegroundColor Green
Write-Host ""
