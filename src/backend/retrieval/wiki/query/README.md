

## 知识库查询 API 服务 - 详细启动说明

## 一、完整代码

以下是修复完成的 [knowledge_api.py](knowledge_api.py) （上面代码已完整，此处为补充说明）：


## 二、环境准备

### 1\. 创建项目目录结构

```
cd /Users/lenghaijun/sdd/kdDemo

# 创建必要的目录
mkdir -p wiki raw logs scripts

# 创建 .env 文件
touch .env
```

### 2\. 安装依赖

使用 [requirements.txt](requirements.txt)：

```
# 安装
pip install -r requirements.txt
```

### 3\. 配置环境变量

编辑 [.env](.env) 文件：

```
# .env 文件  
OPENCODE_PATH=/Users/lenghaijun/sdd/kdDemo  # opencode 命令路径  
WORKSPACE_DIR=/Users/lenghaijun/sdd/kdDemo  # opencode 工作目录  
KNOWLEDGE_BASE_NAME=my_knowledge_base  # 知识库名称  
HOST=0.0.0.0  
PORT=8000  
DEBUG=true  
MAX_CONCURRENT=10  
CACHE_TTL=300  
API_KEY=  # 可选，设置后需要认证  
  
# 大模型 API 配置（根据你的实际 API 填写）  
LLM_API_KEY=sk-8c814e3379274286a853bde65f66ae74  
LLM_BASE_URL=https://api.deepseek.com/v1  
LLM_MODEL=deepseek-chat
```

## 三、启动服务

### 方式 1：直接运行 Python 脚本
```

cd /Users/lenghaijun/sdd/kdDemo
python knowledge_api.py
```

### 方式 2：使用启动脚本

创建 `start_api.sh` ：

```
#!/bin/bash
# start_api.sh - 启动知识库 API 服务

cd /Users/lenghaijun/sdd/kdDemo

# 加载环境变量
source .env 2>/dev/null || echo "未找到 .env 文件，使用默认配置"

# 检查依赖
echo "检查依赖..."
python -c "import fastapi, uvicorn, openai" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "缺少依赖，正在安装..."
    pip install fastapi uvicorn openai python-dotenv
fi

# 检查 wiki 目录
if [ ! -d "wiki" ]; then
    echo "警告: wiki 目录不存在，请创建并添加文档"
fi

# 启动服务
echo "启动知识库 API 服务..."
echo "访问 http://localhost:8000/docs 查看 API 文档"
python knowledge_api.py
```

赋予执行权限并运行：

```
chmod +x start_api.sh
./start_api.sh
```

## 四、验证服务

### 1\. 健康检查

```
curl http://localhost:8000/health
```

预期响应：

```
{
  "status": "ok",
  "version": "3.0.0",
  "timestamp": "2024-01-15T10:30:00",
  "wiki_dir_exists": true,
  "wiki_files_count": 3,
  "llm_available": true
}
```

### 2\. 查询知识库

```
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "AUTH CRBT USER 是什么？",
    "timeout": 60,
    "return_raw": false
  }'
```

### 3\. 使用 Python 测试

```
# test_api.py
import requests
import json

# 查询示例
response = requests.post(
    "http://localhost:8000/query",
    json={
        "query": "USSD 菜单配置方法",
        "timeout": 60
    }
)

result = response.json()
print(f"成功: {result['success']}")
print(f"回答: {result['answer']}")
print(f"来源: {result['sources']}")
print(f"耗时: {result['execution_time']}秒")
```

### 4\. 使用 curl 流式查询

```
curl -N -X POST http://localhost:8000/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "什么是 USSD？", "timeout": 60}'
```

