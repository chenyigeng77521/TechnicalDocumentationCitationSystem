from app.retriever.bm25 import bm25_search


def test_bm25_chinese_tokenize_recall():
    chunks = [
        {"id": "1", "content": "北京的天气很好。"},
        {"id": "2", "content": "上海有东方明珠塔。"},
        {"id": "3", "content": "广州是南方城市。"},
    ]
    results = bm25_search("北京天气", chunks, k=3)
    assert results[0][0]["id"] == "1"


def test_bm25_empty_query_returns_empty():
    chunks = [{"id": "1", "content": "anything"}]
    assert bm25_search("", chunks, k=5) == []


def test_bm25_k_limit():
    chunks = [{"id": str(i), "content": f"关键词 content {i}"} for i in range(10)]
    results = bm25_search("关键词", chunks, k=3)
    assert len(results) <= 3
