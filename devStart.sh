#!/bin/bash

# 知识问答系统启动脚本
# 包含 Nginx + 前端 + 后端 + FirstLayer 问题分类服务

./stopAll.sh
echo "========================================"
echo "  知识问答系统启动脚本"
echo "========================================"
echo ""

current_path=$(pwd)
echo $current_path

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
    /usr/local/nginx/sbin/nginx
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
    nohup /usr/local/Homebrew/Cellar/python@3.12/3.12.13_1/bin/python3.12 app.py > "$current_path/logs/question_filter.log" 2>&1 &
    FILTER_PID=$!
    echo "   进程 PID: $FILTER_PID"
    # 等待服务完全启动
    echo "   ⏳ 等待服务启动..."
    sleep 10
    FILTER_CHECK2=$(lsof -i:3005 2>/dev/null | grep LISTEN)
    if [ -n "$FILTER_CHECK2" ]; then
        echo "   ✅ Question Filter 已启动 (3005)"
    else
        echo "   ❌ Question Filter 启动失败，请检查日志"
        echo "   💡 日志路径：$current_path/logs/question_filter.log"
    fi
fi

# 检查并启动 FirstLayer 问题分类服务
echo ""
echo "3️⃣ 检查 FirstLayer 问题分类服务状态..."
FIRSTLAYER_CHECK=$(lsof -i:3004 2>/dev/null | grep LISTEN)
if [ -n "$FIRSTLAYER_CHECK" ]; then
    echo "   ✅ FirstLayer 已运行 (3004)"
else
    echo "   🔄 启动 FirstLayer 服务..."
    cd "$current_path/backend/firstlayer/category_classifier"
    # 使用 Python 直接启动 app.py（解决相对导入问题）
    nohup /usr/local/Homebrew/Cellar/python@3.12/3.12.13_1/bin/python3.12 app.py > "$current_path/logs/category_classifier.log" 2>&1 &
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
            echo "   ✅ FirstLayer 已启动 (3004)"
            break
        fi
        RETRY_COUNT=$((RETRY_COUNT + 1))
        echo "   ⏳ 等待中... ($RETRY_COUNT/$MAX_RETRIES)"
    done
    
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "   ❌ FirstLayer 启动超时，请检查日志"
        echo "   💡 日志路径：$current_path/logs/firstlayer.log"
    fi
fi

# 检查并启动后端
echo ""
echo "4️⃣ 检查后端服务状态..."
if lsof -i:3002 | grep -q LISTEN; then
    echo "   ✅ 后端已运行 (3002)"
else
    echo "   🔄 启动后端服务..."
    cd "$current_path/backend/entrance"
    npm run dev > "$current_path/logs/backend.log" 2>&1 &
    sleep 3
    echo "   ✅ 后端已启动 (3002)"
fi

# 检查并启动前端
echo ""
echo "5️⃣ 检查前端服务状态..."
if lsof -i:3000 | grep -q LISTEN; then
    echo "   ✅ 前端已运行 (3000)"
else
    echo "   🔄 启动前端服务..."
    cd "$current_path/frontend"
    npm run dev > "$current_path/logs/frontend.log" 2>&1 &
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
echo "  Question Filter: 问题过滤服务  端口 3005 (独立服务)"
echo "  FirstLayer: 问题分类服务  端口 3004 (独立服务)"
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
echo "  🔍 Question Filter 服务 (独立 3005 端口):"
echo "     本地：http://localhost:3005"
echo "     局域网：http://$LOCAL_IP:3005"
echo "     文档：http://localhost:3005/docs"
echo ""
echo "  📊 FirstLayer 服务 (独立 3004 端口):"
echo "     本地：http://localhost:3004"
echo "     局域网：http://$LOCAL_IP:3004"
echo "     文档：http://localhost:3004/docs"
echo "  ───────────────────────────────────────"
echo ""
echo "📝 日志文件:"
echo "  Nginx:    /usr/local/nginx/logs/"
echo "  Question Filter: ./logs/question_filter.log"
echo "  FirstLayer: ./logs/category_classifier.log"
echo "  后端：    ./logs/backend.log"
echo "  前端：    ./logs/frontend.log"
echo ""
echo "💡 提示：局域网内其他设备可通过 http://$LOCAL_IP 访问前端"
echo ""
