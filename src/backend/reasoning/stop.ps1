# Stop Reasoning Service (PowerShell / Windows)
# Double check: kill PID from file first, then clean port residue.

$ErrorActionPreference = "SilentlyContinue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = "$ScriptDir\.reasoning.pid"
$Port = 8001

$KilledAny = $false

# 1. Main process from PID file
if (Test-Path $PidFile) {
    $PidStr = Get-Content $PidFile -Raw
    $PidVal = 0
    if ([int]::TryParse($PidStr, [ref]$PidVal)) {
        $Proc = Get-Process -Id $PidVal -ErrorAction SilentlyContinue
        if ($Proc) {
            Write-Host "Stopping main process $PidVal..."
            Stop-Process -Id $PidVal -Force
            $KilledAny = $true
        }
    }
    Remove-Item $PidFile -Force
}

# 2. Python process still listening on port (fallback)
Start-Sleep -Milliseconds 300
$Conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($Conn) {
    $PidVal = $Conn.OwningProcess
    Write-Host "Stopping process $PidVal on port $Port..."
    Stop-Process -Id $PidVal -Force
    $KilledAny = $true
}

if ($KilledAny) {
    Write-Host "[OK] Stopped" -ForegroundColor Green
} else {
    Write-Host "[INFO] No service running on port $Port" -ForegroundColor Cyan
}
