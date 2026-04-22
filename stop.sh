#!/bin/bash

# 停止 Docker 服务

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}⏹  停止服务...${NC}"

# 检查是否使用新版 docker compose 命令
if docker compose version &> /dev/null; then
    docker compose down
else
    docker-compose down
fi

echo -e "${GREEN}✓ 服务已停止${NC}"
