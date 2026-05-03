#!/bin/bash

# 知识问答系统启动脚本
# 包含 Nginx + 前端 + 后端 + FirstLayer 问题分类服务

echo "========================================"
echo "  知识问答系统启动脚本"
echo "========================================"
echo ""

current_path=`dirname $(pwd)`

PYTHON=`which python`
PIP=`which pip`

#本机环境测试
#PYTHON='/Library/Frameworks/Python.framework/Versions/3.12/bin/python3'

echo '项目目录:' $current_path

bash "$current_path/scripts/stopAll.sh"

current_path=$current_path/src
echo '源代码:' $current_path

bash "$current_path/buildAll.sh"

# 获取本机 IP 地址（优先获取无线网卡 en0 的 IP）
echo "🔍 获取本机 IP 地址..."
# 优先获取 en0（无线网卡）的 IP
LOCAL_IP=$(ifconfig en0 | grep "inet " | awk '{print $2}' | head -1)
# 如果 en0 没有，尝试获取其他网卡
if [ -z "$LOCAL_IP" ] || [ "$LOCAL_IP" = "127.0.0.1" ]; then
    LOCAL_IP=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)
fi
# 如果还是没有，尝试用 ipconfig
if [ -z "$LOCAL_IP" ]; then
    LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "未知")
fi
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
    # 使用 Python 直接启动 app.py（解决相对导入问题）
    nohup $PYTHON app.py > "$current_path/logs/question_filter.log" 2>&1 &
    FILTER_PID=$!
    echo "   进程 PID: $FILTER_PID"
    # 等待服务完全启动
    echo "   ⏳ 等待服务启动..."
    MAX_RETRIES=20
    RETRY_COUNT=0
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        sleep 3
        FILTER_CHECK2=$(lsof -i:3005 2>/dev/null | grep LISTEN)
        if [ -n "$FILTER_CHECK2" ]; then
            echo "   ✅ Question Filter 已启动 (3005)"
            break
        fi
        RETRY_COUNT=$((RETRY_COUNT + 1))
        echo "   ⏳ 等待中... ($RETRY_COUNT/$MAX_RETRIES)"
    done

    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "   ❌ Question Filter 启动超时，请检查日志"
        echo "   💡 日志路径：$current_path/logs/question_filter.log"
    fi


fi

# 检查并启动 Category_classifier 问题分类服务
echo ""
echo "3️⃣ 检查 Category_classifier 问题分类服务状态..."
FIRSTLAYER_CHECK=$(lsof -i:3004 2>/dev/null | grep LISTEN)
if [ -n "$FIRSTLAYER_CHECK" ]; then
    echo "   ✅ Category_classifier 已运行 (3004)"
else
    echo "   🔄 启动 Category_classifier 服务..."
    cd "$current_path/backend/firstlayer/category_classifier"
    # 使用 Python 直接启动 app.py（解决相对导入问题）
    nohup $PYTHON app.py > "$current_path/logs/category_classifier.log" 2>&1 &
    FIRSTLAYER_PID=$!
    echo "   进程 PID: $FIRSTLAYER_PID"
    # 使用循环检测服务是否启动成功
    echo "   ⏳ 等待服务启动..."
    MAX_RETRIES=20
    RETRY_COUNT=0
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        sleep 3
        FIRSTLAYER_CHECK2=$(lsof -i:3004 2>/dev/null | grep LISTEN)
        if [ -n "$FIRSTLAYER_CHECK2" ]; then
            echo "   ✅ Category_classifier 已启动 (3004)"
            break
        fi
        RETRY_COUNT=$((RETRY_COUNT + 1))
        echo "   ⏳ 等待中... ($RETRY_COUNT/$MAX_RETRIES)"
    done
    
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "   ❌ Category_classifier 启动超时，请检查日志"
        echo "   💡 日志路径：$current_path/logs/Category_classifier.log"
    fi
fi

# 检查并启动 Context Memory 上下文记忆服务
echo ""
echo "4️⃣ 检查 Context Memory 上下文记忆服务状态..."
CONTEXT_CHECK=$(lsof -i:3006 2>/dev/null | grep LISTEN)
if [ -n "$CONTEXT_CHECK" ]; then
    echo "   ✅ Context Memory 已运行 (3006)"
