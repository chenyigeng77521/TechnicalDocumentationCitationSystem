"""POST /upload 端点测试。

Spec: docs/superpowers/specs/2026-04-27-upload-endpoint-design.md
"""
import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.ingestion.api.routes_upload import (
    sanitize_filename, PathTraversalError, InvalidFilenameError,
)


def test_sanitize_normal_filename():
    assert sanitize_filename("kubernetes部署.docx") == "kubernetes部署.docx"
    assert sanitize_filename("foo.pdf") == "foo.pdf"


def test_sanitize_path_traversal_raises_specific():
    for bad in ["../../etc/passwd", "foo/../../bar.docx", "/absolute/path", "evil\\path.docx"]:
        with pytest.raises(PathTraversalError):
            sanitize_filename(bad)


def test_sanitize_empty_raises_invalid():
    for bad in ["", "   ", "\t\n"]:
        with pytest.raises(InvalidFilenameError):
            sanitize_filename(bad)


def test_sanitize_max_length():
    long_name = "a" * 250 + ".docx"  # 255 chars
    assert sanitize_filename(long_name) == long_name

    with pytest.raises(InvalidFilenameError, match="too long"):
        sanitize_filename("a" * 256 + ".docx")


def test_sanitize_illegal_chars_replaced():
    assert sanitize_filename('foo<bar>baz?.docx') == 'foo_bar_baz_.docx'
    assert sanitize_filename('a|b*c.pdf') == 'a_b_c.pdf'
