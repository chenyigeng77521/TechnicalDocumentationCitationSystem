#!/bin/bash

# 知识问答系统 - 全量编译脚本
# 编译 frontend 和 backend/entrance 两个项目

echo "========================================"
echo "  知识问答系统 - 全量编译"
echo "========================================"
echo ""

# 获取脚本所在目录（项目根目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "📁 项目根目录：$SCRIPT_DIR"
echo ""

# 检查 Node.js 版本
echo "🔍 检查 Node.js 环境..."
if command -v node &> /dev/null; then
    NODE_VERSION=$(node -v)
    echo "   ✅ Node.js 版本：$NODE_VERSION"
else
    echo "   ❌ 错误：未找到 Node.js，请先安装 Node.js"
    exit 1
fi

# 检查 npm
if command -v npm &> /dev/null; then
    NPM_VERSION=$(npm -v)
    echo "   ✅ npm 版本：$NPM_VERSION"
else
    echo "   ❌ 错误：未找到 npm，请先安装 npm"
    exit 1
fi
echo ""

# 编译后端
echo "========================================"
echo "  1️⃣ 编译后端 (backend/entrance)"
echo "========================================"
cd "$SCRIPT_DIR/backend/entrance"

npm install

if [ ! -d "node_modules" ]; then
    echo "   📦 后端依赖未安装，先安装依赖..."
    npm install
    if [ $? -ne 0 ]; then
        echo "   ❌ 后端依赖安装失败"
        exit 1
    fi
else
    echo "   ✅ 后端依赖已安装"
fi

echo "   🔨 开始编译后端 TypeScript..."
npm run build
if [ $? -ne 0 ]; then
    echo "   ❌ 后端编译失败"
    exit 1
fi
echo "   ✅ 后端编译完成"
echo ""

# 编译前端
echo "========================================"
echo "  2️⃣ 编译前端 (frontend)"
echo "========================================"
cd "$SCRIPT_DIR/frontend"

npm install
if [ ! -d "node_modules" ]; then
    echo "   📦 前端依赖未安装，先安装依赖..."
    npm install
    if [ $? -ne 0 ]; then
        echo "   ❌ 前端依赖安装失败"
        exit 1
    fi
else
    echo "   ✅ 前端依赖已安装"
fi

echo "   🔨 开始编译前端 Next.js..."
npm run build
if [ $? -ne 0 ]; then
    echo "   ❌ 前端编译失败"
    exit 1
fi
echo "   ✅ 前端编译完成"
echo ""

# 编译完成
echo "========================================"
echo "  ✅ 全量编译完成！"
echo "========================================"
echo ""
echo "📊 编译结果:"
echo "   后端：backend/entrance/dist/"
echo "   前端：frontend/.next/"
echo ""
echo "🚀 启动服务:"
echo "   方式 1: 使用一键启动脚本"
echo "      ./start_all.sh"
echo ""
echo "   方式 2: 手动启动"
echo "      # 启动后端"
echo "      cd backend/entrance && npm start"
echo ""
echo "      # 启动前端（新窗口）"
echo "      cd frontend && npm start"
echo ""
