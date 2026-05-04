#!/usr/bin/env bash
# 一键初始化脚本：team 成员 clone 项目后跑这个就能配齐 ingestion 模块
#
# 做的事：
#   1. 检查 Python 3.12+
#   2. 创建 venv（默认 .venv-ingestion/）+ pip install requirements
#   3. 检查 src/.env.aigw 是否就绪（缺则提示 + 退出）
#   4. 跑 reindex_all --from-fs，重建 DB（src/backend/database/knowledge.db）
#   5. 输出最终验证：documents/chunks 数 + 启动命令
#
# 用法：
#   bash scripts/init.sh                # 默认：用 AIGW embedding（需要 VPN + AIGW key）
#   bash scripts/init.sh --local        # 用本地 SentenceTransformer（首次拉 ~2GB bge-m3 模型）
#   bash scripts/init.sh --no-venv      # 跳过 venv，直接用当前 python（自己装好依赖）
#   bash scripts/init.sh --skip-install # 跳过 pip install（依赖已装）
#   bash scripts/init.sh --skip-reindex # 跳过 reindex（DB 已就绪）

set -e

# ---- 解析参数 ----
USE_LOCAL_EMBEDDING=0
SKIP_VENV=0
SKIP_INSTALL=0
SKIP_REINDEX=0
for arg in "$@"; do
    case "$arg" in
        --local) USE_LOCAL_EMBEDDING=1 ;;
        --no-venv) SKIP_VENV=1 ;;
        --skip-install) SKIP_INSTALL=1 ;;
        --skip-reindex) SKIP_REINDEX=1 ;;
        -h|--help)
            head -20 "$0" | tail -19
            exit 0
            ;;
        *) echo "未知参数: $arg"; exit 1 ;;
    esac
done

# ---- 路径 ----
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv-ingestion"
REQUIREMENTS="$PROJECT_ROOT/src/backend/ingestion/requirements.txt"
ENV_AIGW="$PROJECT_ROOT/src/.env.aigw"
ENV_AIGW_EXAMPLE="$PROJECT_ROOT/src/.env.aigw.example"
DB_PATH="$PROJECT_ROOT/src/backend/database/knowledge.db"
DOCS_DIR="$PROJECT_ROOT/data/docs"

cd "$PROJECT_ROOT"

echo "════════════════════════════════════════════════════════"
echo "  Ingestion 一键初始化"
echo "════════════════════════════════════════════════════════"
echo "  项目根: $PROJECT_ROOT"
echo "  Embedding: $([ "$USE_LOCAL_EMBEDDING" = 1 ] && echo "本地 SentenceTransformer" || echo "AIGW (远程)")"
echo

# ---- Step 1: Python 检查 ----
echo "━━━ Step 1/5: 检查 Python ━━━"
PYTHON_BIN=$(command -v python3.12 || command -v python3 || true)
if [ -z "$PYTHON_BIN" ]; then
    echo "❌ 找不到 python3.12 / python3。请先装 Python 3.12+"
    exit 1
fi
PY_VERSION=$("$PYTHON_BIN" --version 2>&1)
echo "  ✅ $PYTHON_BIN ($PY_VERSION)"
echo

# ---- Step 2: venv + pip install ----
echo "━━━ Step 2/5: 装依赖 ━━━"
if [ "$SKIP_VENV" = 0 ]; then
    if [ ! -d "$VENV_DIR" ]; then
        echo "  创建 venv: $VENV_DIR"
        "$PYTHON_BIN" -m venv "$VENV_DIR"
    else
        echo "  venv 已存在: $VENV_DIR"
    fi
    PYTHON_BIN="$VENV_DIR/bin/python"
    PIP_BIN="$VENV_DIR/bin/pip"
else
    echo "  --no-venv 跳过 venv，用当前 $PYTHON_BIN"
    PIP_BIN="$PYTHON_BIN -m pip"
fi

if [ "$SKIP_INSTALL" = 0 ]; then
    echo "  pip install -r $REQUIREMENTS（可能需要 1-3 分钟）..."
    $PIP_BIN install --quiet --upgrade pip
    $PIP_BIN install --quiet -r "$REQUIREMENTS"
    echo "  ✅ 依赖装好"
else
    echo "  --skip-install 跳过"
fi
echo

# ---- Step 3: 检查 AIGW key（如果用 AIGW 模式）----
echo "━━━ Step 3/5: 检查 AIGW 配置 ━━━"
if [ "$USE_LOCAL_EMBEDDING" = 1 ]; then
    echo "  --local 模式，不需要 AIGW key（用本地 SentenceTransformer）"
