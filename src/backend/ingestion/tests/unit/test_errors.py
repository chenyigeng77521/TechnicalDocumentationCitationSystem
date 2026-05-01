"""测试错误码 enum 与自定义 Exception。"""
import pytest
from backend.ingestion.common.errors import (
    ErrorType, IngestionError, ParseError, EmbeddingError, DBError,
    UnsupportedFormatError,
)


def test_error_type_enum_values():
    assert ErrorType.FILE_NOT_FOUND.value == "file_not_found"
    assert ErrorType.UNSUPPORTED_FORMAT.value == "unsupported_format"
    assert ErrorType.PARSE_FAILED.value == "parse_failed"
    assert ErrorType.EMBEDDING_TIMEOUT.value == "embedding_timeout"
    assert ErrorType.DB_ERROR.value == "db_error"


def test_parse_error_carries_type_and_detail():
    err = ParseError("PDF 加密")
    assert err.error_type == ErrorType.PARSE_FAILED
    assert err.detail == "PDF 加密"
    assert isinstance(err, IngestionError)


def test_unsupported_format_error_inherits():
    err = UnsupportedFormatError(".doc")
    assert err.error_type == ErrorType.UNSUPPORTED_FORMAT
    assert ".doc" in err.detail


def test_to_dict_format():
    err = EmbeddingError("超时 5 次重试")
    d = err.to_dict()
    assert d["status"] == "error"
    assert d["error_type"] == "embedding_timeout"
    assert d["detail"] == "超时 5 次重试"
