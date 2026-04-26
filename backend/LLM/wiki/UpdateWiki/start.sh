#!/bin/bash

# backend/LLM/wiki/UpdateWiki/start.sh
# 启动 update_wiki.py

echo "========================================"
echo "  启动 Wiki 更新服务"
echo "========================================"
echo ""

current_path=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$current_path/../../../../" && pwd)
LOGS_DIR="$PROJECT_ROOT/logs"

# 确保日志目录存在
mkdir -p "$LOGS_DIR"

# 启动 Wiki 更新服务 (update_wiki.py, 端口 18010)
echo "🔄 启动 Wiki 更新服务 (18010)..."
if lsof -i:18010 2>/dev/null | grep -q LISTEN; then
    echo "   ✅ Wiki 更新服务已运行"
else
    cd "$current_path"
    nohup python3 update_wiki.py --serve --port 18010 > "$LOGS_DIR/update_wiki.log" 2>&1 &
    sleep 3
    if lsof -i:18010 2>/dev/null | grep -q LISTEN; then
        echo "   ✅ Wiki 更新服务已启动"
    else
        echo "   ❌ Wiki 更新服务启动失败，请检查日志: $LOGS_DIR/update_wiki.log"
    fi
fi

echo ""
echo "📊 服务状态:"
echo "  Wiki 更新：$(lsof -i:18010 2>/dev/null | grep -q LISTEN && echo '✅ 运行中' || echo '❌ 未启动')  端口 18010"
echo ""
echo "🌐 访问地址: http://localhost:18010/docs"
echo "📝 日志文件: $LOGS_DIR/update_wiki.log"
echo ""
