#!/usr/bin/env bash
# Ingestion Service 启动脚本（Layer 1 / 数据处理层）
#
# 用法：
#   ./start.sh           # 前台启动（Ctrl+C 停止）
#   ./start.sh --bg      # 后台启动，PID 写入 logs/server.pid
#
# 停止后台进程：
#   ./stop.sh
#   或：kill $(cat logs/server.pid)

set -e

# ---- 路径 ----
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
PID_FILE="$LOG_DIR/server.pid"
SERVER_LOG="$LOG_DIR/server.log"

# ---- 配置 ----
CONDA_BIN="/opt/anaconda3/bin/conda"
CONDA_ENV="sqllineage"
PORT=3003

mkdir -p "$LOG_DIR"
cd "$PROJECT_ROOT"

# ---- 端口占用检查 ----
if lsof -i :$PORT -sTCP:LISTEN >/dev/null 2>&1; then
    EXISTING_PID=$(lsof -ti :$PORT -sTCP:LISTEN)
    echo "❌ 端口 $PORT 已被进程 $EXISTING_PID 占用"
    echo "   想杀掉旧进程？运行: kill $EXISTING_PID"
    echo "   或用: ./stop.sh"
    exit 1
fi

# ---- conda 检查 ----
if [ ! -x "$CONDA_BIN" ]; then
    echo "❌ 找不到 conda: $CONDA_BIN"
    echo "   请检查 conda 安装路径，或修改本脚本中的 CONDA_BIN 变量"
    exit 1
fi

# ---- 启动模式 ----
MODE="foreground"
if [ "$1" = "--bg" ] || [ "$1" = "-d" ]; then
    MODE="background"
fi

echo "──────────────────────────────────────────────"
echo " Ingestion Service (Layer 1)"
echo "──────────────────────────────────────────────"
echo "  Project root : $PROJECT_ROOT"
echo "  Conda env    : $CONDA_ENV"
echo "  Port         : $PORT"
echo "  Log dir      : $LOG_DIR"
echo "  Mode         : $MODE"
echo "──────────────────────────────────────────────"

if [ "$MODE" = "foreground" ]; then
    echo "前台启动（Ctrl+C 停止）..."
    echo
    exec "$CONDA_BIN" run -n "$CONDA_ENV" --no-capture-output \
        python -m backend.ingestion.api.server
else
    # 后台模式
    echo "后台启动，日志写入: $SERVER_LOG"
    nohup "$CONDA_BIN" run -n "$CONDA_ENV" --no-capture-output \
        python -m backend.ingestion.api.server \
        >"$SERVER_LOG" 2>&1 &
    SERVER_PID=$!
    echo "$SERVER_PID" > "$PID_FILE"
    echo "PID: $SERVER_PID（已写入 $PID_FILE）"
    echo
    echo "等待服务就绪..."
    for i in 1 2 3 4 5 6 7 8 9 10; do
        if curl -sf "http://localhost:$PORT/health" >/dev/null 2>&1; then
            echo "✅ 服务已就绪: http://localhost:$PORT"
            echo
            echo "查日志:  tail -f $SERVER_LOG"
            echo "停止:    ./stop.sh"
            exit 0
        fi
        sleep 1
    done
    echo "⚠️  10 秒内未就绪，请查日志: $SERVER_LOG"
    exit 1
fi
