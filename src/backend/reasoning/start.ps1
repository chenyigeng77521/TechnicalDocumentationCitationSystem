# Reasoning Service Startup Script (PowerShell / Windows)
# Layer 3: Reasoning & Citation Layer
#
# Usage:
#   .\start.ps1              # Foreground mode (Ctrl+C to stop)
#   .\start.ps1 -Bg          # Background mode (Start-Process)
#   .\start.ps1 -Bg -FakeLLM # Background + Fake LLM mode
#   .\start.ps1 -Bg -Provider glm5 -Port 5050
#
# Stop:
#   .\stop.ps1

param(
    [switch]$Bg,
    [switch]$FakeLLM,
    [switch]$Test,
    [string]$Provider,
    [int]$Port = 8001,
    [double]$ScoreThreshold
)

$ErrorActionPreference = "Stop"

# ---- Paths ----
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Resolve-Path "$ScriptDir\.."
$LogDir = "$ScriptDir\logs"
$PidFile = "$ScriptDir\.reasoning.pid"
$ServerLog = "$LogDir\reasoning.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $BackendDir

# ---- Port check ----
$Existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($Existing) {
    $ExistingPid = $Existing.OwningProcess
    Write-Host "[ERROR] Port $Port is already in use by process $ExistingPid" -ForegroundColor Red
    Write-Host "        Run: .\backend\reasoning\stop.ps1"
    exit 1
}

# ---- Build args ----
$PyArgs = @("-m", "reasoning.main", "--port", $Port)
if ($FakeLLM) { $PyArgs += "--fake-llm" }
if ($Test)    { $PyArgs += "--test" }
if ($Provider) { $PyArgs += @("--provider", $Provider) }
if ($ScoreThreshold) { $PyArgs += @("--score-threshold", $ScoreThreshold) }

Write-Host "----------------------------------------------"
Write-Host " Reasoning Service (Layer 3)"
Write-Host "----------------------------------------------"
Write-Host "  Backend dir  : $BackendDir"
Write-Host "  Port         : $Port"
Write-Host "  Log dir      : $LogDir"
Write-Host "  Mode         : $(if ($Bg) { 'background' } else { 'foreground' })"
Write-Host "  Python args  : $($PyArgs -join ' ')"
Write-Host "----------------------------------------------"

if (-not $Bg) {
    Write-Host "Foreground mode (Ctrl+C to stop)..." -ForegroundColor Cyan
    & python @PyArgs
} else {
    # Background mode
    Write-Host "Background mode, logging to: $ServerLog" -ForegroundColor Cyan

    $Proc = Start-Process -FilePath "python" -ArgumentList $PyArgs `
        -WorkingDirectory $BackendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $ServerLog `
        -RedirectStandardError $ServerLog `
        -PassThru

    $Proc.Id | Out-File -FilePath $PidFile -Encoding utf8 -NoNewline
    Write-Host "PID: $($Proc.Id) (written to $PidFile)"
    Write-Host
    Write-Host "Waiting for service to be ready..." -ForegroundColor Cyan

    for ($i = 1; $i -le 10; $i++) {
        try {
            $Resp = Invoke-WebRequest -Uri "http://localhost:$Port/health" -Method GET -TimeoutSec 2 -ErrorAction Stop
            if ($Resp.StatusCode -eq 200) {
                Write-Host "[OK] Service is ready: http://localhost:$Port" -ForegroundColor Green
                Write-Host
                Write-Host "View logs: Get-Content $ServerLog -Tail 20 -Wait"
                Write-Host "Stop:      .\stop.ps1"
                exit 0
            }
        } catch {}
        Start-Sleep -Seconds 1
    }

    Write-Host "[WARN] Service not ready within 10s, check logs: $ServerLog" -ForegroundColor Yellow
    exit 1
}
