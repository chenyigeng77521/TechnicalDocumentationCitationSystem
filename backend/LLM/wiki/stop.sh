#!/bin/bash

# backend/LLM/wiki/stop.sh
# 停止 knowledge_api.py 和 update_wiki.py

echo "========================================"
echo "  停止知识库相关服务"
echo "========================================"
echo ""

# 停止知识库查询服务 (端口 18020)
echo "1️⃣ 停止知识库查询服务 (18020)..."
KNOWLEDGE_PID=$(lsof -ti:18020 2>/dev/null)
if [ -n "$KNOWLEDGE_PID" ]; then
    kill -9 $KNOWLEDGE_PID 2>/dev/null
    sleep 1
    echo "   ✅ 知识库查询服务已停止 (PID: $KNOWLEDGE_PID)"
else
    echo "   ⚠️  知识库查询服务未运行"
fi

# 停止 Wiki 更新服务 (端口 18010)
echo ""
echo "2️⃣ 停止 Wiki 更新服务 (18010)..."
WIKI_PID=$(lsof -ti:18010 2>/dev/null)
if [ -n "$WIKI_PID" ]; then
    kill -9 $WIKI_PID 2>/dev/null
    sleep 1
    echo "   ✅ Wiki 更新服务已停止 (PID: $WIKI_PID)"
else
    echo "   ⚠️  Wiki 更新服务未运行"
fi

echo ""
echo "========================================"
echo "  ✅ 知识库相关服务已停止"
echo "========================================"
echo ""
echo "📊 最终状态:"
echo "  知识库查询：$(lsof -i:18020 2>/dev/null | grep -q LISTEN && echo '✅ 运行中' || echo '❌ 已停止')"
echo "  Wiki 更新：$(lsof -i:18010 2>/dev/null | grep -q LISTEN && echo '✅ 运行中' || echo '❌ 已停止')"
echo ""
