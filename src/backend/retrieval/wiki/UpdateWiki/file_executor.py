"""
文件操作执行模块
"""
import re
from pathlib import Path
from typing import Dict, List
from datetime import datetime

from logger import Logger
from config import PathConfig


class FileExecutor:
    """执行文件操作"""

    def __init__(self, path_config: PathConfig, logger: Logger):
        self.path_config = path_config
        self.logger = logger
        self.wiki_dir = path_config.wiki_path
        self.log_path = self.wiki_dir / "log.md"

    def _get_current_timestamp(self) -> str:
        """获取当前时间戳"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _append_to_log(self, log_entry: str) -> None:
        """追加内容到 log.md"""
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(f"\n{log_entry}\n")
        except IOError as e:
            self.logger.error(f"写入 log.md 失败: {e}")

    def _validate_links(self) -> List[str]:
        """验证 wiki 目录中的链接有效性"""
        invalid_links: List[str] = []

        index_path = self.wiki_dir / "index.md"
        if not index_path.exists():
            return invalid_links

        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 查找 Markdown 链接: [text](path)
            links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content)

            for text, link in links:
                # 跳过外部链接和锚点链接
                if link.startswith(('http', '#', 'mailto:')):
                    continue

                link_path = self.wiki_dir / link
                if not link_path.exists():
                    invalid_links.append(link)
                    self.logger.warning(f"无效链接: {link}")

        except IOError as e:
            self.logger.error(f"读取 index.md 失败: {e}")

        return invalid_links

    def execute(self, operations: Dict) -> bool:
        """执行大模型返回的操作

        Returns:
            bool: 是否执行成功
        """
        if not operations:
            self.logger.warning("无操作需要执行")
            return False

        deleted = operations.get("deleted_files", [])
        files_content = operations.get("files_content", {})
        index_content = operations.get("index_content", "")
        log_entry = operations.get("log_entry", "")

        # 1. 删除文件
        for file_name in deleted:
            file_path = self.wiki_dir / file_name
            if file_path.exists():
                try:
                    file_path.unlink()
                    self.logger.info(f"删除文件: {file_name}")
                except OSError as e:
                    self.logger.error(f"删除文件失败 {file_name}: {e}")
            else:
                self.logger.debug(f"文件不存在，跳过删除: {file_name}")

        # 2. 创建/更新文件
        for file_name, content in files_content.items():
            if not content:
                self.logger.warning(f"文件 {file_name} 内容为空，跳过")
                continue

            file_path = self.wiki_dir / file_name
            try:
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)

                action = "创建" if not file_path.exists() else "更新"
                self.logger.info(f"{action}文件: {file_name}")
            except IOError as e:
                self.logger.error(f"写入文件失败 {file_name}: {e}")

        # 3. 更新 index.md
        if index_content:
            index_path = self.wiki_dir / "index.md"
            try:
                with open(index_path, 'w', encoding='utf-8') as f:
                    f.write(index_content)
                self.logger.info("更新 index.md")
            except IOError as e:
                self.logger.error(f"更新 index.md 失败: {e}")

        # 4. 更新 log.md
        if log_entry:
            timestamp = self._get_current_timestamp()
            formatted_log = f"## [{timestamp}] 更新记录\n\n{log_entry}\n"
            self._append_to_log(formatted_log)
            self.logger.info("更新 log.md")

        # 5. 验证链接
        invalid_links = self._validate_links()
        if invalid_links:
            self.logger.warning(f"发现 {len(invalid_links)} 个无效链接")

        self.logger.info("文件操作执行完成")
        return True

    def cleanup_orphaned_files(self) -> List[str]:
        """清理孤立文件（没有在 raw 中对应的 wiki 文件）

        Returns:
            List[str]: 被删除的文件列表
        """
        # 此方法保留用于手动清理
        # 实际清理由大模型判断
        return []