#!/usr/bin/env bash
# =============================================================
# start.sh — 启动 reasoning 推理层服务
# 用法：bash start.sh [选项]
#
# 常用示例：
#   bash start.sh                        # 从 .env 读取配置，正常启动
#   bash start.sh --fake-llm             # Fake LLM 模式（不调用真实 API）
#   bash start.sh --provider kimi        # 切换 LLM provider
#   bash start.sh --port 5051            # 自定义端口
#   bash start.sh --score-threshold 0.3  # 调整拒答阈值
# =============================================================

set -e  # 遇到错误立即退出

# ── 定位脚本所在目录（兼容软链接场景）────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── 加载 .env（若存在）──────────────────────────────────────
if [ -f ".env" ]; then
    echo "📄 加载 .env 配置..."
    set -o allexport
    source .env
    set +o allexport
fi

# ── Python 环境检查 ──────────────────────────────────────────
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" &>/dev/null; then
    PYTHON="python"
fi

echo "🐍 Python: $($PYTHON --version)"

# ── 可选：激活虚拟环境 ───────────────────────────────────────
# 按以下优先级查找 venv（注释掉不需要的行）
for VENV_DIR in ".venv" "venv" "../.venv"; do
    if [ -f "$VENV_DIR/bin/activate" ]; then
        echo "🔧 激活虚拟环境: $VENV_DIR"
        source "$VENV_DIR/bin/activate"
        break
    elif [ -f "$VENV_DIR/Scripts/activate" ]; then
        # Windows Git Bash / MINGW
        echo "🔧 激活虚拟环境 (Windows): $VENV_DIR"
        source "$VENV_DIR/Scripts/activate"
        break
    fi
done

# ── 依赖检查（首次运行时自动安装）──────────────────────────
if ! $PYTHON -c "import flask" &>/dev/null 2>&1; then
    echo "📦 安装依赖 (pip install -r requirements.txt)..."
    pip install -r requirements.txt
fi

# ── 默认参数（可被命令行参数覆盖）──────────────────────────
HOST="${REASONING_HOST:-0.0.0.0}"
PORT="${REASONING_PORT:-5050}"

# ── 启动服务 ─────────────────────────────────────────────────
echo "🚀 启动 reasoning 服务: http://${HOST}:${PORT}"
echo "   Provider : ${LLM_ACTIVE_PROVIDER:-（未设置，使用内置默认值）}"
echo "   Config   : reasoning_config.yaml"
echo "   按 Ctrl+C 停止服务"
echo "─────────────────────────────────────────────────────────"

exec $PYTHON -m reasoning.main \
    --host "$HOST" \
    --port "$PORT" \
    "$@"
