#!/bin/bash

# Knowledge QA System Docker 部署脚本
# 使用方法：./start.sh

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

log_section() {
    echo -e "${BLUE}════════════════════════════════════════${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}════════════════════════════════════════${NC}"
}

# 检查 Docker 是否安装
check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装，请先安装 Docker"
        echo "安装地址：https://docs.docker.com/get-docker/"
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        log_error "Docker Compose 未安装，请先安装 Docker Compose"
        echo "安装地址：https://docs.docker.com/compose/install/"
        exit 1
    fi
    
    log_info "Docker 环境检查通过"
}

# 创建必要的目录
create_directories() {
    log_section "创建数据目录"
    
    mkdir -p storage/files
    mkdir -p storage/index
    
    # 设置权限
    chmod -R 777 storage/
    
    log_info "数据目录创建完成"
    ls -la storage/
}

# 检查 .env 文件
check_env() {
    if [ ! -f .env ]; then
        log_warn ".env 文件不存在，从 .env.example 复制"
        cp .env.example .env
        log_info "请编辑 .env 文件配置 LLM API（可选）"
        log_info "如果不配置，系统将使用关键词检索模式"
    else
        log_info ".env 文件已存在"
    fi
}

# 构建镜像
build_images() {
    log_section "构建 Docker 镜像"
    
    # 检查是否使用新版 docker compose 命令
    if docker compose version &> /dev/null; then
        docker compose build
    else
        docker-compose build
    fi
    
    log_info "镜像构建完成"
}

# 启动服务
start_services() {
    log_section "启动服务"
    
    # 检查是否使用新版 docker compose 命令
    if docker compose version &> /dev/null; then
        docker compose up -d
    else
        docker-compose up -d
    fi
    
    log_info "服务启动中..."
}

# 等待服务就绪
wait_for_services() {
    log_section "等待服务就绪"
    
    max_attempts=30
    attempt=0
    
    # 等待后端服务
    while [ $attempt -lt $max_attempts ]; do
        if curl -s http://localhost:3002/health &> /dev/null; then
            log_info "后端服务已就绪"
            break
        fi
        
        attempt=$((attempt + 1))
        echo -ne "等待后端服务... $attempt/$max_attempts\r"
        sleep 2
    done
    
    if [ $attempt -eq $max_attempts ]; then
        log_warn "后端服务启动超时，请检查日志"
    fi
    
    # 等待前端服务
    attempt=0
    while [ $attempt -lt $max_attempts ]; do
        if curl -s http://localhost:3000 &> /dev/null; then
            log_info "前端服务已就绪"
            break
        fi
        
        attempt=$((attempt + 1))
        echo -ne "等待前端服务... $attempt/$max_attempts\r"
        sleep 2
    done
    
    if [ $attempt -eq $max_attempts ]; then
        log_warn "前端服务启动超时，请检查日志"
    fi
}

# 显示状态
show_status() {
    log_section "服务状态"
    
    # 检查是否使用新版 docker compose 命令
    if docker compose version &> /dev/null; then
        docker compose ps
    else
        docker-compose ps
    fi
    
    echo ""
    log_section "访问地址"
    echo -e "  前端界面：${GREEN}http://localhost:3000${NC}"
    echo -e "  后端 API:  ${GREEN}http://localhost:3002${NC}"
    echo -e "  健康检查: ${GREEN}http://localhost:3002/health${NC}"
    echo ""
    log_section "管理命令"
    echo -e "  查看日志:  ${YELLOW}docker compose logs -f${NC}"
    echo -e "  停止服务:  ${YELLOW}docker compose down${NC}"
    echo -e "  重启服务:  ${YELLOW}docker compose restart${NC}"
    echo -e "  查看状态:  ${YELLOW}docker compose ps${NC}"
    echo ""
    log_info "🎉 部署完成！系统已启动"
}

# 主流程
main() {
    log_section "Knowledge QA System Docker 部署"
    
    # 检查环境
    check_docker
    
    # 创建目录
    create_directories
    
    # 检查配置
    check_env
    
    # 构建镜像
    build_images
    
    # 启动服务
    start_services
    
    # 等待就绪
    wait_for_services
    
    # 显示状态
    show_status
}

# 执行
main
