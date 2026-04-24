#!/usr/bin/env python3
"""
知识库增量更新脚本

功能：
1. 检测 raw/ 目录变更
2. 调用大模型进行增量更新
3. 同步 wiki/ 与 raw/ 内容

使用方法：
    python update_wiki.py              # 正常运行
    python update_wiki.py --force      # 强制全量更新
    python update_wiki.py --config config.yaml  # 指定配置文件
"""
import sys
import argparse
from pathlib import Path

# 添加 scripts 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from logger import Logger
from config import AppConfig, PathConfig
from change_detector import ChangeDetector, ChangeResult
from llm_client import LLMClient
from file_executor import FileExecutor


class KnowledgeBaseUpdater:
    """知识库更新器主类"""

    def __init__(self, config_path: Path = None):
        # 加载配置
        if config_path and config_path.exists():
            self.config = AppConfig.from_yaml(config_path)
        else:
            self.config = AppConfig()

        # 初始化组件
        self.logger = Logger(
            log_file=self.config.paths.logs_path / "auto-update.log"
        )
        self.detector = ChangeDetector(self.config.paths, self.logger)
        self.llm_client = LLMClient(self.config, self.logger)
        self.executor = FileExecutor(self.config.paths, self.logger)

    def run(self, force_full: bool = False) -> int:
        """执行更新流程

        Args:
            force_full: 是否强制全量更新

        Returns:
            int: 0 成功，1 失败
        """
        self.logger.divider()
        self.logger.info("开始知识库增量更新")

        try:
            # 1. 检测变更
            if force_full:
                self.logger.info("强制全量更新模式")
                # 强制全量：获取所有 raw 文件
                result = ChangeResult(
                    status="FIRST_RUN",
                    changed_files=list(self._get_all_raw_files())
                )
            else:
                result = self.detector.detect()

            if result.status == "NO_RAW_DIR":
                self.logger.error("raw 目录不存在，退出")
                return 1

            if result.status == "NO_CHANGE":
                self.logger.info("无变更，跳过更新")
                return 0

            is_first_run = (result.status == "FIRST_RUN")

            if is_first_run:
                self.logger.info("首次运行模式（全量构建）")

            if not result.changed_files:
                self.logger.info("无变更文件，跳过更新")
                return 0

            self.logger.info(f"变更文件数量: {len(result.changed_files)}")
            for f in result.changed_files[:10]:  # 只显示前10个
                self.logger.debug(f"  - {f}")
            if len(result.changed_files) > 10:
                self.logger.debug(f"  ... 还有 {len(result.changed_files) - 10} 个文件")

            # 2. 调用大模型
            operations = self.llm_client.update_knowledge_base(
                result.changed_files,
                is_first_run
            )

            if not operations:
                self.logger.error("大模型返回空结果，更新失败")
                return 1

            # 3. 执行操作
            success = self.executor.execute(operations)

            if not success:
                self.logger.error("文件操作执行失败")
                return 1

            self.logger.info("知识库增量更新完成")
            return 0

        except KeyboardInterrupt:
            self.logger.info("用户中断")
            return 130
        except Exception as e:
            self.logger.error(f"更新过程中发生错误: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return 1
        finally:
            self.logger.divider()

    def _get_all_raw_files(self) -> set:
        """获取所有 raw 文件路径"""
        raw_path = self.config.paths.raw_path
        if not raw_path.exists():
            return set()

        files = set()
        for file_path in raw_path.rglob('*'):
            if file_path.is_file():
                rel_path = str(file_path.relative_to(self.config.paths.project_root))
                files.add(rel_path)
        return files


def main():
    parser = argparse.ArgumentParser(
        description='知识库增量更新工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python update_wiki.py                    # 正常运行
  python update_wiki.py --force            # 强制全量更新
  python update_wiki.py --config config.yaml  # 使用配置文件
  python update_wiki.py --verbose          # 详细输出
        """
    )
    parser.add_argument(
        '--config', '-c',
        type=Path,
        help='配置文件路径'
    )
    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='强制全量更新'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='详细输出'
    )

    args = parser.parse_args()

    # 如果没有指定配置文件，自动查找同目录下的 config.yaml
    config_path = args.config
    if not config_path:
        auto_config = Path(__file__).parent / "config.yaml"
        if auto_config.exists():
            config_path = auto_config

    # 创建更新器并运行
    updater = KnowledgeBaseUpdater(config_path=config_path)

    # 设置日志级别
    if args.verbose:
        updater.logger.logger.setLevel(10)  # DEBUG

    sys.exit(updater.run(force_full=args.force))


# 用于兼容旧的 bash 脚本调用
if __name__ == "__main__":
    main()