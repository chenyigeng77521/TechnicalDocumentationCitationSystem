"""错误码 + 自定义 Exception 树。"""
from enum import Enum


class ErrorType(str, Enum):
    FILE_NOT_FOUND = "file_not_found"
    UNSUPPORTED_FORMAT = "unsupported_format"
    PARSE_FAILED = "parse_failed"
    EMBEDDING_TIMEOUT = "embedding_timeout"
    DB_ERROR = "db_error"


class IngestionError(Exception):
    error_type: ErrorType = ErrorType.DB_ERROR

    def __init__(self, detail: str = ""):
        super().__init__(detail)
        self.detail = detail

    def to_dict(self) -> dict:
        return {
            "status": "error",
            "error_type": self.error_type.value,
            "detail": self.detail,
        }


class ParseError(IngestionError):
    error_type = ErrorType.PARSE_FAILED


class EmbeddingError(IngestionError):
    error_type = ErrorType.EMBEDDING_TIMEOUT


class DBError(IngestionError):
    error_type = ErrorType.DB_ERROR


class UnsupportedFormatError(IngestionError):
    error_type = ErrorType.UNSUPPORTED_FORMAT

    def __init__(self, ext: str):
        super().__init__(f"不支持的扩展名: {ext}")