## 五、API 端点说明

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/` | GET | 根路径，健康检查 |
| `/health` | GET | 健康检查 |
| `/docs` | GET | Swagger API 文档 |
| `/redoc` | GET | ReDoc API 文档 |
| `/query` | POST | 查询知识库 |
| `/query/stream` | POST | 流式查询（SSE） |
| `/wiki/stats` | GET | 获取 wiki 统计 |
| `/wiki/files` | GET | 列出 wiki 文件 |
| `/wiki/refresh` | POST | 刷新 wiki 缓存 |
| `/cache` | DELETE | 清空查询缓存 |
| `/stats` | GET | 服务统计信息 |

## 六、查询请求格式

```
{
  "query": "你的问题",
  "timeout": 60,
  "return_raw": false
}
```

### 参数说明：

- `query`: 必填，查询内容
- `timeout`: 可选，超时时间（秒），默认 60，范围 10-300
- `return_raw`: 可选，是否返回原始输出，默认 false

## 七、查询规则（硬编码在 prompt 中）

服务强制大模型遵守以下规则：

1. **只使用 wiki/ 目录中的内容**
2. **不使用训练数据中的知识**
3. **找不到信息时明确告知**
4. **回答必须说明来源**
5. **不编造任何信息**

## 八、使用 Docker 启动（可选）

创建 `Dockerfile` ：

```
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "knowledge_api:app", "--host", "0.0.0.0", "--port", "8000"]
```

构建并运行：

```
# 构建镜像
docker build -t knowledge-api .

# 运行容器
docker run -d \
  -p 8000:8000 \
  -e LLM_API_KEY=your-key \
  -v $(pwd)/wiki:/app/wiki \
  --name knowledge-api \
  knowledge-api
```

## 九、常见问题解决

### 1\. 端口被占用

```
# 查看占用端口的进程
lsof -i :8000

# 杀掉进程或更改端口
PORT=8001 python knowledge_api.py
```

### 2\. 大模型 API 调用失败

检查 `.env` 配置：

```
# 测试 API 连接
curl -X POST $LLM_BASE_URL/chat/completions \
  -H "Authorization: Bearer $LLM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-3.5-turbo","messages":[{"role":"user","content":"test"}]}'
```

### 3\. 中文乱码

确保文件编码为 UTF-8：

```
# 转换文件编码
iconv -f GBK -t UTF-8 input.md > output.md
```

## 十、后台运行服务

### 使用 nohup

```
nohup python knowledge_api.py > api.log 2>&1 &
```

### 使用 screen

```
# 创建新 session
screen -S knowledge-api

# 运行服务
python knowledge_api.py

# 分离：Ctrl+A, 然后按 D
# 重新连接：screen -r knowledge-api
```

### 使用 systemd（Linux）

创建 `/etc/systemd/system/knowledge-api.service` ：

```
[Unit]
Description=Knowledge Base API Service
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/Users/lenghaijun/sdd/kdDemo
EnvironmentFile=/Users/lenghaijun/sdd/kdDemo/.env
ExecStart=/usr/bin/python3 /Users/lenghaijun/sdd/kdDemo/knowledge_api.py
Restart=always

[Install]
WantedBy=multi-user.target
```

启动服务：

```
sudo systemctl daemon-reload
sudo systemctl start knowledge-api
sudo systemctl enable knowledge-api
sudo systemctl status knowledge-api
```

## 十一、测试示例

创建 `test_queries.sh` 批量测试脚本：

```
#!/bin/bash
# test_queries.sh

API_URL="http://localhost:8000"

echo "=== 测试健康检查 ==="
curl -s $API_URL/health | jq .

echo -e "\n=== 测试查询 ==="
curl -s -X POST $API_URL/query \
  -H "Content-Type: application/json" \
  -d '{"query": "USSD 菜单如何配置？"}' | jq .

echo -e "\n=== 测试不存在的知识 ==="
curl -s -X POST $API_URL/query \
  -H "Content-Type: application/json" \
  -d '{"query": "不存在的概念"}' | jq .

echo -e "\n=== 获取 wiki 统计 ==="
curl -s $API_URL/wiki/stats | jq .
```

运行测试：

```
chmod +x test_queries.sh
./test_queries.sh
```

## 启动成功标志

当看到以下输出时，表示服务启动成功：

```
============================================================
知识库查询服务 v3.0 - 大模型查询 wiki 目录
============================================================
查询规则:
  1. 大模型只读取 wiki/ 目录下的文件
  2. 不使用训练数据中的知识
  3. 以 wiki/ 目录中的内容为准
  4. 无信息时明确告知
  5. 必须说明来源
============================================================
配置:
  - Host: 0.0.0.0:8000
  - Workspace: /Users/lenghaijun/sdd/kdDemo
  - Wiki Dir: wiki
  - LLM Model: gpt-3.5-turbo
  - Wiki 文件数: 3
  ✅ Wiki 目录就绪
  ✅ LLM API 配置完成
============================================================
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

然后就可以访问 [http://localhost:8000/docs](http://localhost:8000/docs) 查看交互式 API 文档了！

