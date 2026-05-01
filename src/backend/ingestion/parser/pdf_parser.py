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
    import numpy as np

    def _run():
        # PaddleOCR 3.x API（2026-04-26 实测，参考 INTERFACE.md 部署章节）：
        # - 用 predict() 替代已 deprecated 的 ocr()
        # - 输入：numpy 数组 (H, W, 3 RGB)；不再支持 bytes 直传
        # - 输出：list[OCRResult]，OCRResult 是 dict-like，
        #         rec_texts: list[str] 是识别出的文字
        #         rec_scores: list[float] 是每条置信度
        ocr = PaddleOCR(use_textline_orientation=True, lang="ch")
        doc = fitz.open(path)
        all_text = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            # PyMuPDF pixmap → numpy 数组
            img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )
            # 4 通道 RGBA → 3 通道 RGB（OCR 不需要 alpha）
            if img_array.shape[2] == 4:
                img_array = img_array[:, :, :3]
            result = ocr.predict(img_array)
            page_text = ""
            if result and len(result) > 0:
                page_text = "\n".join(result[0].get('rec_texts', []))
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
