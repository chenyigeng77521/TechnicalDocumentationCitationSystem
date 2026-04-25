"""PDF 解析器。

主路径：PyMuPDF 提取文字
降级路径：文字为空时调 PaddleOCR
"""
from pathlib import Path
import fitz  # PyMuPDF
from backend.ingestion.parser.types import ParseResult


def _extract_text_pymupdf(path: Path) -> tuple[str, int]:
    """返回 (文本, 页数)。"""
    doc = fitz.open(path)
    pages = doc.page_count
    parts = []
    for page in doc:
        parts.append(page.get_text())
    doc.close()
    return "\n\n".join(parts), pages


async def _ocr_pdf(path: Path) -> str:
    """调 PaddleOCR 识别。CPU 模式可跑，但慢。"""
    from paddleocr import PaddleOCR
    import asyncio

    def _run():
        ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        doc = fitz.open(path)
        all_text = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            result = ocr.ocr(img_bytes, cls=True)
            page_text = "\n".join(
                line[1][0] for block in (result or []) for line in (block or [])
            )
            all_text.append(page_text)
        doc.close()
        return "\n\n".join(all_text)

    return await asyncio.to_thread(_run)


async def parse(path: Path) -> ParseResult:
    text, pages = _extract_text_pymupdf(path)
    is_scanned = len(text.strip()) == 0
    if is_scanned:
        text = await _ocr_pdf(path)
    return ParseResult(
        raw_text=text,
        title_tree=[],   # PDF 不抽 heading（MVP）
        content_type="document",
        metadata={"pdf_pages": pages, "pdf_is_scanned": is_scanned},
    )
