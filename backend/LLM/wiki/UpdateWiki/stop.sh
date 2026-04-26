#!/bin/bash

# backend/LLM/wiki/UpdateWiki/stop.sh
# 停止 update_wiki.py

echo "========================================"
echo "  停止 Wiki 更新服务"
echo "========================================"
echo ""

# 停止 Wiki 更新服务 (端口 18010)
echo "🛑 停止 Wiki 更新服务 (18010)..."
WIKI_PID=$(lsof -ti:18010 2>/dev/null)
if [ -n "$WIKI_PID" ]; then
    kill -9 $WIKI_PID 2>/dev/null
    sleep 1
    echo "   ✅ Wiki 更新服务已停止 (PID: $WIKI_PID)"
else
    echo "   ⚠️  Wiki 更新服务未运行"
fi

echo ""
echo "📊 最终状态:"
echo "  Wiki 更新：$(lsof -i:18010 2>/dev/null | grep -q LISTEN && echo '✅ 运行中' || echo '❌ 已停止')"
echo ""