else
    echo "   🔄 启动 Context Memory 服务..."
    cd "$current_path/backend/firstlayer/context_memory/src"
    # 使用 uvicorn 启动（解决相对导入问题）
    nohup $PYTHON -m uvicorn app:app --host 0.0.0.0 --port 3006 > "$current_path/logs/context_memory.log" 2>&1 &
    CONTEXT_PID=$!
    echo "   进程 PID: $CONTEXT_PID"
    # 使用循环检测服务是否启动成功
    echo "   ⏳ 等待服务启动..."
    MAX_RETRIES=20
    RETRY_COUNT=0
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        sleep 3
        CONTEXT_CHECK2=$(lsof -i:3006 2>/dev/null | grep LISTEN)
        if [ -n "$CONTEXT_CHECK2" ]; then
            echo "   ✅ Context Memory 已启动 (3006)"
            break
        fi
        RETRY_COUNT=$((RETRY_COUNT + 1))
        echo "   ⏳ 等待中... ($RETRY_COUNT/$MAX_RETRIES)"
    done
    
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "   ❌ Context Memory 启动超时，请检查日志"
        echo "   💡 日志路径：$current_path/logs/context_memory.log"
    fi
fi

# 检查并启动 Reasoning 推理服务
echo ""
echo "5️⃣ 检查 Reasoning 推理服务状态..."
REASON_CHECK=$(lsof -i:8001 2>/dev/null | grep LISTEN)
if [ -n "$REASON_CHECK" ]; then
    echo "   ✅ Reasoning 已运行 (8001)"
else
    echo "   🔄 启动 Reasoning 服务..."
    bash "$current_path/backend/reasoning/start.sh" --bg
fi

# 检查并启动 Ingestion 数据层服务（Layer 1）
echo ""
echo "6️⃣ 检查 Ingestion 数据层服务状态..."
INGEST_CHECK=$(lsof -i:3003 2>/dev/null | grep LISTEN)
if [ -n "$INGEST_CHECK" ]; then
    echo "   ✅ Ingestion 已运行 (3003)"
else
    echo "   🔄 启动 Ingestion 服务..."
    # ingestion/start.sh 内部用 conda run -n sqllineage 自激活，不依赖外部 conda activate
    # 也会自动 source src/.env + src/.env.aigw（含 AIGW_API_KEY）
    bash "$current_path/backend/ingestion/start.sh" --bg
fi

# 检查并启动后端
echo ""
echo "7️⃣ 检查后端服务状态..."
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
echo "8️⃣ 检查前端服务状态..."
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
echo "  ✅ 所有服务已启动完成！"
echo "========================================"
echo ""
echo "📊 服务状态:"
echo "  Nginx: $LOCAL_IP  端口 80 (代理)"
echo "  Question Filter : 问题过滤服务  端口 3005 (独立服务)"
echo "  Category_classifier : 问题分类服务  端口 3004 (独立服务)"
echo "  Context Memory: 上下文记忆服务  端口 3006 (独立服务)"
echo "  Reasoning: 推理服务  端口 8001 (Layer 3)"
echo "  Ingestion: 数据层服务  端口 3003 (Layer 1)"
echo "  后端：3002 (通过 Nginx 代理)"
echo "  前端：3000 (通过 Nginx 代理)"
echo ""
echo "🌐 访问地址:"
echo "  ───────────────────────────────────────"
echo "  🖥️  前端页面 (Nginx 代理 80 端口):"
echo "     本地：http://localhost"
echo "     局域网：http://$LOCAL_IP"
echo ""
echo "  🔧 API 接口 (Nginx 代理 80 端口):"
echo "     本地：http://localhost/api/*"
echo "     局域网：http://$LOCAL_IP/api/*"
echo ""
echo "  📊 FirstLayer 服务 (独立 3004 端口):"
echo "     本地：http://localhost:3004"
echo "     局域网：http://$LOCAL_IP:3004"
echo "     文档：http://localhost:3004/docs"
echo ""
echo "  💾 Context Memory 服务 (独立 3006 端口):"
echo "     本地：http://localhost:3006"
echo "     局域网：http://$LOCAL_IP:3006"
echo "     文档：http://localhost:3006/docs"
echo "  ───────────────────────────────────────"
echo ""
echo "  🧠 Reasoning 服务 (独立 8001 端口):"
echo "     本地：http://localhost:8001"
echo "     局域网：http://$LOCAL_IP:8001"
echo "  ───────────────────────────────────────"
echo ""
echo "📝 日志文件:"
echo "  Nginx:    /usr/local/nginx/logs/"
echo "  FirstLayer: ./logs/category_classifier.log"
echo "  Question Filter: ./logs/question_filter.log"
echo "  Context Memory: ./logs/context_memory.log"
echo "  Reasoning: ./logs/reasoning.log"
echo "  后端：    ./logs/backend.log"
echo "  前端：    ./logs/frontend.log"
echo ""
echo "💡 提示: 局域网内其他设备可通过 http://$LOCAL_IP 访问前端"
echo ""
