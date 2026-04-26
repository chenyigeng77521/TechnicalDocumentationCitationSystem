#!/usr/bin/env bash
# 停止 Ingestion Service
#
# conda run 是个 wrapper，它 fork 出 python child 才是真正监听端口的进程。
# 所以双保险：先 kill PID 文件里的 wrapper，再 kill 端口上残留的 python。

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/logs/server.pid"
PORT=3003

KILLED_ANY=0

# 1. PID 文件里的 wrapper 进程
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "停止 wrapper 进程 $PID..."
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
