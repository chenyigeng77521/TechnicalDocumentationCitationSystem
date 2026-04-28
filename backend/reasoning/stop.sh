#!/usr/bin/env bash
# =============================================================
# stop.sh — 停止 reasoning 推理层服务
#
# 说明：
#   本脚本不依赖 PID 文件，直接按端口查找并停止进程。
#   优先使用 lsof，无可用时降级到 ss / netstat。
#   默认端口 5050，可通过 REASONING_PORT 环境变量覆盖。
#
# 用法：
#   bash stop.sh              # 停止默认端口 5050
#   REASONING_PORT=5051 bash stop.sh   # 停止自定义端口
# =============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${REASONING_PORT:-5050}"
KILLED_ANY=0

# ── 辅助函数：尝试停止指定 PID ──────────────────────────────
_try_kill() {
    local pid="$1"
    if kill -0 "$pid" 2>/dev/null; then
        echo "🛑 停止 reasoning 进程 (PID: $pid)..."
        kill "$pid" 2>/dev/null || true
        KILLED_ANY=1
        sleep 0.5
        if kill -0 "$pid" 2>/dev/null; then
            echo "💥 进程 $pid 未响应 SIGTERM，发送 SIGKILL..."
            kill -9 "$pid" 2>/dev/null || true
        fi
    fi
}

# ── 1. 优先使用 lsof 按端口查找 ─────────────────────────────
if command -v lsof >/dev/null 2>&1; then
    if lsof -i :"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
        PIDS=$(lsof -ti :"$PORT" -sTCP:LISTEN)
        for PID in $PIDS; do
            _try_kill "$PID"
        done
        # 兜底：若仍有残留，再次检查并强杀
        sleep 0.3
        if lsof -i :"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
            PIDS=$(lsof -ti :"$PORT" -sTCP:LISTEN)
            for PID in $PIDS; do
                echo "💥 端口 $PORT 进程 $PID 仍未退出，发送 SIGKILL..."
                kill -9 "$PID" 2>/dev/null || true
            done
        fi
    fi

# ── 2. 降级：使用 ss ────────────────────────────────────────
elif command -v ss >/dev/null 2>&1; then
    if ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
        PIDS=$(ss -tlnp 2>/dev/null | grep ":$PORT " | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | sort -u)
        if [ -n "$PIDS" ]; then
            for PID in $PIDS; do
                _try_kill "$PID"
            done
        fi
    fi

# ── 3. 再降级：使用 netstat ─────────────────────────────────
elif command -v netstat >/dev/null 2>&1; then
    if netstat -tlnp 2>/dev/null | grep -q ":$PORT "; then
        PIDS=$(netstat -tlnp 2>/dev/null | grep ":$PORT " | awk '{print $NF}' | sed 's|/.*||' | sort -u)
        if [ -n "$PIDS" ]; then
            for PID in $PIDS; do
                _try_kill "$PID"
            done
        fi
    fi
fi

# ── 4. 最终状态 ─────────────────────────────────────────────
if [ "$KILLED_ANY" = "1" ]; then
    echo "✅ reasoning 服务已停止"
else
    echo "ℹ️  reasoning 服务未运行（端口 $PORT 无监听）"
fi
