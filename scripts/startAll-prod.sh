#!/bin/bash

# ===================================================================
# 知识问答系统 — 生产环境启动脚本
# ===================================================================
#
# 跟本地 startAll.sh 区别：
#   - 本地 startAll.sh    → ingestion 用 conda（团队成员开发用）
#   - 生产 startAll-prod.sh → ingestion 用本地 Python（部署到比赛服 / 生产共享环境用）
#
# 前置条件（生产部署前一次性配好）：
#   1. 已装 Python 3.12+：`python3 --version`
#   2. 已 pip install 各服务依赖（按需）：
#      python3 -m pip install -r src/backend/ingestion/requirements.txt
#      python3 -m pip install -r src/backend/firstlayer/question_filter/requirements.txt
#      python3 -m pip install -r src/backend/firstlayer/category_classifier/requirements.txt
#      python3 -m pip install -r src/backend/firstlayer/context_memory/requirements.txt
#   3. 配 src/.env.aigw 含 AIGW_API_KEY（参考 src/.env.aigw.example）
#   4. 已装 Nginx + Node.js（前端 / entrance 用）
#
# 用法：
#   ./startAll-prod.sh                       # 用 PATH 里的 python3
#   PYTHON_BIN=/usr/bin/python3.12 ./startAll-prod.sh   # 显式指定解释器
#
# ===================================================================

echo "========================================"
echo "  知识问答系统 — 生产模式启动脚本"
echo "========================================"
echo ""

current_path=`dirname $(pwd)`

# ---- Python 解释器：默认 PATH 里 python3，可用 PYTHON_BIN 覆盖 ----
PYTHON="${PYTHON_BIN:-$(which python3)}"
PIP=`which pip3`

if [ -z "$PYTHON" ] || ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "❌ 找不到 Python 解释器: $PYTHON"
    echo "   方案 1：安装 python3 到 PATH"
    echo "   方案 2：PYTHON_BIN=/path/to/python3.12 ./startAll-prod.sh"
    exit 1
fi

echo "🐍 Python 解释器: $PYTHON ($($PYTHON --version 2>&1))"
echo '项目目录:' $current_path

bash "$current_path/scripts/stopAll.sh"

current_path=$current_path/src
echo '源代码:' $current_path

bash "$current_path/buildAll.sh"

# 获取本机 IP 地址
echo "🔍 获取本机 IP 地址..."
LOCAL_IP=$(ifconfig en0 2>/dev/null | grep "inet " | awk '{print $2}' | head -1)
if [ -z "$LOCAL_IP" ] || [ "$LOCAL_IP" = "127.0.0.1" ]; then
    LOCAL_IP=$(ifconfig 2>/dev/null | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)
fi
[ -z "$LOCAL_IP" ] && LOCAL_IP="未知"
echo "   ✅ 本机 IP: $LOCAL_IP"
echo ""

# 检查并启动 Nginx
echo "1️⃣ 检查 Nginx 状态..."
if pgrep -x "nginx" > /dev/null; then
    echo "   ✅ Nginx 已运行"
else
    echo "   🔄 启动 Nginx..."
    /usr/local/nginx/sbin/nginx -c "$current_path/nginx.conf"
    sleep 1
    echo "   ✅ Nginx 已启动"
fi

# 检查并启动 Question Filter 问题过滤服务
echo ""
echo "2️⃣ 检查 Question Filter 问题过滤服务状态..."
FILTER_CHECK=$(lsof -i:3005 2>/dev/null | grep LISTEN)
if [ -n "$FILTER_CHECK" ]; then
    echo "   ✅ Question Filter 已运行 (3005)"
else
    echo "   🔄 启动 Question Filter 服务..."
    cd "$current_path/backend/firstlayer/question_filter"
    nohup "$PYTHON" app.py > "$current_path/logs/question_filter.log" 2>&1 &
    FILTER_PID=$!
    echo "   进程 PID: $FILTER_PID"
    echo "   ⏳ 等待服务启动..."
    MAX_RETRIES=20
    RETRY_COUNT=0
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        sleep 3
        if lsof -i:3005 2>/dev/null | grep -q LISTEN; then
            echo "   ✅ Question Filter 已启动 (3005)"
            break
        fi
        RETRY_COUNT=$((RETRY_COUNT + 1))
        echo "   ⏳ 等待中... ($RETRY_COUNT/$MAX_RETRIES)"
    done
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "   ❌ Question Filter 启动超时，请检查日志：$current_path/logs/question_filter.log"
    fi
fi

# 检查并启动 Category_classifier 问题分类服务
echo ""
echo "3️⃣ 检查 Category_classifier 问题分类服务状态..."
if lsof -i:3004 2>/dev/null | grep -q LISTEN; then
    echo "   ✅ Category_classifier 已运行 (3004)"
