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
import time
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

    def run(self, force_full: bool = False, daemon_mode: bool = False, interval: int = 300) -> int:
        """执行更新流程

        Args:
            force_full: 是否强制全量更新
            daemon_mode: 是否常驻模式
            interval: 常驻模式下的检测间隔（秒）

        Returns:
            int: 0 成功，1 失败，130 用户中断
        """
        if daemon_mode:
            self.logger.info(f"进入常驻模式，检测间隔: {interval} 秒，按 Ctrl+C 退出")

        try:
            while True:
                exit_code = self._run_once(force_full=force_full)

                if not daemon_mode:
                    return exit_code

                if exit_code == 0:
                    self.logger.info(f"本次检测完成，{interval} 秒后进入下一轮...")
                else:
                    self.logger.warning(f"本次执行异常（退出码: {exit_code}），{interval} 秒后重试...")

                time.sleep(interval)
                # 后续轮次恢复为增量检测
                force_full = False

        except KeyboardInterrupt:
            self.logger.info("用户中断")
            return 130

    def _run_once(self, force_full: bool = False) -> int:
        """执行单次更新流程"""
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
            raise
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

    def _resolve_file_paths(self, file_paths: list) -> list:
        """解析并补全文件路径

        如果传入的路径已存在于 project_root 下，直接使用；
        否则尝试在 raw_dir 下查找并补全前缀。

        Args:
            file_paths: 原始文件路径列表

        Returns:
            list: 补全后的文件路径列表
        """
        resolved = []
        for fp in file_paths:
            fp_path = Path(fp)
            if (self.config.paths.project_root / fp_path).exists():
                resolved.append(fp)
            else:
                # 尝试在 raw 目录下查找
                raw_candidate = self.config.paths.raw_dir / fp_path
                if (self.config.paths.project_root / raw_candidate).exists():
                    resolved.append(str(raw_candidate))
                else:
                    resolved.append(fp)
        return resolved

    def update_files(self, file_paths: list) -> dict:
        """更新指定文件对应的 wiki 内容（供外部调用）

        Args:
            file_paths: 文件路径列表，相对于 project_root
                        或相对于 raw_dir 的裸文件名

        Returns:
            dict: 包含 success、message、data 等字段的结果字典
        """
        self.logger.divider()
        self.logger.info(f"收到外部更新请求，文件数量: {len(file_paths)}")

        if not file_paths:
            self.logger.warning("文件列表为空")
            return {
                "success": False,
                "message": "文件列表不能为空",
                "data": None
            }

        # 解析路径（支持裸文件名自动补全 raw/ 前缀）
        file_paths = self._resolve_file_paths(file_paths)

        # 验证文件
        valid_files = []
        invalid_files = []
        for fp in file_paths:
            full_path = self.config.paths.project_root / fp
            if full_path.exists():
                valid_files.append(fp)
            else:
                invalid_files.append(fp)
                self.logger.warning(f"文件不存在: {fp}")

        if not valid_files:
            self.logger.error("所有指定的文件都不存在")
            return {
                "success": False,
                "message": "所有指定的文件都不存在",
                "data": None,
                "invalid_files": invalid_files
            }

        try:
            # 调用大模型
            operations = self.llm_client.update_knowledge_base(
                valid_files,
                is_first_run=False
            )

            if not operations:
                self.logger.error("大模型返回空结果，更新失败")
                return {
                    "success": False,
                    "message": "大模型返回空结果，更新失败",
                    "data": None,
                    "invalid_files": invalid_files
                }

            # 执行操作
            success = self.executor.execute(operations)

            if not success:
                self.logger.error("文件操作执行失败")
                return {
                    "success": False,
                    "message": "文件操作执行失败",
                    "data": None,
                    "invalid_files": invalid_files
                }

            # 更新状态文件，确保下次增量检测正确
            self.detector.update_state_for_files(valid_files)

            self.logger.info("指定文件更新完成")

            return {
                "success": True,
                "message": "更新完成",
                "data": {
                    "deleted_files": operations.get("deleted_files", []),
                    "updated_files": operations.get("updated_files", []),
                    "created_files": operations.get("created_files", []),
                    "files_content_keys": list(operations.get("files_content", {}).keys()),
                    "invalid_links": self.executor._validate_links()
                },
                "invalid_files": invalid_files
            }

        except Exception as e:
            self.logger.error(f"更新过程中发生错误: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": f"更新失败: {str(e)}",
                "data": None,
                "invalid_files": invalid_files
            }
        finally:
            self.logger.divider()


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
  python update_wiki.py --daemon           # 常驻模式
  python update_wiki.py -d -i 600          # 常驻模式，每10分钟检测一次
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
    parser.add_argument(
        '--daemon', '-d',
        action='store_true',
        help='常驻模式，循环检测变更'
    )
    parser.add_argument(
        '--interval', '-i',
        type=int,
        default=None,
        help='常驻模式检测间隔（秒），默认读取配置或 300'
    )
    parser.add_argument(
        '--serve', '-s',
        action='store_true',
        help='启动 REST API 服务，供第三方 HTTP 调用'
    )
    parser.add_argument(
        '--port', '-p',
        type=int,
        default=8080,
        help='REST API 服务端口（默认 8080）'
    )
    parser.add_argument(
        '--host',
        type=str,
        default='0.0.0.0',
        help='REST API 服务绑定地址（默认 0.0.0.0）'
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

    # 启动 REST API 服务
    if args.serve:
        updater.logger.info(f"启动 REST API 服务: http://{args.host}:{args.port}")
        from api_server import start_server
        start_server(updater, host=args.host, port=args.port)
        return

    # 确定间隔时间：命令行 > 配置文件 > 默认 300
    interval = args.interval if args.interval is not None else updater.config.interval

    sys.exit(updater.run(
        force_full=args.force,
        daemon_mode=args.daemon,
        interval=interval
    ))


# 用于兼容旧的 bash 脚本调用
if __name__ == "__main__":
    main()