# Question Filter Service

## 概述

问题过滤系统，使用 StructBERT 模型对用户提问进行预过滤，识别无效问题和实时类问题。

## 问题分类

| 分类代码 | 分类名称 | 描述 | 示例 |
|---------|---------|------|------|
| VALID | 有效问题 | 属于知识库范围内的可回答问题 | "如何申请年假？"、"公司成立于哪一年？" |
| INVALID | 无效问题 | 无法回答的问题（空问题、乱码、无关内容等） | ""、"!!!"、"abc" |
| REALTIME | 实时类问题 | 需要实时数据的问题（天气、新闻、股价等） | "今天天气怎么样？"、"现在股价多少？" |
| PERSONAL | 个人隐私 | 涉及个人隐私的问题 | "我的工资是多少？"、"我的考勤记录" |
| OFFTOPIC | 偏离主题 | 与知识库完全无关的问题（恶意/敏感/广告等） | 广告、色情、政治敏感等 |
| CHAT | 友好闲聊 | 日常问候和友好交流，可适度回应 | "你好"、"谢谢"、"在干嘛"、"哈哈" |

## 快速开始

### 1. 安装依赖

```bash
cd backend/firstlayer/question_filter
pip install -r requirements.txt
```

### 2. 启动服务

```bash
# 开发模式
python app.py

# 或使用 uvicorn
uvicorn app:app --host 0.0.0.0 --port 3005 --reload

# 或使用启动脚本
./start.sh
```

### 3. 访问 API 文档

```
http://localhost:3005/docs
```

## API 接口

### 1. 问题过滤

**POST** `/api/filter`

请求示例：
```json
{
    "question": "今天的天气怎么样？"
}
```

响应示例：
```json
{
    "success": true,
    "question": "今天的天气怎么样？",
    "category": "REALTIME",
    "confidence": 0.92,
    "description": "实时类问题 - 需要实时数据的问题（天气、新闻、股价等），系统无法回答",
    "reason": "包含实时关键词：天气",
    "filter_message": "抱歉，这是一个需要实时数据的问题（如天气、新闻、股价等），本系统无法提供实时信息。请问一个与知识库相关的问题。"
}
```

### 2. 获取所有过滤类型

**GET** `/api/filter/types`

响应示例：
```json
{
    "success": true,
    "types": {
        "VALID": "有效问题 - 属于知识库范围内的可回答问题",
        "INVALID": "无效问题 - 无法回答的问题（空问题、乱码、无关内容等）",
        "REALTIME": "实时类问题 - 需要实时数据的问题（天气、新闻、股价等）",
        "PERSONAL": "个人隐私 - 涉及个人隐私的问题",
        "OFFTOPIC": "偏离主题 - 与知识库完全无关的问题"
    }
}
```

### 3. 批量过滤

**POST** `/api/filter/batch`

请求示例：
```json
[
    {"question": "今天的天气怎么样？"},
    {"question": "如何申请年假？"},
    {"question": ""}
]
```

### 4. 健康检查

**GET** `/health`

## 技术栈

- **框架**: FastAPI
- **模型**: StructBERT (uer/structbert-base-chinese)
- **深度学习**: PyTorch 2.1.0+
- **Python**: 3.11+

## 目录结构

```
question_filter/
├── app.py              # FastAPI 应用入口
├── classifier.py       # StructBERT 分类器
├── config.py           # 配置文件
├── requirements.txt    # Python 依赖
├── start.sh            # 启动脚本
├── routes/
│   ├── __init__.py
│   └── classify.py     # 过滤 API 路由
├── .env               # 环境变量
├── .env.example       # 环境变量示例
└── README.md          # 说明文档
```

## 环境变量

| 变量名 | 默认值 | 说明 |
|-------|--------|------|
| HOST | 0.0.0.0 | 服务绑定地址 |
| PORT | 3005 | 服务端口 |
| LOG_LEVEL | INFO | 日志级别 |

## 过滤规则

### 无效问题检测

- 空字符串或只有空白字符
- 无中文字符
- 只有标点符号

### 闲聊类问题检测

使用 132+ 个闲聊关键词，包括：

- **问候语**: 你好、您好、早上好、下午好、晚上好、晚安、嗨、哈喽
- **感谢**: 谢谢、谢谢你、感谢、多谢、麻烦了、辛苦、辛苦了
- **告别**: 再见、拜拜、拜、回头聊、下次、改天、再聊
- **日常对话**: 在吗、有空吗、在干嘛、吃了吗、聊天、聊聊
- **语气词**: 嗯嗯、啊啊、哦哦、哈哈、呵呵、嘻嘻、嘿嘿
- **礼貌用语**: 请问、拜托、劳驾、不好意思、抱歉、对不起
- **询问**: 你是谁、你叫什么、你能做什么、你是做什么的
- **其他**: 开心、高兴、无聊、累了、周末愉快、节日快乐

**识别规则**:
- 高置信度关键词（如"你好"、"谢谢"、"再见"）匹配 1 个即识别为 CHAT
- 普通闲聊关键词需要匹配 2 个或以上才识别为 CHAT

### 实时类问题关键词

包括：天气、新闻、股价、汇率、交通、直播、比分等实时信息相关关键词。

## 集成到主系统

在主后端服务中集成过滤功能：

```python
# 调用问题过滤服务
import requests

def preprocess_question(question: str):
    """问题预处理：先过滤，再分类"""
    # 1. 问题过滤
    filter_resp = requests.post(
        "http://localhost:3005/api/filter",
        json={"question": question}
    )
    filter_result = filter_resp.json()
    
    # 2. 如果不是有效问题，直接返回过滤提示
    if filter_result["category"] != "VALID":
        return {
            "success": False,
            "message": filter_result["filter_message"]
        }
    
    # 3. 有效问题，继续分类和处理
    # ... 调用 category_classifier ...
```

## 模型说明

使用阿里达摩院 StructBERT 模型：
- **模型名称**: uer/structbert-base-chinese
- **类型**: 中文预训练语言模型
- **优势**: 对中文文本分类任务有良好表现
- **来源**: https://github.com/dbiir/UER-py

## 日志

启动日志示例：
```
============================================================
  问题过滤服务启动中...
============================================================
✅ 规则分类器已初始化
🤖 模型：uer/structbert-base-chinese
🔄 正在加载 StructBERT 模型...
✅ StructBERT 模型加载完成！设备：cuda
============================================================
  ✅ 服务启动完成!
  🌐 访问地址：http://0.0.0.0:3005
  📚 API 文档：http://0.0.0.0:3005/docs
============================================================
```