else
    echo "   🔄 启动 Category_classifier 服务..."
    cd "$current_path/backend/firstlayer/category_classifier"
    nohup "$PYTHON" app.py > "$current_path/logs/category_classifier.log" 2>&1 &
    FIRSTLAYER_PID=$!
    echo "   进程 PID: $FIRSTLAYER_PID"
    echo "   ⏳ 等待服务启动..."
    MAX_RETRIES=20
    RETRY_COUNT=0
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        sleep 3
        if lsof -i:3004 2>/dev/null | grep -q LISTEN; then
            echo "   ✅ Category_classifier 已启动 (3004)"
            break
        fi
        RETRY_COUNT=$((RETRY_COUNT + 1))
        echo "   ⏳ 等待中... ($RETRY_COUNT/$MAX_RETRIES)"
    done
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "   ❌ Category_classifier 启动超时，请检查日志：$current_path/logs/category_classifier.log"
    fi
fi

# 检查并启动 Context Memory 上下文记忆服务
echo ""
echo "4️⃣ 检查 Context Memory 上下文记忆服务状态..."
if lsof -i:3006 2>/dev/null | grep -q LISTEN; then
    echo "   ✅ Context Memory 已运行 (3006)"
else
    echo "   🔄 启动 Context Memory 服务..."
    cd "$current_path/backend/firstlayer/context_memory/src"
    nohup "$PYTHON" -m uvicorn app:app --host 0.0.0.0 --port 3006 > "$current_path/logs/context_memory.log" 2>&1 &
    CONTEXT_PID=$!
    echo "   进程 PID: $CONTEXT_PID"
    echo "   ⏳ 等待服务启动..."
    MAX_RETRIES=20
    RETRY_COUNT=0
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        sleep 3
        if lsof -i:3006 2>/dev/null | grep -q LISTEN; then
            echo "   ✅ Context Memory 已启动 (3006)"
            break
        fi
        RETRY_COUNT=$((RETRY_COUNT + 1))
        echo "   ⏳ 等待中... ($RETRY_COUNT/$MAX_RETRIES)"
    done
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "   ❌ Context Memory 启动超时，请检查日志：$current_path/logs/context_memory.log"
    fi
fi

# 检查并启动 Ingestion 数据层服务（Layer 1）
echo ""
echo "5️⃣ 检查 Ingestion 数据层服务状态..."
if lsof -i:3003 2>/dev/null | grep -q LISTEN; then
    echo "   ✅ Ingestion 已运行 (3003)"
else
    echo "   🔄 启动 Ingestion 服务（生产模式：用本地 Python）..."
    # ingestion/start-prod.sh 用本地 Python（PYTHON_BIN 同步透传），自动 source src/.env + src/.env.aigw
    PYTHON_BIN="$PYTHON" bash "$current_path/backend/ingestion/start-prod.sh" --bg
fi

# 检查并启动后端
echo ""
echo "6️⃣ 检查后端服务状态..."
if lsof -i:3002 | grep -q LISTEN; then
    echo "   ✅ 后端已运行 (3002)"
else
    echo "   🔄 启动后端服务..."
    cd "$current_path/backend/entrance"
    npm start > "$current_path/logs/backend.log" 2>&1 &
    sleep 3
    echo "   ✅ 后端已启动 (3002)"
fi

# 检查并启动前端
echo ""
echo "7️⃣ 检查前端服务状态..."
if lsof -i:3000 | grep -q LISTEN; then
    echo "   ✅ 前端已运行 (3000)"
else
    echo "   🔄 启动前端服务..."
    cd "$current_path/frontend"
    npm start > "$current_path/logs/frontend.log" 2>&1 &
    sleep 5
    echo "   ✅ 前端已启动 (3000)"
fi

echo ""
echo "========================================"
echo "  ✅ 所有服务已启动完成（生产模式）！"
echo "========================================"
echo ""
echo "📊 服务状态:"
echo "  Nginx: $LOCAL_IP  端口 80 (代理)"
echo "  Question Filter : 端口 3005"
echo "  Category_classifier : 端口 3004"
echo "  Context Memory: 端口 3006"
echo "  Ingestion: 端口 3003 (Layer 1，生产模式 PYTHON=$PYTHON)"
echo "  后端：3002 (通过 Nginx 代理)"
echo "  前端：3000 (通过 Nginx 代理)"
echo ""
echo "🌐 访问: http://localhost  |  http://$LOCAL_IP"
echo ""
echo "💡 注意: reasoning (8001) 不在 startAll 范围，由海军 team 单独启动"
