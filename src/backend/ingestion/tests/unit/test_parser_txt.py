import pytest
from backend.ingestion.parser.txt_parser import parse


@pytest.mark.asyncio
async def test_parse_utf8(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello 你好", encoding="utf-8")
    result = await parse(f)
    assert "你好" in result.raw_text


@pytest.mark.asyncio
async def test_parse_gbk(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes("中文测试".encode("gbk"))
    result = await parse(f)
    assert "中文" in result.raw_text
