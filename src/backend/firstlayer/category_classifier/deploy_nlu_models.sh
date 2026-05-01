#!/bin/bash
# NLU 模型一键部署脚本
# 用法：./deploy_nlu_models.sh

set -e

echo "=========================================="
echo "🚀 NLU 模型一键部署"
echo "=========================================="

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$(dirname "$(dirname "$SCRIPT_DIR")")")"

echo ""
echo "📁 项目目录：$PROJECT_ROOT"
echo ""

# 1. 安装依赖
echo "=========================================="
echo "1️⃣  安装 Python 依赖"
echo "=========================================="

cd "$PROJECT_ROOT/backend/firstlayer/category_classifier"

if ! python3 -c "import huggingface_hub" 2>/dev/null; then
    echo "📦 安装 huggingface_hub..."
    pip3 install huggingface_hub>=0.20.0 -q
else
    echo "✅ huggingface_hub 已安装"
fi

if ! python3 -c "import transformers" 2>/dev/null; then
    echo "📦 安装 transformers..."
    pip3 install transformers>=4.36.0 -q
else
    echo "✅ transformers 已安装"
fi

if ! python3 -c "import torch" 2>/dev/null; then
    echo "📦 安装 torch..."
    pip3 install torch>=2.2.0 -q
else
    echo "✅ torch 已安装"
fi

echo ""

# 2. 下载模型
echo "=========================================="
echo "2️⃣  下载 NLU 模型"
echo "=========================================="

python3 "$SCRIPT_DIR/download_models.py"

echo ""

# 3. 验证模型
echo "=========================================="
echo "3️⃣  验证模型文件"
echo "=========================================="

MODELS_DIR="$PROJECT_ROOT/backend/models"

if [ -d "$MODELS_DIR/qwen2.5-0.5b" ]; then
    echo "✅ Qwen2.5-0.5B 模型存在"
    ls -lh "$MODELS_DIR/qwen2.5-0.5b" | head -5
else
    echo "❌ Qwen2.5-0.5B 模型不存在"
    exit 1
fi

if [ -d "$MODELS_DIR/chinese-roberta-wwm-ext" ]; then
    echo "✅ chinese-roberta-wwm-ext 模型存在"
    ls -lh "$MODELS_DIR/chinese-roberta-wwm-ext" | head -5
else
    echo "❌ chinese-roberta-wwm-ext 模型不存在"
    exit 1
fi

echo ""
echo "=========================================="
echo "✅ NLU 模型部署完成！"
echo "=========================================="
echo ""
echo "📊 模型信息:"
echo "  • Qwen2.5-0.5B: $MODELS_DIR/qwen2.5-0.5b"
echo "  • chinese-roberta-wwm-ext: $MODELS_DIR/chinese-roberta-wwm-ext"
echo ""
echo "💡 下一步:"
echo "  1. 启动服务：./startAll.sh"
echo "  2. 查看日志：tail -f ./logs/backend.log | grep -E 'Qwen|完整性检查'"
echo ""
