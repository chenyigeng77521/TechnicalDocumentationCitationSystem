#!/bin/bash

# 知识问答系统停止脚本
# 停止 Nginx + 前端 + 后端 + Ingestion + FirstLayer + Question Filter 服务

# 算路径（脚本在 scripts/，..=项目根，加 src）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_ROOT="$PROJECT_ROOT/src"

echo $SRC_ROOT

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

# 停止 Context Memory 上下文记忆服务
echo ""
echo "5️⃣ 停止 Context Memory 上下文记忆服务 (3006)..."
CONTEXT_PID=$(lsof -ti:3006 2>/dev/null)
if [ -n "$CONTEXT_PID" ]; then
    kill -9 $CONTEXT_PID 2>/dev/null
    sleep 1
    echo "   ✅ Context Memory 已停止 (PID: $CONTEXT_PID)"
else
    echo "   ⚠️  Context Memory 未运行"
fi

# 停止 Ingestion 数据层服务（用脚本自带 stop.sh，处理 wrapper + python child 双进程）
echo ""
echo "6️⃣ 停止 Reasoning 推理服务 (8001)..."
REASON_PID=$(lsof -ti:8001 2>/dev/null)
if [ -n "$REASON_PID" ]; then
    cd "$SRC_ROOT/backend/reasoning"
    ./stop.sh
    sleep 1
    echo "   ✅ Reasoning 已停止"
else
    echo "   ⚠️  Reasoning 未运行"
fi

# 停止 Ingestion 数据层服务（用脚本自带 stop.sh，处理 wrapper + python child 双进程）
echo ""
echo "7️⃣ 停止 Ingestion 数据层服务 (3003)..."
INGEST_PID=$(lsof -ti:3003 2>/dev/null)
if [ -n "$INGEST_PID" ]; then
    bash "$SRC_ROOT/backend/ingestion/stop.sh" 2>/dev/null || kill -9 $INGEST_PID 2>/dev/null
    sleep 1
    echo "   ✅ Ingestion 已停止"
else
    echo "   ⚠️  Ingestion 未运行"
fi

# 停止 Nginx
echo ""
echo "8️⃣ 停止 Nginx..."
NGINX=`which nginx`
NGINX_PID=$(pgrep -x "nginx" 2>/dev/null)
if [ -n "$NGINX_PID" ]; then
    $NGINX -s stop 2>/dev/null
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
echo "  Context Memory: $(lsof -i:3006 2>/dev/null | grep -q LISTEN && echo '❌ 运行中' || echo '✅ 已停止')"
echo "  Reasoning: $(lsof -i:8001 2>/dev/null | grep -q LISTEN && echo '❌ 运行中' || echo '✅ 已停止')"
echo "  Ingestion: $(lsof -i:3003 2>/dev/null | grep -q LISTEN && echo '❌ 运行中' || echo '✅ 已停止')"
echo "  后端：$(lsof -i:3002 2>/dev/null | grep -q LISTEN && echo '❌ 运行中' || echo '✅ 已停止')"
echo "  前端：$(lsof -i:3000 2>/dev/null | grep -q LISTEN && echo '❌ 运行中' || echo '✅ 已停止')"
echo ""
