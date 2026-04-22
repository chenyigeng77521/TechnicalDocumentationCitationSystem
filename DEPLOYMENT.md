# Docker 部署文档

Knowledge QA System 的完整 Docker 部署方案。

---

## 📋 前置要求

- **Docker** 20.10+
- **Docker Compose** 2.0+（或 Docker Compose Plugin）
- **内存** 至少 2GB 可用
- **磁盘** 至少 5GB 可用空间

### 检查 Docker 版本

```bash
docker --version
docker compose version  # 或 docker-compose --version
```

---

## 🚀 快速开始

### 1. 启动服务

```bash
# 赋予执行权限
chmod +x *.sh

# 一键启动
./start.sh
```

脚本会自动完成：
- ✅ 检查 Docker 环境
- ✅ 创建数据目录
- ✅ 构建镜像
- ✅ 启动服务
- ✅ 等待服务就绪

### 2. 访问系统

- **前端界面**: http://localhost:3000
- **后端 API**: http://localhost:3002
- **健康检查**: http://localhost:3002/health

---

## 📁 目录结构

```
knowledge-qa-system/
├── docker-compose.yml      # Docker Compose 配置
├── Dockerfile.backend      # 后端镜像定义
├── .env.example            # 环境变量模板
├── .dockerignore           # Docker 忽略文件
├── storage/                # 数据目录（自动创建）
│   ├── knowledge.db        # SQLite 数据库
│   ├── index/              # 向量索引
│   └── files/              # 上传的文件
├── start.sh                # 启动脚本
├── stop.sh                 # 停止脚本
├── restart.sh              # 重启脚本
├── logs.sh                 # 查看日志
├── backup.sh               # 备份数据
└── restore.sh              # 恢复数据
```

---

## 🔧 配置选项

### 环境变量 (.env)

复制模板并编辑：

```bash
cp .env.example .env
vim .env
```

**核心配置**：

```bash
# LLM API（可选，不配置使用关键词检索）
LLM_API_KEY=your_openai_api_key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4-turbo

# 嵌入模型
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIMENSION=1536

# 严格模式
STRICT_MODE=true
```

---

## 🛠️ 管理命令

### 启动

```bash
./start.sh
# 或
docker compose up -d
```

### 停止

```bash
./stop.sh
# 或
docker compose down
```

### 重启

```bash
./restart.sh
# 或
docker compose restart
```

### 查看日志

```bash
# 实时日志
./logs.sh -f
# 或
docker compose logs -f

# 仅后端
docker compose logs backend

# 仅前端
docker compose logs frontend

# 最近 100 行
docker compose logs --tail=100
```

### 查看状态

```bash
docker compose ps
```

---

## 💾 数据备份

### 备份

```bash
./backup.sh
```

备份文件保存在 `backups/` 目录：
```
backups/
└── knowledge-qa-backup-20260421_143022.tar.gz
```

### 恢复

```bash
# 列出可用备份
ls -lh backups/*.tar.gz

# 恢复指定备份
./restore.sh backups/knowledge-qa-backup-20260421_143022.tar.gz
```

⚠️ **警告**: 恢复会覆盖当前所有数据！

---

## 🔍 故障排查

### 1. 端口被占用

```bash
# 检查端口占用
lsof -i :3000
lsof -i :3002

# 终止进程
kill -9 <PID>
```

或在 `docker-compose.yml` 中修改端口：
```yaml
ports:
  - "8080:3000"  # 主机端口：容器端口
```

### 2. 权限问题

```bash
# 修复权限
chmod -R 777 storage/
```

### 3. 容器启动失败

```bash
# 查看详细日志
docker compose logs backend
docker compose logs frontend

# 重新构建
docker compose build --no-cache
docker compose up -d
```

### 4. 内存不足

```bash
# 查看资源使用
docker stats

# 在 docker-compose.yml 中调整资源限制
deploy:
  resources:
    limits:
      memory: 2G  # 增加限制
```

### 5. 数据目录不存在

```bash
mkdir -p storage/files storage/index
chmod -R 777 storage/
```

---

## 🔄 更新版本

```bash
# 拉取最新代码
git pull

# 重新构建镜像
docker compose build

# 重启服务
docker compose up -d
```

---

## 📊 生产环境部署

### 1. 使用自定义域名

配置 Nginx 反向代理：

```nginx
server {
    listen 80;
    server_name qa.yourdomain.com;

    # 前端
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    # 后端 API
    location /api {
        proxy_pass http://localhost:3002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 2. SSL 证书（HTTPS）

使用 Let's Encrypt：

```bash
# 安装 certbot
sudo apt install certbot python3-certbot-nginx

# 获取证书
sudo certbot --nginx -d qa.yourdomain.com
```

### 3. 自动重启

```bash
# 在 docker-compose.yml 中已配置
restart: unless-stopped
```

### 4. 监控

```bash
# 实时资源监控
docker stats

# 日志轮转（已在配置中）
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

---

## 🎯 最佳实践

### 1. 定期备份

```bash
# 添加到 crontab（每天凌晨 2 点）
0 2 * * * /path/to/backup.sh
```

### 2. 日志清理

```bash
# 清理旧日志
docker system prune -f
```

### 3. 安全加固

```bash
# 使用非 root 用户（已配置）
# 限制网络访问
# 定期更新 Docker 镜像
```

---

## 📞 常见问题

**Q: 上传的文件存在哪里？**  
A: `storage/files/` 目录，已挂载到宿主机，容器重启不会丢失。

**Q: 如何查看数据库文件？**  
A: `storage/knowledge.db`，使用 SQLite 浏览器可打开。

**Q: 可以只启动后端或前端吗？**  
A: 可以，使用 `docker compose up -d backend` 或 `docker compose up -d frontend`。

**Q: 如何进入容器？**  
A: `docker compose exec backend sh` 或 `docker compose exec frontend sh`。

**Q: 数据迁移到新机器？**  
A: 复制整个 `storage/` 目录到新机器，重新运行 `start.sh`。

---

## 🔗 相关文档

- [Docker 官方文档](https://docs.docker.com/)
- [Docker Compose 文档](https://docs.docker.com/compose/)
- [Knowledge QA System 使用说明](./README.md)

---

**最后更新**: 2026-04-21
