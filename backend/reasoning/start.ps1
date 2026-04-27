<#
.SYNOPSIS
    启动 / 停止 / 查看 reasoning 推理层服务

.DESCRIPTION
    该脚本等价于 start.sh，为 Windows PowerShell 环境设计。
    支持前台运行（默认）和后台运行（-Background）。

.EXAMPLE
    .\start.ps1                        # 前台启动
    .\start.ps1 -Background            # 后台启动
    .\start.ps1 --fake-llm             # Fake LLM 模式（不调用真实 API）
    .\start.ps1 --provider kimi        # 切换 LLM provider
    .\start.ps1 --port 5051            # 自定义端口
    .\start.ps1 -Stop                 # 停止后台服务
    .\start.ps1 -Status               # 查看服务状态
#>

[CmdletBinding()]
param(
    [switch]$Background,
    [switch]$Stop,
    [switch]$Status,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

$ErrorActionPreference = "Stop"

# ── 定位脚本所在目录 ───────────────────────────────────────────
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $ScriptDir

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$PidFile = Join-Path $ScriptDir ".reasoning.pid"
$LogDir = Join-Path $ProjectRoot "logs"
$LogFile = Join-Path $LogDir "reasoning.log"
$ErrFile = Join-Path $LogDir "reasoning.err"

# ── 状态查询 ──────────────────────────────────────────────────
if ($Status) {
    if (Test-Path $PidFile) {
        $pidValue = Get-Content $PidFile -Raw
        $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "✅ reasoning 服务正在运行 (PID: $pidValue)" -ForegroundColor Green
            Write-Host "   日志文件: $LogFile"
        } else {
            Write-Host "⚠️ PID 文件存在但进程未运行 (PID: $pidValue)" -ForegroundColor Yellow
            Write-Host "   建议删除 PID 文件后重新启动"
        }
    } else {
        Write-Host "❌ reasoning 服务未运行（未找到 PID 文件）" -ForegroundColor Red
    }
    exit 0
}

# ── 停止服务 ──────────────────────────────────────────────────
if ($Stop) {
    if (Test-Path $PidFile) {
        $pidValue = Get-Content $PidFile -Raw
        $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "🛑 停止 reasoning 服务 (PID: $pidValue)..." -ForegroundColor Yellow
            Stop-Process -Id $pidValue -Force
            Write-Host "✅ 服务已停止" -ForegroundColor Green
        } else {
            Write-Host "⚠️ PID 文件存在但进程未运行" -ForegroundColor Yellow
        }
        Remove-Item $PidFile -Force
    } else {
        Write-Host "❌ 未找到 PID 文件，服务可能未在后台运行" -ForegroundColor Red
    }
    exit 0
}

# ── 加载 .env（若存在）────────────────────────────────────────
$EnvFile = Join-Path -Path $ScriptDir -ChildPath ".env"
if (Test-Path $EnvFile) {
    Write-Host "📄 加载 .env 配置..." -ForegroundColor Cyan
    foreach ($line in Get-Content $EnvFile) {
        $line = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith("#")) { continue }
        $parts = $line -split '=', 2
        if ($parts.Length -eq 2) {
            $name = $parts[0].Trim()
            $val = $parts[1].Trim()
            # 移除外层引号（如果有的话）
            if ($val.Length -ge 2 -and (($val.StartsWith('"') -and $val.EndsWith('"')) -or ($val.StartsWith("'") -and $val.EndsWith("'")))) {
                $val = $val.Substring(1, $val.Length - 2)
            }
            [Environment]::SetEnvironmentVariable($name, $val, "Process")
        }
    }
}

# ── Python 环境检查 ───────────────────────────────────────────
$PythonCmd = "python"
if (Get-Command "python3" -ErrorAction SilentlyContinue) {
    $PythonCmd = "python3"
}
$PythonVersion = & $PythonCmd --version 2>&1
Write-Host "🐍 Python: $PythonVersion" -ForegroundColor Cyan

# ── 可选：激活虚拟环境 ────────────────────────────────────────
$VenvDirs = @(".venv", "venv", "..\.venv")
foreach ($dir in $VenvDirs) {
    $ActivateScript = Join-Path -Path $ScriptDir -ChildPath "$dir\Scripts\Activate.ps1"
    if (Test-Path $ActivateScript) {
        Write-Host "🔧 激活虚拟环境: $dir" -ForegroundColor Cyan
        . $ActivateScript
        break
    }
}

