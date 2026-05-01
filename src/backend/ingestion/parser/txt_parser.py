"""TXT 解析器。chardet 自动编码检测，低置信度时尝试常见中文编码。"""
from pathlib import Path
import chardet
from backend.ingestion.parser.types import ParseResult

# 低置信度时按顺序尝试的候选编码
_FALLBACK_ENCODINGS = ["utf-8", "gbk", "gb2312", "gb18030", "big5", "utf-16"]


def _decode_bytes(raw_bytes: bytes) -> str:
    detected = chardet.detect(raw_bytes)
    encoding = detected.get("encoding") or "utf-8"
    confidence = detected.get("confidence") or 0.0

    # 高置信度直接用
    if confidence >= 0.8:
        try:
            return raw_bytes.decode(encoding, errors="replace")
        except (LookupError, UnicodeDecodeError):
            pass

    # 低置信度：先尝试候选编码（严格模式，不 replace）
    for enc in _FALLBACK_ENCODINGS:
        try:
            return raw_bytes.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue

    # 最终兜底
    return raw_bytes.decode("utf-8", errors="replace")


async def parse(path: Path) -> ParseResult:
    raw_bytes = path.read_bytes()
    text = _decode_bytes(raw_bytes)
    return ParseResult(raw_text=text, title_tree=[], content_type="document")
