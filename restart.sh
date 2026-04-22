#!/bin/bash

# 重启 Docker 服务

set -e

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}🔄 重启服务...${NC}"

# 检查是否使用新版 docker compose 命令
if docker compose version &> /dev/null; then
    docker compose restart
else
    docker-compose restart
fi

echo -e "${GREEN}✓ 服务已重启${NC}"
echo ""

# 等待服务就绪
echo "等待服务就绪..."
sleep 5

# 显示状态
if docker compose version &> /dev/null; then
    docker compose ps
else
    docker-compose ps
fi
