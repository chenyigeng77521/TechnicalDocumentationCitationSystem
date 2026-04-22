#!/bin/bash

# 查看 Docker 日志

set -e

# 颜色定义
GREEN='\033[0;32m'
NC='\033[0m'

# 检查参数
if [ "$1" == "-f" ] || [ "$1" == "--follow" ]; then
    FOLLOW="-f"
else
    FOLLOW=""
fi

# 检查是否使用新版 docker compose 命令
if docker compose version &> /dev/null; then
    docker compose logs $FOLLOW
else
    docker-compose logs $FOLLOW
fi
