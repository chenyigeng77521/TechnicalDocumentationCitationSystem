"""JSON line logger（每行一个 JSON record）。"""
import json
import logging
from pathlib import Path
from typing import Optional


class _JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k not in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            ):
                payload[k] = v
        return json.dumps(payload, ensure_ascii=False)


_loggers: dict[str, logging.Logger] = {}


def get_logger(name: str, log_file: Optional[Path] = None) -> logging.Logger:
    if name in _loggers:
        return _loggers[name]
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = _JsonLineFormatter()
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    else:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    logger.propagate = False
    _loggers[name] = logger
    return logger
