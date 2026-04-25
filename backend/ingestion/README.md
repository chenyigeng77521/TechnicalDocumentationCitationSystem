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
