"""
日志模块
"""
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional


class Logger:
    """日志管理器"""

    def __init__(self, log_file: Optional[Path] = None, level: int = logging.INFO):
        self.log_file = log_file
        self.logger = logging.getLogger("knowledge_base_updater")
        self.logger.setLevel(level)
        self.logger.handlers.clear()

        # 格式化器
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        # 文件处理器
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

        # 回调列表（用于 SSE 等实时推送场景）
        self._callbacks: List[callable] = []

    def add_callback(self, callback: callable) -> None:
        """注册日志回调函数

        Args:
            callback: 接收 (level: str, message: str) 的回调函数
        """
        self._callbacks.append(callback)

    def remove_callback(self, callback: callable) -> None:
        """移除日志回调函数"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _notify(self, level: str, msg: str) -> None:
        """通知所有注册的回调"""
        for cb in self._callbacks:
            try:
                cb(level, msg)
            except Exception:
                pass

    def info(self, msg: str) -> None:
        self.logger.info(msg)
        self._notify("info", msg)

    def error(self, msg: str) -> None:
        self.logger.error(msg)
        self._notify("error", msg)

    def warning(self, msg: str) -> None:
        self.logger.warning(msg)
        self._notify("warning", msg)

    def debug(self, msg: str) -> None:
        self.logger.debug(msg)
        self._notify("debug", msg)

    def divider(self, char: str = "=", length: int = 60) -> None:
        """输出分隔线"""
        self.info(char * length)