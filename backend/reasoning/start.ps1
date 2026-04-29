# Reasoning Service 启动脚本（PowerShell / Windows）
# Layer 3: 推理与引用层
#
# 用法：
#   .\start.ps1              # 前台启动
#   .\start.ps1 -Bg          # 后台启动（Start-Process）
#   .\start.ps1 -Bg -FakeLLM # 后台 + Fake LLM 模式
#   .\start.ps1 -Bg -Provider glm5 -Port 5050
#
# 停止：
#   .\stop.ps1

param(
    [switch]$Bg,
    [switch]$FakeLLM,
    [switch]$Test,
    [string]$Provider,
    [int]$Port = 5050,
    [double]$ScoreThreshold
)

$ErrorActionPreference = "Stop"

# ---- 路径 ----
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path "$ScriptDir\..\.."
$LogDir = "$ScriptDir\logs"
$PidFile = "$ScriptDir\.reasoning.pid"
$ServerLog = "$LogDir\reasoning.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $ProjectRoot

# ---- 端口占用检查 ----
$Existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($Existing) {
    $ExistingPid = $Existing.OwningProcess
    Write-Host "❌ 端口 $Port 已被进程 $ExistingPid 占用" -ForegroundColor Red
    Write-Host "   想杀掉旧进程？运行: .\backend\reasoning\stop.ps1"
    exit 1
}

# ---- 构建参数 ----
$PyArgs = @("-m", "reasoning.main", "--port", $Port)
if ($FakeLLM) { $PyArgs += "--fake-llm" }
if ($Test)    { $PyArgs += "--test" }
if ($Provider) { $PyArgs += @("--provider", $Provider) }
if ($ScoreThreshold) { $PyArgs += @("--score-threshold", $ScoreThreshold) }

Write-Host "──────────────────────────────────────────────"
Write-Host " Reasoning Service (Layer 3)"
Write-Host "──────────────────────────────────────────────"
Write-Host "  Project root : $ProjectRoot"
Write-Host "  Port         : $Port"
Write-Host "  Log dir      : $LogDir"
Write-Host "  Mode         : $(if ($Bg) { 'background' } else { 'foreground' })"
Write-Host "  Python args  : $($PyArgs -join ' ')"
Write-Host "──────────────────────────────────────────────"

if (-not $Bg) {
    Write-Host "前台启动（Ctrl+C 停止）..." -ForegroundColor Cyan
    & python @PyArgs
} else {
    # 后台模式：Start-Process + 窗口隐藏
    Write-Host "后台启动，日志写入: $ServerLog" -ForegroundColor Cyan

    $Proc = Start-Process -FilePath "python" -ArgumentList $PyArgs `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $ServerLog `
        -RedirectStandardError $ServerLog `
        -PassThru

    $Proc.Id | Out-File -FilePath $PidFile -Encoding utf8 -NoNewline
    Write-Host "PID: $($Proc.Id)（已写入 $PidFile）"
    Write-Host
    Write-Host "等待服务就绪..." -ForegroundColor Cyan

    for ($i = 1; $i -le 10; $i++) {
        try {
            $Resp = Invoke-WebRequest -Uri "http://localhost:$Port/api/reasoning/health" -Method GET -TimeoutSec 2 -ErrorAction Stop
            if ($Resp.StatusCode -eq 200) {
                Write-Host "✅ 服务已就绪: http://localhost:$Port" -ForegroundColor Green
                Write-Host
                Write-Host "查日志:  Get-Content $ServerLog -Tail 20 -Wait"
                Write-Host "停止:    .\stop.ps1"
                exit 0
            }
        } catch {}
        Start-Sleep -Seconds 1
    }

    Write-Host "⚠️ 10 秒内未就绪，请查日志: $ServerLog" -ForegroundColor Yellow
    exit 1
}
