#!/bin/bash

# 备份数据

set -e

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 备份目录
BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/knowledge-qa-backup-${TIMESTAMP}.tar.gz"

# 创建备份目录
mkdir -p ${BACKUP_DIR}

echo -e "${YELLOW}📦 开始备份...${NC}"
echo "备份文件：${BACKUP_FILE}"

# 停止服务（可选）
echo -e "${YELLOW}⏸  停止服务...${NC}"
if docker compose version &> /dev/null; then
    docker compose stop
else
    docker-compose stop
fi

# 备份数据目录
echo -e "${YELLOW}📁 备份数据...${NC}"
tar -czf ${BACKUP_FILE} storage/

# 启动服务
echo -e "${YELLOW}▶  启动服务...${NC}"
if docker compose version &> /dev/null; then
    docker compose start
else
    docker-compose start
fi

echo -e "${GREEN}✓ 备份完成${NC}"
echo "备份文件：${BACKUP_FILE}"
echo "文件大小: $(du -h ${BACKUP_FILE} | cut -f1)"
