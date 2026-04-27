#!/bin/bash

# 知识问答系统停止脚本
# 停止 Nginx + 前端 + 后端 + FirstLayer + Question Filter 服务

echo "========================================"
echo "  知识问答系统停止脚本"
echo "========================================"
echo ""

# 停止 Question Filter 问题过滤服务
echo "1️⃣ 停止 Question Filter 问题过滤服务 (3005)..."
FILTER_PID=$(lsof -ti:3005 2>/dev/null)
if [ -n "$FILTER_PID" ]; then
    kill -9 $FILTER_PID 2>/dev/null
    sleep 1
    echo "   ✅ Question Filter 已停止 (PID: $FILTER_PID)"
else
    echo "   ⚠️  Question Filter 未运行"
fi

# 停止 category_classifier 问题分类服务
echo ""
echo "2️⃣ 停止 category_classifier 问题分类服务 (3004)..."
FIRSTLAYER_PID=$(lsof -ti:3004 2>/dev/null)
if [ -n "$FIRSTLAYER_PID" ]; then
    kill -9 $FIRSTLAYER_PID 2>/dev/null
    sleep 1
    echo "   ✅ category_classifier 已停止 (PID: $FIRSTLAYER_PID)"
else
    echo "   ⚠️  category_classifier  未运行"
fi

# 停止前端
echo ""
echo "3️⃣ 停止前端服务 (3000)..."
FRONTEND_PID=$(lsof -ti:3000 2>/dev/null)
if [ -n "$FRONTEND_PID" ]; then
    kill -9 $FRONTEND_PID 2>/dev/null
    sleep 1
    echo "   ✅ 前端已停止 (PID: $FRONTEND_PID)"
else
    echo "   ⚠️  前端未运行"
fi

# 停止后端
echo ""
echo "4️⃣ 停止后端服务 (3002)..."
BACKEND_PID=$(lsof -ti:3002 2>/dev/null)
if [ -n "$BACKEND_PID" ]; then
    kill -9 $BACKEND_PID 2>/dev/null
    sleep 1
    echo "   ✅ 后端已停止 (PID: $BACKEND_PID)"
else
    echo "   ⚠️  后端未运行"
fi

# 停止 Nginx
echo ""
echo "5️⃣ 停止 Nginx..."
NGINX_PID=$(pgrep -x "nginx" 2>/dev/null)
if [ -n "$NGINX_PID" ]; then
    /usr/local/nginx/sbin/nginx -s stop 2>/dev/null
    sleep 1
    echo "   ✅ Nginx 已停止 (PID: $NGINX_PID)"
else
    echo "   ⚠️  Nginx 未运行"
fi

echo ""
echo "========================================"
echo "  ✅ 所有服务已停止"
echo "========================================"
echo ""
echo "📊 最终状态:"
echo "  Question Filter: $(lsof -i:3005 2>/dev/null | grep -q LISTEN && echo '❌ 运行中' || echo '✅ 已停止')"
echo "  Category_classifier: $(lsof -i:3004 2>/dev/null | grep -q LISTEN && echo '❌ 运行中' || echo '✅ 已停止')"
echo "  后端：$(lsof -i:3002 2>/dev/null | grep -q LISTEN && echo '❌ 运行中' || echo '✅ 已停止')"
echo "  前端：$(lsof -i:3000 2>/dev/null | grep -q LISTEN && echo '❌ 运行中' || echo '✅ 已停止')"
echo ""