# ── 依赖检查（首次运行时自动安装）───────────────────────────
$CheckFlask = & $PythonCmd -c "import flask" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "📦 安装依赖 (pip install -r requirements.txt)..." -ForegroundColor Yellow
    & $PythonCmd -m pip install -r requirements.txt
}

# ── 默认参数（可被环境变量覆盖）─────────────────────────────
$HostIP = [Environment]::GetEnvironmentVariable("REASONING_HOST")
if ([string]::IsNullOrEmpty($HostIP)) { $HostIP = "0.0.0.0" }

$Port = [Environment]::GetEnvironmentVariable("REASONING_PORT")
if ([string]::IsNullOrEmpty($Port)) { $Port = "5050" }

$Provider = [Environment]::GetEnvironmentVariable("LLM_ACTIVE_PROVIDER")
if ([string]::IsNullOrEmpty($Provider)) { $Provider = "（未设置，使用内置默认值）" }

# 组装启动参数
$RunArgs = @("-m", "reasoning.main", "--host", $HostIP, "--port", $Port)
if ($ScriptArgs) {
    $RunArgs += $ScriptArgs
}

# 由于模块入口在 reasoning.main，确保我们是在 backend 目录下来执行
$BackendDir = Split-Path -Parent $ScriptDir
$env:PYTHONPATH = $BackendDir

# ── 后台模式 ──────────────────────────────────────────────────
if ($Background) {
    # 检查是否已有实例在运行
    if (Test-Path $PidFile) {
        $existingPid = Get-Content $PidFile -Raw
        $existingProcess = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($existingProcess) {
            Write-Host "⚠️ reasoning 服务已在后台运行 (PID: $existingPid)" -ForegroundColor Yellow
            Write-Host "   如需重启，请先执行: .\start.ps1 -Stop" -ForegroundColor Yellow
            exit 1
        } else {
            Remove-Item $PidFile -Force
        }
    }

    # 确保日志目录存在
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir | Out-Null
    }

    Write-Host "🚀 后台启动 reasoning 服务: http://${HostIP}:${Port}" -ForegroundColor Green
    Write-Host "   Provider : $Provider"
    Write-Host "   Config   : reasoning_config.yaml"
    Write-Host "   日志文件 : $LogFile"
    Write-Host "   PID 文件 : $PidFile"
    Write-Host "─────────────────────────────────────────────────────────"

    # 构建环境变量传递字符串（Start-Process 需要显式传递）
    $pythonPathEnv = $env:PYTHONPATH
    $pathEnv = $env:PATH

    # 收集所有需要传递的环境变量（.env 中加载的 + PYTHONPATH）
    $envVars = @{}
    foreach ($line in Get-Content $EnvFile -ErrorAction SilentlyContinue) {
        $line = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith("#")) { continue }
        $parts = $line -split '=', 2
        if ($parts.Length -eq 2) {
            $name = $parts[0].Trim()
            $val = $parts[1].Trim()
            if ($val.Length -ge 2 -and (($val.StartsWith('"') -and $val.EndsWith('"')) -or ($val.StartsWith("'") -and $val.EndsWith("'")))) {
                $val = $val.Substring(1, $val.Length - 2)
            }
            $envVars[$name] = $val
        }
    }
    $envVars["PYTHONPATH"] = $pythonPathEnv

    # 使用 Start-Process 后台启动
    $proc = Start-Process -FilePath $PythonCmd `
        -ArgumentList $RunArgs `
        -WorkingDirectory $BackendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError $ErrFile `
        -PassThru

    # 记录 PID
    $proc.Id | Out-File -FilePath $PidFile -Encoding utf8 -NoNewline

    Write-Host "✅ 服务已后台启动 (PID: $($proc.Id))" -ForegroundColor Green
    Write-Host "   查看日志: Get-Content '$LogFile' -Tail 20 -Wait"
    Write-Host "   停止服务: .\start.ps1 -Stop"
    exit 0
}

# ── 前台模式（默认）───────────────────────────────────────────
Write-Host "🚀 前台启动 reasoning 服务: http://${HostIP}:${Port}" -ForegroundColor Green
Write-Host "   Provider : $Provider"
Write-Host "   Config   : reasoning_config.yaml"
Write-Host "   按 Ctrl+C 停止服务"
Write-Host "─────────────────────────────────────────────────────────"

& $PythonCmd @RunArgs
