#!/bin/bash

# backend/LLM/wiki/query/stop.sh
# 停止 knowledge_api.py

echo "========================================"
echo "  停止知识库查询服务"
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

echo ""
echo "========================================"
echo "  ✅ 知识库查询服务已停止"
echo "========================================"
echo ""
echo "📊 最终状态:"
echo "  知识库查询：$(lsof -i:18020 2>/dev/null | grep -q LISTEN && echo '✅ 运行中' || echo '❌ 已停止')"
echo ""
