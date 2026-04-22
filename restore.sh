#!/bin/bash

# 恢复数据

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 检查参数
if [ -z "$1" ]; then
    echo -e "${RED}✗ 请指定备份文件${NC}"
    echo "用法：./restore.sh <backup_file.tar.gz>"
    echo ""
    echo "可用的备份文件:"
    ls -lh backups/*.tar.gz 2>/dev/null || echo "  暂无备份文件"
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "${BACKUP_FILE}" ]; then
    echo -e "${RED}✗ 备份文件不存在：${BACKUP_FILE}${NC}"
    exit 1
fi

echo -e "${YELLOW}⚠️  警告：恢复数据将覆盖当前所有数据！${NC}"
read -p "确定继续吗？(y/N) " -n 1 -r
echo

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${RED}✗ 已取消${NC}"
    exit 1
fi

echo -e "${YELLOW}📦 开始恢复...${NC}"
echo "备份文件：${BACKUP_FILE}"

# 停止服务
echo -e "${YELLOW}⏸  停止服务...${NC}"
if docker compose version &> /dev/null; then
    docker compose stop
else
    docker-compose stop
fi

# 备份当前数据（以防万一）
CURRENT_BACKUP="./storage_backup_$(date +%Y%m%d_%H%M%S)"
echo -e "${YELLOW}💾 备份当前数据到：${CURRENT_BACKUP}${NC}"
mv storage/ ${CURRENT_BACKUP}/

# 恢复数据
echo -e "${YELLOW}📁 恢复数据...${NC}"
mkdir -p storage/
tar -xzf ${BACKUP_FILE} -C ./

# 设置权限
chmod -R 777 storage/

# 启动服务
echo -e "${YELLOW}▶  启动服务...${NC}"
if docker compose version &> /dev/null; then
    docker compose up -d
else
    docker-compose up -d
fi

echo -e "${GREEN}✓ 恢复完成${NC}"
echo ""
echo "如果恢复失败，可以从临时备份恢复:"
echo "  mv ${CURRENT_BACKUP}/ storage/ && docker compose up -d"
