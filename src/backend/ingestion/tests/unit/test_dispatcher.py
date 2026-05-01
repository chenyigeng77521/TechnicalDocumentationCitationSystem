"""测试解析器分派。"""
import pytest
from backend.ingestion.parser.dispatcher import parse_document, get_parser_name
from backend.ingestion.common.errors import UnsupportedFormatError


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_dispatch_md(tmp_path):
    f = _write(tmp_path, "a.md", "# hello\nworld")
    assert get_parser_name(f) == "markdown"


def test_dispatch_txt(tmp_path):
    f = _write(tmp_path, "a.txt", "plain text")
    assert get_parser_name(f) == "txt"


def test_dispatch_html(tmp_path):
    f = _write(tmp_path, "a.html", "<p>hello</p>")
    assert get_parser_name(f) == "html"


def test_dispatch_pdf(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4 fake")
    assert get_parser_name(tmp_path / "a.pdf") == "pdf"


def test_dispatch_docx(tmp_path):
    (tmp_path / "a.docx").write_bytes(b"PK\x03\x04 fake")
    assert get_parser_name(tmp_path / "a.docx") == "docx"


def test_dispatch_unsupported_raises(tmp_path):
    (tmp_path / "a.exe").write_bytes(b"\x00")
    with pytest.raises(UnsupportedFormatError):
        get_parser_name(tmp_path / "a.exe")
