# NLU 模型部署指南

本文档介绍如何部署和配置 NLU 流水线中的三个核心模型。

## 📦 模型列表

| 功能 | 模型名称 | 用途 | 推荐模型 |
|------|----------|------|----------|
| **指代消解** | RexUniNLU | 将代词（它、这个、那个）替换为具体实体 | [RexUniNLU](https://github.com/your-repo/rex-uninlu) |
| **查询改写** | SlimPLM | 优化用户查询，提高检索效果 | [SlimPLM Query Rewriting](https://github.com/your-repo/slimplm) |
| **完整性检查** | TurnSense | 判断问题是否完整，是否需要更多上下文 | [TurnSense](https://github.com/your-repo/turnsense) |

---

## 🔧 部署方案

### 方案 A：本地模型部署（推荐）

#### 1. 下载模型文件

```bash
# 创建模型目录
mkdir -p /Users/chenyigeng/models/nlu

# 下载 RexUniNLU 模型
cd /Users/chenyigeng/models/nlu
git clone https://huggingface.co/your-repo/rex-uninlu

# 下载 SlimPLM 模型
git clone https://huggingface.co/your-repo/slimplm-query-rewriting

# 下载 TurnSense 模型
git clone https://huggingface.co/your-repo/turnsense
```

#### 2. 配置环境变量

编辑 `backend/entrance/.env` 文件：

```bash
# NLU 模型路径配置（本地模式）
REXUNINLU_MODEL_PATH=/Users/chenyigeng/models/nlu/rex-uninlu
SLIMPLM_MODEL_PATH=/Users/chenyigeng/models/nlu/slimplm-query-rewriting
TURNSENSE_MODEL_PATH=/Users/chenyigeng/models/nlu/turnsense

# API 模式留空（不使用）
REXUNINLU_API_URL=
SLIMPLM_API_URL=
TURNSENSE_API_URL=
```

#### 3. 重启服务

```bash
cd /Users/chenyigeng/Library/Application\ Support/winclaw/.openclaw/workspace/TechnicalDocumentationCitationSystem
./stopAll.sh
./startAll.sh
```

#### 4. 验证模型加载

查看日志，确认模型成功加载：

```bash
tail -f ./logs/backend.log | grep -E "RexUniNLU|SlimPLM|TurnSense"
```

预期输出：
```
✅ RexUniNLU 模型加载完成！设备：cuda
✅ SlimPLM 模型加载完成！设备：cuda
✅ TurnSense 模型加载完成！设备：cuda
```

---

### 方案 B：API 模式部署

如果模型已经部署为 HTTP 服务，可以使用 API 模式。

#### 1. 部署模型服务

每个模型需要部署为独立的 HTTP 服务，接收 JSON 请求并返回 JSON 响应。

**RexUniNLU API 接口规范**:
```json
POST http://localhost:8001/resolve
{
  "question": "它多少钱？",
  "context": "用户：我想了解 iPhone 15 的价格。助手：iPhone 15 售价 5999 元起。"
}

Response:
{
  "success": true,
  "resolved_question": "iPhone 15 多少钱？"
}
```

**SlimPLM API 接口规范**:
```json
POST http://localhost:8002/rewrite
{
  "question": "怎么申请？"
}

Response:
{
  "success": true,
  "rewritten_question": "如何申请员工年假？"
}
```

**TurnSense API 接口规范**:
```json
POST http://localhost:8003/check
{
  "question": "申请"
}

Response:
{
  "success": false,
  "is_complete": false,
  "message": "问题不完整，请提供更多上下文信息"
}
```

#### 2. 配置环境变量

编辑 `backend/entrance/.env` 文件：

```bash
# NLU 模型路径配置（本地模式留空）
REXUNINLU_MODEL_PATH=
SLIMPLM_MODEL_PATH=
TURNSENSE_MODEL_PATH=

# API 模式配置
REXUNINLU_API_URL=http://localhost:8001/resolve
SLIMPLM_API_URL=http://localhost:8002/rewrite
TURNSENSE_API_URL=http://localhost:8003/check
```

#### 3. 重启服务

```bash
./stopAll.sh
./startAll.sh
```

---

## 🧪 测试模型调用

### 测试指代消解

```bash
curl -X POST http://localhost:3002/api/nlu/test-retrieval \
  -H "Content-Type: application/json" \
  -d '{
    "question": "它多少钱？",
    "session_id": "test-session-123"
  }'
```

### 测试查询改写

```bash
curl -X POST http://localhost:3004/api/nlu/rewrite-query \
  -H "Content-Type: application/json" \
  -d '{"question": "怎么申请？"}'
```

### 测试完整性检查

```bash
curl -X POST http://localhost:3004/api/nlu/check-completeness \
  -H "Content-Type: application/json" \
  -d '{"question": "申请"}'
```

---

## 📊 性能优化建议

### GPU 加速

如果系统有 NVIDIA GPU，确保安装 CUDA 和 cuDNN：

```bash
# 检查 GPU 可用性
python3 -c "import torch; print(f'GPU 可用：{torch.cuda.is_available()}'); print(f'GPU 名称：{torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')"
```

### 模型量化（减少内存占用）

```python
# 在 pipeline.py 中添加量化配置
from transformers import BitsAndBytesConfig

quantization_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16
)

model = AutoModelForSeq2SeqLM.from_pretrained(
    model_path,
    quantization_config=quantization_config,
    device_map="auto"
)
```

### 批量推理

如果并发请求较多，考虑实现批量推理：

```python
def batch_inference(self, questions: List[str]) -> List[str]:
    """批量推理（提高吞吐量）"""
    inputs = self.tokenizer(questions, padding=True, truncation=True, return_tensors="pt")
    outputs = self.model.generate(**inputs)
    return self.tokenizer.batch_decode(outputs, skip_special_tokens=True)
```

---

## 🔍 故障排查

### 问题 1：模型加载失败

**症状**: `❌ RexUniNLU 模型加载失败：...`

**解决方案**:
1. 检查模型路径是否正确
2. 确认模型文件完整（包含 `config.json`, `pytorch_model.bin`, `tokenizer.json`）
3. 检查磁盘空间是否充足

### 问题 2：GPU 内存不足

**症状**: `CUDA out of memory`

**解决方案**:
1. 使用模型量化（4bit/8bit）
2. 减小 `max_length` 参数
3. 使用 CPU 模式（设置 `device = torch.device("cpu")`）

### 问题 3：推理速度慢

**症状**: 单次推理超过 5 秒

**解决方案**:
1. 确保使用 GPU（检查日志中的 `设备：cuda`）
2. 启用模型缓存
3. 使用 ONNX Runtime 优化

---

## 📝 降级方案

如果模型无法部署，系统会自动降级到规则模式：

| 功能 | 降级方案 | 效果 |
|------|----------|------|
| 指代消解 | 简单规则替换 | ⭐⭐ 基础效果 |
| 查询改写 | 正则表达式替换 | ⭐⭐⭐ 中等效果 |
| 完整性检查 | 规则快速过滤 | ⭐⭐⭐⭐ 较好效果 |

系统会打印警告日志：
```
⚠️  使用规则模式进行指代替换（降级方案）
```

---

## 📚 参考资料

- [RexUniNLU GitHub](https://github.com/your-repo/rex-uninlu)
- [SlimPLM Paper](https://arxiv.org/abs/xxxx.xxxxx)
- [TurnSense Documentation](https://your-docs.com/turnsense)
- [Hugging Face Transformers](https://huggingface.co/docs/transformers)

---

**最后更新**: 2026-04-29  
**维护者**: WinClaw AI Team
