#!/usr/bin/env bash
# Ingestion Service 生产环境启动脚本（Layer 1 / 数据处理层）
#
# 跟本地 start.sh 的区别：
#   - 本地 start.sh  → 用 conda env sqllineage（团队成员开发用）
#   - 生产 start-prod.sh → 用本地 Python（部署到比赛服 / 生产共享环境用）
#
# 前置条件（生产环境一次性配好）：
#   1. 已装 Python 3.12+：python3.12 --version
#   2. 已装依赖：python3.12 -m pip install -r src/backend/ingestion/requirements.txt
#   3. 配 src/.env.aigw 含 AIGW_API_KEY（参考 src/.env.aigw.example）
#
# 用法：
#   ./start-prod.sh                          # 前台启动（默认 python3）
#   ./start-prod.sh --bg                     # 后台启动
#   PYTHON_BIN=/path/to/python ./start-prod.sh   # 显式指定解释器路径
#
# 停止：
#   ./stop.sh   # 跟 start.sh 共用，按 PID 文件 kill

set -e

# ---- 路径 ----
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
PID_FILE="$LOG_DIR/server.pid"
SERVER_LOG="$LOG_DIR/server.log"

# ---- 配置 ----
# Python 解释器：默认 PATH 里的 python3，可通过 PYTHON_BIN 环境变量覆盖
PYTHON_BIN="${PYTHON_BIN:-python3}"

# ---- 联调用：传文件接口（默认关闭）----
INGESTION_UPLOAD_ENABLED=${INGESTION_UPLOAD_ENABLED:-false}
export INGESTION_UPLOAD_ENABLED

mkdir -p "$LOG_DIR"
# cd 到 src/，让 `python -m backend.ingestion.api.server` 模块路径能解析
# （backend/ 包在 PROJECT_ROOT/src/backend/，不在 PROJECT_ROOT/backend/）
cd "$PROJECT_ROOT/src"

# ---- 加载环境变量（让 AIGW_API_KEY 等进 server 进程）----
# 生产环境通常通过容器 env / k8s secret 注入，但仍兼容本地 .env 文件
for env_file in "$PROJECT_ROOT/src/.env" "$PROJECT_ROOT/src/.env.aigw"; do
    if [ -f "$env_file" ]; then
        set -a
        # shellcheck disable=SC1091
        source "$env_file"
        set +a
    fi
done

# ---- 端口（必须放在 source .env 之后，否则 src/.env 里 PORT=3002 是 entrance 的，会污染 ingestion）----
PORT="${INGESTION_PORT:-3003}"

# 校验 AIGW_API_KEY 已设置（warning，不阻塞启动；首次 embedding 调用才会失败）
if [ -z "${AIGW_API_KEY:-}" ]; then
    echo "⚠️  AIGW_API_KEY 未设置！embedding 调用会在首次请求时失败"
    echo "   方案 1：创建 src/.env.aigw 含 AIGW_API_KEY=..."
    echo "   方案 2：export AIGW_API_KEY=... 后启动"
    echo "   方案 3：用本地 SentenceTransformer 模型：export EMBEDDING_USE_LOCAL=1"
fi

# ---- Python 检查 ----
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "❌ 找不到 Python 解释器: $PYTHON_BIN"
    echo "   方案 1：安装 python3 到 PATH"
    echo "   方案 2：PYTHON_BIN=/path/to/python ./start-prod.sh"
    exit 1
fi

# ---- 端口占用检查 ----
if lsof -i :$PORT -sTCP:LISTEN >/dev/null 2>&1; then
    EXISTING_PID=$(lsof -ti :$PORT -sTCP:LISTEN)
    echo "❌ 端口 $PORT 已被进程 $EXISTING_PID 占用"
    echo "   想杀掉旧进程？运行: kill $EXISTING_PID 或 ./stop.sh"
    exit 1
fi

# ---- 启动模式 ----
MODE="foreground"
if [ "$1" = "--bg" ] || [ "$1" = "-d" ]; then
    MODE="background"
fi

echo "──────────────────────────────────────────────"
echo " Ingestion Service (Layer 1) — 生产模式"
echo "──────────────────────────────────────────────"
echo "  Project root : $PROJECT_ROOT"
echo "  Python       : $PYTHON_BIN ($($PYTHON_BIN --version 2>&1))"
echo "  Port         : $PORT"
echo "  Log dir      : $LOG_DIR"
echo "  Mode         : $MODE"
echo "──────────────────────────────────────────────"

if [ "$MODE" = "foreground" ]; then
    echo "前台启动（Ctrl+C 停止）..."
    echo
    exec "$PYTHON_BIN" -m backend.ingestion.api.server
else
    echo "后台启动，日志写入: $SERVER_LOG"
    nohup "$PYTHON_BIN" -m backend.ingestion.api.server \
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
