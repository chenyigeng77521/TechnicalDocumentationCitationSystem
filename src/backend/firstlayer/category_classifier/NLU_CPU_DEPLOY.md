# NLU 模型部署文档

## 📦 模型说明

| 模型 | 用途 | 大小 | 设备 |
|------|------|------|------|
| **Qwen2.5-0.5B** | 指代消解 + 查询改写 | ~1GB | CPU/GPU |
| **chinese-roberta-wwm-ext** | 完整性检查 | ~500MB | CPU/GPU |

---

## 🚀 一键部署（推荐）

### 方式 1：使用部署脚本

```bash
cd /Users/chenyigeng/Library/Application\ Support/winclaw/.openclaw/workspace/TechnicalDocumentationCitationSystem/backend/firstlayer/category_classifier

# 执行一键部署
./deploy_nlu_models.sh
```

脚本会自动完成：
1. ✅ 安装 Python 依赖（huggingface_hub, transformers, torch）
2. ✅ 下载两个模型到 `backend/models/` 目录
3. ✅ 验证模型文件完整性

---

### 方式 2：手动部署

#### 1. 安装依赖

```bash
cd backend/firstlayer/category_classifier

# 安装所有依赖
pip3 install -r requirements.txt

# 或单独安装
pip3 install huggingface_hub>=0.20.0
pip3 install transformers>=4.36.0
pip3 install torch>=2.2.0
pip3 install accelerate>=0.26.0
```

#### 2. 下载模型

```bash
cd backend/firstlayer/category_classifier

# 运行下载脚本
python3 download_models.py
```

#### 3. 验证安装

```bash
# 检查模型目录
ls -lh backend/models/

# 应该看到：
# qwen2.5-0.5b/
# chinese-roberta-wwm-ext/
```

---

## 📁 目录结构

```
backend/
├── models/                           # 模型目录
│   ├── qwen2.5-0.5b/                # Qwen2.5-0.5B 模型
│   │   ├── config.json
│   │   ├── model.safetensors
│   │   ├── tokenizer.json
│   │   └── ...
│   ├── chinese-roberta-wwm-ext/     # 完整性检查模型
│   │   ├── config.json
│   │   ├── pytorch_model.bin
│   │   ├── tokenizer.json
│   │   └── ...
│   └── cache/                        # HuggingFace 缓存
│
└── firstlayer/category_classifier/
    ├── nlu/pipeline.py               # NLU 流水线（自动加载模型）
    ├── download_models.py            # 模型下载脚本
    ├── deploy_nlu_models.sh          # 一键部署脚本
    └── requirements.txt              # Python 依赖
```

---

## ⚙️ 自动加载

模型下载后，**无需手动配置**。NLU 流水线会自动检测并加载：

```python
# pipeline.py 自动检测模型路径
base_path = os.path.join(os.path.dirname(...), 'models')
self.rexnunlu_model_path = os.path.join(base_path, 'qwen2.5-0.5b')
self.turnsense_model_path = os.path.join(base_path, 'chinese-roberta-wwm-ext')
```

---

## 🧪 测试模型

```bash
cd backend/firstlayer/category_classifier

# 运行测试脚本
python3 test_nlu_models.py
```

预期输出：
```
✅ Qwen2.5-0.5B 模型加载完成！设备：cpu
✅ 完整性检查模型加载完成！设备：cpu

🧪 测试指代消解 (Qwen2.5-0.5B)
原始问题：它多少钱？
替换后：iPhone 15 多少钱？
是否替换：True

✅ 指代消解测试完成
```

---

## 🔄 重启服务

```bash
# 停止所有服务
./stopAll.sh

# 启动所有服务
./startAll.sh

# 查看模型加载日志
tail -f ./logs/backend.log | grep -E "Qwen|完整性检查"
```

预期日志：
```
🖥️  检测到 CPU 环境，启用 CPU 优化模式
🔄 正在加载 Qwen2.5-0.5B 模型：/path/to/qwen2.5-0.5b
✅ Qwen2.5-0.5B 模型加载完成！设备：cpu
🔄 正在加载完整性检查模型：/path/to/chinese-roberta-wwm-ext
✅ 完整性检查模型加载完成！设备：cpu
```

---

## 💻 CPU 优化

当前配置已针对 CPU 优化：

- ✅ **float32 精度**（避免 CPU 不支持 float16）
- ✅ **device_map="cpu"**（强制 CPU 运行）
- ✅ **num_beams=3**（减少搜索宽度，加快速度）
- ✅ **temperature=0.7**（平衡生成质量）

如需进一步优化，可修改 `pipeline.py`：

```python
# 启用 4bit 量化（减少内存占用）
self.use_4bit_quantization = True  # 在 .env 中设置 NLU_4BIT_QUANTIZATION=true
```

---

## 🐛 故障排查

### 问题 1：模型下载失败

**解决方案**:
```bash
# 使用国内镜像源
export HF_ENDPOINT=https://hf-mirror.com

# 重新下载
python3 download_models.py
```

### 问题 2：内存不足

**解决方案**:
```bash
# 方案 A：使用 4bit 量化
pip3 install bitsandbytes
# 修改 pipeline.py 启用量化

# 方案 B：分批加载模型
# 修改 pipeline.py，用完即卸载
```

### 问题 3：推理速度慢

**解决方案**:
```bash
# 方案 A：减小 max_length
# 修改 pipeline.py 中的 generate() 参数

# 方案 B：使用 ONNX Runtime
pip3 install optimum[onnxruntime]
```

---

## 📊 性能参考

| 任务 | CPU 时间 | 内存占用 |
|------|----------|----------|
| Qwen2.5-0.5B 推理 | 1-3 秒 | ~2GB |
| chinese-roberta 推理 | 0.1-0.5 秒 | ~500MB |

---

## 📚 相关文档

- [NLU_MODEL_DEPLOY.md](NLU_MODEL_DEPLOY.md) - 详细部署指南
- [NLU_GUIDE.md](../../../entrance/NLU_GUIDE.md) - NLU 使用指南
- [pipeline.py](nlu/pipeline.py) - 核心实现代码

---

**最后更新**: 2026-04-29  
**维护者**: WinClaw AI Team
