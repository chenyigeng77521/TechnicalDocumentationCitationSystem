#!/usr/bin/env bash
# Reasoning Service 启动脚本（Layer 3 / 推理与引用层）
#
# 用法：
#   ./start.sh              # 前台启动（Ctrl+C 停止）
#   ./start.sh --bg         # 后台启动，PID 写入 .reasoning.pid
#   ./start.sh --bg --fake-llm --port 5050 --provider glm5
#
# 停止后台进程：
#   ./stop.sh

set -e

# ---- 路径 ----
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
PID_FILE="$SCRIPT_DIR/.reasoning.pid"
SERVER_LOG="$SCRIPT_DIR/../../../src/logs/reasoning.log"
BACKEND_LOG="$SCRIPT_DIR/../../../src/logs/backend.log"  # 共享日志

# ---- 配置 ----
PORT=8001
PYTHON_CMD="python"

#本机环境测试
#PYTHON_CMD='/Library/Frameworks/Python.framework/Versions/3.12/bin/python3'
EXTRA_ARGS=()

# ---- 解析参数 ----
MODE="foreground"
while [ $# -gt 0 ]; do
    case "$1" in
        --bg|-d)
            MODE="background"
            shift
            ;;
        --fake-llm|--test|--provider|--port|--score-threshold)
            EXTRA_ARGS+=("$1")
            if [ $# -gt 1 ] && [[ "$2" != --* ]]; then
                EXTRA_ARGS+=("$2")
                shift 2
            else
                shift
            fi
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

mkdir -p "$LOG_DIR"
mkdir -p "$SCRIPT_DIR/../../../src/logs"  # 确保共享日志目录存在
cd "$BACKEND_DIR"

# ---- 端口占用检查 ----
if lsof -i :$PORT -sTCP:LISTEN >/dev/null 2>&1; then
    EXISTING_PID=$(lsof -ti :$PORT -sTCP:LISTEN)
    echo "❌ 端口 $PORT 已被进程 $EXISTING_PID 占用"
    echo "   想杀掉旧进程？运行: ./src/backend/reasoning/stop.sh"
    exit 1
fi

echo "──────────────────────────────────────────────"
echo " Reasoning Service (Layer 3)"
echo "──────────────────────────────────────────────"
echo "  Backend dir  : $BACKEND_DIR"
echo "  Port         : $PORT"
echo "  Log dir      : $LOG_DIR"
echo "  Mode         : $MODE"
if [ ${#EXTRA_ARGS[@]} -gt 0 ]; then
    echo "  Extra args   : ${EXTRA_ARGS[*]}"
fi
echo "──────────────────────────────────────────────"

if [ "$MODE" = "foreground" ]; then
    echo "前台启动（Ctrl+C 停止）..."
    echo
    exec "$PYTHON_CMD" -m reasoning.main --port "$PORT" "${EXTRA_ARGS[@]}"
else
    # 后台模式
    echo "后台启动，日志写入: $SERVER_LOG"
    nohup "$PYTHON_CMD" -m reasoning.main --port "$PORT" "${EXTRA_ARGS[@]}" \
        >"$SERVER_LOG" 2>&1 &
    SERVER_PID=$!
    echo "$SERVER_PID" > "$PID_FILE"
    echo "PID: $SERVER_PID（已写入 $PID_FILE）"
    echo
    echo "等待服务就绪..."
    for i in $(seq 1 10); do
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
