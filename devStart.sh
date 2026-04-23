#!/bin/bash

# 知识问答系统启动脚本
# 包含 Nginx + 前端 + 后端

echo "========================================"
echo "  知识问答系统启动脚本"
echo "========================================"
echo ""


# 检查并启动后端
echo ""
echo "1️⃣ 检查后端服务状态..."
if lsof -i:3002 | grep -q LISTEN; then
    echo "   ✅ 后端已运行 (3002)"
else
    echo "   🔄 启动后端服务..."
    cd "./backend"
    npx tsx src/server.ts > ../logs/backend.log 2>&1 &
    sleep 3
    echo "   ✅ 后端已启动 (3002)"
fi

# 检查并启动前端
echo ""
echo "2️⃣ 检查前端服务状态..."
if lsof -i:3000 | grep -q LISTEN; then
    echo "   ✅ 前端已运行 (3000)"
else
    echo "   🔄 启动前端服务..."
    cd "./frontend"
    npm run dev > ../logs/frontend.log 2>&1 &
    sleep 5
    echo "   ✅ 前端已启动 (3000)"
fi

echo ""
echo "========================================"
echo "  ✅ 所有服务已启动完成！"
echo "========================================"
echo ""
echo "🔧 直接访问:"
echo "  前端：    http://localhost:3000"
echo "  后端 API: http://localhost:3002"
echo ""