else
    if [ ! -f "$ENV_AIGW" ]; then
        echo "❌ $ENV_AIGW 不存在"
        echo "   方案 1：cp $ENV_AIGW_EXAMPLE $ENV_AIGW，编辑填 AIGW_API_KEY"
        echo "   方案 2：用本地 embedding 重新跑：bash scripts/init.sh --local"
        exit 1
    fi
    if ! grep -q "^AIGW_API_KEY=sk-" "$ENV_AIGW" 2>/dev/null; then
        echo "❌ $ENV_AIGW 里 AIGW_API_KEY 没填或格式不对"
        echo "   编辑 $ENV_AIGW，填 AIGW_API_KEY=sk-xxx"
        exit 1
    fi
    echo "  ✅ AIGW_API_KEY 已配"
fi
echo

# ---- Step 4: 检查 data/docs/ ----
echo "━━━ Step 4/5: 检查源文档 ━━━"
if [ ! -d "$DOCS_DIR" ]; then
    echo "❌ $DOCS_DIR 不存在"
    echo "   data/docs/ 是 git tracked 的源文档目录，clone 时应该自动有"
    exit 1
fi
DOC_COUNT=$(find "$DOCS_DIR" -type f \( -name "*.md" -o -name "*.adoc" \) | wc -l | tr -d ' ')
echo "  ✅ $DOC_COUNT 个 .md/.adoc 文件 in $DOCS_DIR"
echo

# ---- Step 5: 重建 DB ----
echo "━━━ Step 5/5: 重建 DB（reindex_all --from-fs）━━━"
if [ "$SKIP_REINDEX" = 0 ]; then
    if [ -f "$DB_PATH" ]; then
        EXISTING_SIZE=$(du -h "$DB_PATH" | cut -f1)
        echo "  ⚠️  DB 已存在: $DB_PATH ($EXISTING_SIZE)"
        echo "     reindex_all 会清空重建（约 7-10 分钟，请耐心等）"
        echo "     按 Ctrl+C 取消，或回车继续..."
        read -r
    fi
    cd "$PROJECT_ROOT/src"
    if [ "$USE_LOCAL_EMBEDDING" = 1 ]; then
        echo "  EMBEDDING_USE_LOCAL=1 模式，首次会拉 ~2GB bge-m3 模型..."
        EMBEDDING_USE_LOCAL=1 "$PYTHON_BIN" -m backend.ingestion.scripts.reindex_all --from-fs
    else
        # source .env.aigw 让 AIGW_API_KEY 进环境
        set -a
        # shellcheck disable=SC1090
        source "$ENV_AIGW"
        set +a
        "$PYTHON_BIN" -m backend.ingestion.scripts.reindex_all --from-fs
    fi
    cd "$PROJECT_ROOT"
else
    echo "  --skip-reindex 跳过"
fi
echo

# ---- 最终验证 ----
echo "════════════════════════════════════════════════════════"
echo "  ✅ 初始化完成"
echo "════════════════════════════════════════════════════════"
if [ -f "$DB_PATH" ]; then
    DB_SIZE=$(du -h "$DB_PATH" | cut -f1)
    DOC_NUM=$("$PYTHON_BIN" -c "import sqlite3; print(sqlite3.connect('$DB_PATH').execute('SELECT count(*) FROM documents').fetchone()[0])" 2>/dev/null || echo "?")
    CHUNK_NUM=$("$PYTHON_BIN" -c "import sqlite3; print(sqlite3.connect('$DB_PATH').execute('SELECT count(*) FROM chunks').fetchone()[0])" 2>/dev/null || echo "?")
    echo "  DB: $DB_PATH ($DB_SIZE)"
    echo "  documents: $DOC_NUM, chunks: $CHUNK_NUM"
fi
echo
echo "📌 下一步启动 ingestion 服务："
if [ "$SKIP_VENV" = 0 ]; then
    echo "  PYTHON_BIN=$PYTHON_BIN bash src/backend/ingestion/start.sh"
    echo "  # 或 source $VENV_DIR/bin/activate 激活后跑 bash src/backend/ingestion/start.sh"
else
    echo "  bash src/backend/ingestion/start.sh"
fi
echo
echo "📌 全栈启动（含 entrance / 前端 / firstlayer 等）："
echo "  bash scripts/startAll.sh"
