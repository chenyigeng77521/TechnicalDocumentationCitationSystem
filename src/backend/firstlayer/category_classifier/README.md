# FirstLayer 问题分类系统

## 概述

第一层问题分类系统，使用 GLiClass base 模型对前台请求的问题进行智能分类。

## 五大问题分类

| 分类代码 | 分类名称 | 描述 | 示例 |
|---------|---------|------|------|
| FACT | 事实型 | 询问具体事实、数据、定义、名称等 | "什么是人工智能？"、"公司成立于哪一年？" |
| PROC | 过程型 | 询问步骤、流程、操作方法等 | "如何申请年假？"、"怎样安装软件？" |
| EXPL | 解释型 | 询问原因、原理、机制等 | "为什么天空是蓝色的？"、"这是什么原理？" |
| COMP | 比较型 | 询问对比、差异、区别、优劣等 | "A 和 B 有什么区别？"、"哪个更好？" |
| META | 元认知型 | 询问学习方法、思考过程、自我反思等 | "怎么提高记忆力？"、"如何有效学习？" |
| UNKNOWN | 未知类型 | 无法归类到上述任何一类 | - |

## 快速开始

### 1. 安装依赖

```bash
cd backend/firstlayer
pip install -r requirements.txt
```

### 2. 启动服务

```bash
# 开发模式
python category_classifier/app.py

# 或使用 uvicorn
uvicorn category_classifier.app:app --host 0.0.0.0 --port 3004 --reload

# 或使用启动脚本
cd category_classifier
./start.sh
```

### 3. 访问 API 文档

```
http://localhost:3004/docs
```

## API 接口

### 1. 问题分类

**POST** `/api/classify`

请求示例：
```json
{
    "question": "如何申请年假？"
}
```

响应示例：
```json
{
    "success": true,
    "question": "如何申请年假？",
    "category": "PROC",
    "confidence": 0.9234,
    "description": "过程型问题 - 询问步骤、流程、操作方法、怎么做等"
}
```

### 2. 获取所有分类类型

**GET** `/api/classify/types`

响应示例：
```json
{
    "success": true,
    "types": {
        "FACT": "事实型问题 - 询问具体事实、数据、定义、名称等",
        "PROC": "过程型问题 - 询问步骤、流程、操作方法、怎么做等",
        "EXPL": "解释型问题 - 询问原因、原理、机制、为什么等",
        "COMP": "比较型问题 - 询问对比、差异、区别、哪个更好等",
        "META": "元认知型问题 - 询问学习方法、思考过程、自我反思等"
    }
}
```

### 3. 批量分类

**POST** `/api/classify/batch`

请求示例：
```json
[
    {"question": "什么是人工智能？"},
    {"question": "如何安装 Python？"},
    {"question": "为什么天空是蓝色的？"}
]
```

### 4. 健康检查

**GET** `/health`

## 技术栈

- **框架**: FastAPI
- **模型**: GLiClass base (google/gliclass-base)
- **深度学习**: PyTorch 2.1.2
- **Python**: 3.9+

## 目录结构

```
category_classifier/
├── app.py              # FastAPI 应用入口
├── classifier.py       # GLiClass 分类器
├── config.py           # 配置文件
├── requirements.txt    # Python 依赖
├── start.sh            # 启动脚本
├── routes/
│   ├── __init__.py
│   └── classify.py     # 分类 API 路由
├── data/              # 数据文件
│   └── sample_questions.json
├── .env               # 环境变量
├── .env.example       # 环境变量示例
├── README.md          # 说明文档
├── FINE_TUNING_GUIDE.md  # 微调指南
└── __pycache__/
```

## 环境变量

| 变量名 | 默认值 | 说明 |
|-------|--------|------|
| FIRSTLAYER_HOST | 0.0.0.0 | 服务绑定地址 |
| FIRSTLAYER_PORT | 3004 | 服务端口 |

## 备用方案

如果 GLiClass 模型无法加载，系统将自动切换到基于关键词的分类方法：

- **FACT**: 包含"什么"、"哪个"、"谁"、"何时"、"何地"、"多少"等
- **PROC**: 包含"如何"、"怎样"、"步骤"、"流程"、"方法"、"怎么"等
- **EXPL**: 包含"为什么"、"什么原因"、"原理"、"机制"等
- **COMP**: 包含"区别"、"差异"、"对比"、"比较"、"哪个更好"等
- **META**: 包含"怎么学"、"如何学习"、"怎样提高"、"学习方法"等

## 集成到主系统

在主后端服务中集成分类功能：

```python
# 在主后端服务中调用分类 API
import requests

response = requests.post(
    "http://localhost:3004/api/classify",
    json={"question": "用户的问题"}
)

category = response.json()["category"]
confidence = response.json()["confidence"]
```

## License

MIT
