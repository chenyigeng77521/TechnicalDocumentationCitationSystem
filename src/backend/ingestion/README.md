# backend/ingestion/ — Layer 1 数据处理层

## 启动

```bash
conda activate sqllineage
cd /Users/tuyh3/Desktop/Asiainfo/chenyigeng77521/TechnicalDocumentationCitationSystem
pip install -r backend/ingestion/requirements.txt
python -m backend.ingestion.api.server
```
监听 `:3003`

## 测试

```bash
cd backend/ingestion
pytest tests/unit -v
pytest tests/integration -v
```

## 设计文档
参考 `docs/superpowers/specs/2026-04-25-data-layer-design.md`

## ⚠️ 部署到评委环境（无外网）必须做的事

评委环境是 **x86 Linux + 无外网**。两个模型默认从公网下载，必须在打 Docker 镜像时**预先下载并打包进镜像**，否则首次启动直接崩。

### 模型来源 + 大小

| 模型 | 用途 | 大小 | 首次下载来源 | 缓存目录 |
|---|---|---|---|---|
| `BAAI/bge-m3` | embedding（写入+查询）| ~2 GB | HuggingFace | `~/.cache/huggingface/` |
| `PP-OCR-v5` | 扫描 PDF OCR 降级 | ~200 MB | 百度 BOS | `~/.paddlex/` |

### 预下载脚本（Dockerfile 构建阶段跑）

```bash
# 在有外网的构建机执行一次，模型自动缓存到 ~/.cache 和 ~/.paddlex
conda run -n sqllineage python -c "
from sentence_transformers import SentenceTransformer
SentenceTransformer('BAAI/bge-m3')
print('bge-m3 ready')
"

conda run -n sqllineage python -c "
from paddleocr import PaddleOCR
PaddleOCR(use_textline_orientation=True, lang='ch')
print('PaddleOCR ready')
"
```

### Dockerfile 关键步骤

```dockerfile
# 在 RUN pip install -r requirements.txt 之后追加
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(use_textline_orientation=True, lang='ch')"
# 模型现在在镜像 layer 里，无网也能跑
```

### GPU 注意

如果部署环境有 NVIDIA GPU，把 `paddlepaddle` 替换成 `paddlepaddle-gpu`（同版本范围 `>=3.3.1,<4.0.0`），速度提升 ~10x。CPU 版默认能跑，无 GPU 也不影响功能。

