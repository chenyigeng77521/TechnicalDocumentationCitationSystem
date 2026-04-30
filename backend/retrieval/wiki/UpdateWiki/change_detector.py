"""
文件变更检测模块
"""
import json
import hashlib
from pathlib import Path
from typing import Tuple, List, Dict
from dataclasses import dataclass

from logger import Logger
from config import PathConfig


@dataclass
class ChangeResult:
    """变更检测结果"""
    status: str  # NO_CHANGE, FIRST_RUN, CHANGED, NO_RAW_DIR
    changed_files: List[str]


class ChangeDetector:
    """检测 raw/ 目录的文件变更"""

    def __init__(self, path_config: PathConfig, logger: Logger):
        self.path_config = path_config
        self.logger = logger
        self.raw_dir = path_config.raw_path
        self.state_file = path_config.state_path

    def _get_file_md5(self, file_path: Path) -> str:
        """计算文件 MD5"""
        md5_hash = hashlib.md5()
        try:
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    md5_hash.update(chunk)
        except (IOError, OSError) as e:
            self.logger.error(f"计算 MD5 失败 {file_path}: {e}")
            return ""
        return md5_hash.hexdigest()

    def _get_current_state(self) -> Dict[str, str]:
        """获取当前所有文件及其 MD5"""
        state: Dict[str, str] = {}

        if not self.raw_dir.exists():
            return state

        for file_path in self.raw_dir.rglob('*'):
            if file_path.is_file():
                rel_path = str(file_path.relative_to(self.path_config.project_root))
                state[rel_path] = self._get_file_md5(file_path)

        return state

    def _load_previous_state(self) -> Dict[str, str]:
        """加载之前的状态"""
        if not self.state_file.exists():
            return {}

        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            self.logger.warning(f"加载状态文件失败: {e}")
            return {}

    def _save_state(self, state: Dict[str, str]) -> None:
        """保存当前状态"""
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except IOError as e:
            self.logger.error(f"保存状态文件失败: {e}")

    def detect(self) -> ChangeResult:
        """检测变更"""
        if not self.raw_dir.exists():
            self.logger.warning(f"raw 目录不存在: {self.raw_dir}")
            return ChangeResult(status="NO_RAW_DIR", changed_files=[])

        current_state = self._get_current_state()
        previous_state = self._load_previous_state()

        # 首次运行
        if not previous_state:
            self.logger.info("首次运行，执行全量构建")
            changed_files = list(current_state.keys())
            self._save_state(current_state)
            return ChangeResult(status="FIRST_RUN", changed_files=changed_files)

        # 找出变更的文件
        changed_files: List[str] = []

        # 新增或修改的文件
        for file_path, md5 in current_state.items():
            if file_path not in previous_state or previous_state[file_path] != md5:
                changed_files.append(file_path)

        # 删除的文件
        for file_path in previous_state:
            if file_path not in current_state:
                changed_files.append(file_path)

        if not changed_files:
            self.logger.info("无变更")
            self._save_state(current_state)
            return ChangeResult(status="NO_CHANGE", changed_files=[])

        self.logger.info(f"检测到 {len(changed_files)} 个变更文件")
        for f in changed_files:
            self.logger.debug(f"  - {f}")

        self._save_state(current_state)
        return ChangeResult(status="CHANGED", changed_files=changed_files)

    def update_state_for_files(self, file_paths: List[str]) -> None:
        """为指定文件更新状态（MD5）

        Args:
            file_paths: 相对于 project_root 的文件路径列表
        """
        state = self._load_previous_state()

        for fp in file_paths:
            full_path = self.path_config.project_root / fp
            if full_path.exists():
                state[fp] = self._get_file_md5(full_path)
            elif fp in state:
                # 文件已删除，从状态中移除
                del state[fp]

        self._save_state(state)
        self.logger.info(f"已更新 {len(file_paths)} 个文件的状态")