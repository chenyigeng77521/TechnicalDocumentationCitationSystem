#!/bin/bash

# backend/LLM/wiki/start.sh
# 启动 knowledge_api.py 和 update_wiki.py

echo "========================================"
echo "  启动知识库相关服务"
echo "========================================"
echo ""

current_path=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$current_path/../../.." && pwd)
LOGS_DIR="$PROJECT_ROOT/logs"

# 确保日志目录存在
mkdir -p "$LOGS_DIR"

# 启动知识库查询服务 (knowledge_api.py, 端口 18020)
echo "1️⃣ 启动知识库查询服务 (18020)..."
if lsof -i:18020 2>/dev/null | grep -q LISTEN; then
    echo "   ✅ 知识库查询服务已运行"
else
    cd "$current_path"
    nohup python3 knowledge_api.py > "$LOGS_DIR/knowledge_api.log" 2>&1 &
    sleep 3
    if lsof -i:18020 2>/dev/null | grep -q LISTEN; then
        echo "   ✅ 知识库查询服务已启动"
    else
        echo "   ❌ 知识库查询服务启动失败，请检查日志: $LOGS_DIR/knowledge_api.log"
    fi
fi


echo ""
echo "========================================"
echo "  ✅ 知识库相关服务启动完成"
echo "========================================"
echo ""
echo "📊 服务状态:"
echo "  知识库查询：$(lsof -i:18020 2>/dev/null | grep -q LISTEN && echo '✅ 运行中' || echo '❌ 未启动')  端口 18020"
echo ""
echo "🌐 访问地址:"
echo "  知识库查询: http://localhost:18020/docs"
echo ""
echo "📝 日志文件:"
echo "  知识库查询: $LOGS_DIR/knowledge_api.log"
echo ""
