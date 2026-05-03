#!/usr/bin/env bash
# Ingestion Service 启动脚本（Layer 1 / 数据处理层）
#
# 用 PATH 里的 python（跟团队 scripts/startAll.sh 用 `which python` 保持一致）。
# 不依赖 conda——本地 conda 用户先 `conda activate <env>` 让 python 指向 env 里的解释器即可。
# 也可以用 PYTHON_BIN 环境变量显式指定。
#
# 用法：
#   ./start.sh                              # 前台启动（Ctrl+C 停止）
#   ./start.sh --bg                         # 后台启动，PID 写入 logs/server.pid
#   PYTHON_BIN=/path/to/python ./start.sh   # 指定特定解释器
#
# 停止：
#   ./stop.sh

set -e

# ---- 路径 ----
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
PID_FILE="$LOG_DIR/server.pid"
SERVER_LOG="$LOG_DIR/server.log"

# ---- Python 解释器 ----
# 默认按 python3.12 → python3 → python 顺序找（避免 macOS 老系统 `python` 是 Python 2.7 的坑）
# - 本地 conda 用户：conda activate <env> 后 PATH 里的 python3 自动指向 env
# - 生产部署：PATH 里就是系统 / venv 的 python3
# - 显式覆盖：PYTHON_BIN=/path/to/python ./start.sh
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3.12 || command -v python3)}"

# ---- 联调用：传文件接口（默认关闭，联调时设 true 启用）
INGESTION_UPLOAD_ENABLED=${INGESTION_UPLOAD_ENABLED:-false}
export INGESTION_UPLOAD_ENABLED

mkdir -p "$LOG_DIR"
# cd 到 src/，让 `python -m backend.ingestion.api.server` 模块路径能解析
cd "$PROJECT_ROOT/src"

# ---- 加载环境变量（让 AIGW_API_KEY 等进 server 进程）----
# src/.env：团队共享非敏感配置（git tracked）
# src/.env.aigw：含 API key 等敏感信息（gitignored，需各自创建）
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

# 校验 AIGW_API_KEY（warning 不阻塞；首次 embedding 调用才会失败）
if [ -z "${AIGW_API_KEY:-}" ]; then
    echo "⚠️  AIGW_API_KEY 未设置！embedding 调用会在首次请求时失败"
    echo "   方案 1：创建 src/.env.aigw 含 AIGW_API_KEY=...（参考 src/.env.aigw.example）"
    echo "   方案 2：export AIGW_API_KEY=... 后启动"
    echo "   方案 3：用本地 SentenceTransformer 模型：export EMBEDDING_USE_LOCAL=1"
fi

# ---- Python 检查 ----
if [ -z "$PYTHON_BIN" ] || ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "❌ 找不到 Python 解释器（需要 python3.12 或 python3 在 PATH 里）"
    echo "   方案 1：本地 conda 用户：conda activate <env> 后再跑"
    echo "   方案 2：装 python3 到 PATH 或 PYTHON_BIN=/path/to/python3 ./start.sh"
    exit 1
fi
# 校验是 Python 3（避免不小心用了 macOS 系统自带的 Python 2.7）
PY_MAJOR=$("$PYTHON_BIN" -c 'import sys; print(sys.version_info[0])' 2>/dev/null || echo "?")
if [ "$PY_MAJOR" != "3" ]; then
    echo "❌ Python 版本不对：$($PYTHON_BIN --version 2>&1)（需要 Python 3.x）"
    echo "   解释器路径: $PYTHON_BIN"
    echo "   方案 1：PYTHON_BIN=python3.12 ./start.sh（或绝对路径）"
    echo "   方案 2：检查 PATH，让 python3 比 python 优先"
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
echo " Ingestion Service (Layer 1)"
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
