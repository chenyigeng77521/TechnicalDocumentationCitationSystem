import os
import re
from pathlib import Path


ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def fix_encoding(name: str) -> str:
    """修 latin1→utf-8 中文乱码（multipart filename 经常遭此）。无乱码时原样返回。"""
    try:
        repaired = name.encode("latin-1").decode("utf-8")
        return repaired
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def sanitize_filename(name: str) -> str:
    """清非法字符 + 空格→下划线，保留中文 / 数字 / 常见标点。"""
    name = name.strip()
    name = ILLEGAL_CHARS.sub("_", name)
    name = re.sub(r"\s+", "_", name)
    return name or "unnamed"


def _split_name_ext(name: str) -> tuple[str, str]:
    if "." not in name:
        return name, ""
    base, ext = name.rsplit(".", 1)
    return base, "." + ext


def dedupe_and_open(raw_dir: Path, filename: str) -> tuple[Path, int]:
    """原子地创建目标文件并返回 (path, fd)。若同名存在则加 `_N` 后缀。

    调用方负责 os.write(fd, ...) 和 os.close(fd)；若后续写入失败，必须 unlink 返回的 path。
    """
    base, ext = _split_name_ext(filename)
    candidate = filename
    i = 1
    while True:
        path = raw_dir / candidate
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            return path, fd
        except FileExistsError:
            candidate = f"{base}_{i}{ext}"
            i += 1
