"""POST /upload 端点（联调用，受 INGESTION_UPLOAD_ENABLED 开关控制）。

Spec: docs/superpowers/specs/2026-04-27-upload-endpoint-design.md
"""
import re

MAX_FILENAME_LEN = 255
ILLEGAL_CHARS_RE = re.compile(r'[<>:"|?*\x00-\x1f]')


class PathTraversalError(ValueError):
    """文件名含路径穿越字符——安全级，应触发请求级 400 拒绝整批。"""


class InvalidFilenameError(ValueError):
    """文件名其它问题（空 / 长度 / 编码）——单文件级，应返 status=error 但其它继续。"""


def sanitize_filename(filename: str) -> str:
    """两层错误分类清理。优先级：安全级（PathTraversalError）→ 单文件级（InvalidFilenameError）→ 清理"""
    # 安全级最先（决定 PathTraversalError）
    if ".." in filename or "/" in filename or "\\" in filename:
        raise PathTraversalError(f"path traversal not allowed: {filename}")
    # 单文件级
    if not filename or not filename.strip():
        raise InvalidFilenameError("filename is empty")
    if len(filename) > MAX_FILENAME_LEN:
        raise InvalidFilenameError(f"filename too long ({len(filename)} > {MAX_FILENAME_LEN})")
    # 清理（不抛错）
    cleaned = ILLEGAL_CHARS_RE.sub("_", filename)
    return cleaned
