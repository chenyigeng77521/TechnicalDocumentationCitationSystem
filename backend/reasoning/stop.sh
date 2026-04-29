#!/usr/bin/env bash
# 停止 Reasoning Service
#
# nohup 启动的 python 进程，PID 记录在 .reasoning.pid。
# 双保险：先杀 PID 文件里的主进程，再清端口残留。

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.reasoning.pid"
PORT=5050

KILLED_ANY=0

# 1. PID 文件里的主进程
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "停止主进程 $PID..."
        kill "$PID" 2>/dev/null || true
        KILLED_ANY=1
    fi
    rm -f "$PID_FILE"
fi

# 2. 端口上残留的 python 进程（兜底）
sleep 0.3
if lsof -i :$PORT -sTCP:LISTEN >/dev/null 2>&1; then
    PIDS=$(lsof -ti :$PORT -sTCP:LISTEN)
    for PID in $PIDS; do
        echo "停止端口 $PORT 上的进程 $PID..."
        kill "$PID" 2>/dev/null || true
        KILLED_ANY=1
    done
    # 等一下再检查；还在就 -9 强杀
    sleep 0.5
    if lsof -i :$PORT -sTCP:LISTEN >/dev/null 2>&1; then
        PIDS=$(lsof -ti :$PORT -sTCP:LISTEN)
        for PID in $PIDS; do
            echo "进程 $PID 没响应 SIGTERM，发 SIGKILL..."
            kill -9 "$PID" 2>/dev/null || true
        done
    fi
fi

if [ "$KILLED_ANY" = "1" ]; then
    echo "✅ 已停止"
else
    echo "ℹ️  端口 $PORT 上没有运行中的服务"
fi
