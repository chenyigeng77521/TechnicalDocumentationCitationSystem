# Category Classifier - 问题分类服务

> 项目：TechnicalDocumentationCitationSystem  
> 路径：`src/backend/firstlayer/category_classifier`  
> 端口：**3004**  
> 职责：对用户问题进行五大类分类，是问答系统的**第一层过滤**

---

## 📁 目录结构

```
category_classifier/
├── app.py                     # FastAPI 服务入口
├── config.py                  # 配置文件
├── classifier.py             # 分类器核心实现
├── download_models.py        # 模型下载脚本
├── test_nlu_models.py       # NLU 模型测试脚本
├── pipeline/
│   └── qa_pipeline.py       # 问答流水线
├── nlu/
│   └── pipeline.py          # NLU 处理流水线
├── models/
│   ├── base_model.py        # 基模型类
│   ├── slim_plm.py          # SlimPLM 模型（查询改写）
│   ├── rex_uninlu.py        # RexUniNLU 模型（指代消解）
│   └── turn_sense.py        # TurnSense 模型（完整性检测）
├── routes/
│   ├── classify.py         # 分类 API
│   ├── nlu.py              # NLU 处理 API
│   ├── config.py           # 配置 API
│   ├── upload.py           # 上传 API
│   └── qa.py               # 问答 API
├── services/
│   ├── retrieval_client.py # 检索层客户端
│   └── context_client.py    # 上下文记忆客户端
└── data/
    └── sample_questions.json  # 示例问题数据
```

---

## 🛠 技术栈

| 技术 | 说明 |
|------|------|
| FastAPI | Web 服务框架 |
| PyTorch | 深度学习框架 |
| Transformers | Hugging Face 模型库 |
| GLiClass | 问题分类模型 |

---

## 🔬 模型说明

### GLiClass 分类模型
对问题进行五大类分类：
- **FACT**：事实型问题（如"什么是人工智能？"）
- **PROC**：过程型问题（如"如何申请年假？"）
- **EXPL**：解释型问题（如"为什么天空是蓝色的？"）
- **COMP**：比较型问题（如"iPhone 和华为哪个好？"）
- **META**：元认知型问题（如"你能做什么？"）
- **UNKNOWN**：未知类型

### RexUniNLU 模型
指代消解模型，检测并替换指代词：
- 指代词：它、它们、这个、那个、这些、那些等
- 作用：在多轮对话中解析指代对象

### SlimPLM-Query-Rewriting 模型
查询改写模型，优化问题表达

### TurnSense 模型
问题完整性检测，判断问题是否完整可用

---

## 🌐 API 路由总览

### `/api/classify` - 问题分类

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/` | 单条问题分类 |
| GET | `/types` | 获取所有分类类型 |
| POST | `/batch` | 批量分类 |

**分类请求示例**：
```json
{
    "question": "如何申请年假？"
}
```

**分类响应示例**：
```json
{
    "success": true,
    "question": "如何申请年假？",
    "category": "PROC",
    "confidence": 0.95,
    "description": "过程型问题"
}
```

---

### `/api/nlu` - NLU 处理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/process` | 完整 NLU 处理流程 |
| POST | `/classify-only` | 仅分类（不检索） |
| GET | `/check-completeness` | 检查问题完整性 |
| POST | `/rewrite-query` | 查询改写 |
| POST | `/resolve-pronoun` | 指代消解 |
| GET | `/test-retrieval` | 测试检索层连接 |

**NLU 处理流程**：
```
1. 指代判断 → RexUniNLU 模型检测指代词
2. 上下文加载 → 从上下文记忆服务加载历史会话
3. 指代替换 → RexUniNLU 模型替换指代词
4. 查询改写 → SlimPLM 模型优化问题
5. 完整性检查 → 规则过滤 + TurnSense 模型
6. 检索 → 调用检索层接口
7. 记录上下文 → 保存到上下文记忆服务
```

---

## 🚀 启动方式

```bash
# 进入目录
cd category_classifier

# 启动服务
python app.py

# 或使用 uvicorn
uvicorn app:app --host 0.0.0.0 --port 3004
```

---

## ⚙️ 环境变量配置

| 变量名 | 说明 |
|--------|------|
| `HOST` | 监听地址（默认 0.0.0.0） |
| `PORT` | 监听端口（默认 3004） |
| `MODEL_PATH` | 模型文件路径 |
| `RETRIEVAL_URL` | 检索服务地址 |
| `CONTEXT_MEMORY_URL` | 上下文记忆服务地址 |

---

## 📊 下游服务依赖

| 服务名 | 端口 | 说明 |
|--------|------|------|
| Retrieval Service | 8001 | 检索问答服务 |
| Context Memory | 3006 | 上下文记忆服务 |

