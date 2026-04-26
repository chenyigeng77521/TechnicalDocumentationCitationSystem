#!/bin/bash

# FirstLayer 问题分类服务启动脚本
# 位于 category_classifier 目录下

echo "========================================"
echo "  FirstLayer 问题分类服务"
echo "========================================"
echo ""

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "📁 项目根目录：$PROJECT_ROOT"
echo ""

# 检查 Python 版本
echo "🔍 检查 Python 环境..."
PYTHON_CMD="/usr/local/Homebrew/Cellar/python@3.12/3.12.13_1/bin/python3.12"

if [ ! -f "$PYTHON_CMD" ]; then
    echo "   ❌ 未找到 Python 3.12，请使用以下命令安装："
    echo "      brew install python@3.12"
    exit 1
fi

echo "   ✅ Python 版本：$($PYTHON_CMD --version)"
echo ""

# 检查端口是否被占用
echo "🔍 检查端口 3004..."
if lsof -i:3004 | grep -q LISTEN; then
    echo "   ⚠️  端口 3004 已被占用，请关闭其他服务或修改端口"
    lsof -i:3004
    read -p "   是否继续？(y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "   ✅ 端口 3004 可用"
echo ""

# 启动服务
echo "🚀 启动 FirstLayer 问题分类服务..."
echo ""

cd "$SCRIPT_DIR"
$PYTHON_CMD app.py

echo ""
echo "========================================"
echo "  服务已停止"
echo "========================================"
