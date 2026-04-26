"""
推理与引用层 (Reasoning Layer)
服务启动入口

v2 变更：
  - LLM 配置改由 .env 统一管理
  - 命令行新增 --provider 参数，可覆盖 yaml 中的 active_provider
  - 环境变量（LLM_API_KEY / LLM_MODEL / LLM_BASE_URL）优先级最高
"""

from __future__ import annotations
import os
import sys
import argparse
import logging

try:
    from dotenv import load_dotenv
    _DOTENV_AVAILABLE = True
except ImportError:
    load_dotenv = None  # type: ignore
    _DOTENV_AVAILABLE = False

from pathlib import Path
if _DOTENV_AVAILABLE:
    load_dotenv(Path(__file__).parent / '.env')

from flask import Flask

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)


def create_app(
    llm_api_key: str = None,
    llm_base_url: str = None,
    llm_model: str = None,
    llm_provider: str = None,
    score_threshold: float = None,
    fake_llm: bool = False,
) -> Flask:
    """
    创建 Flask 应用。

    LLM 配置优先级（从高到低）：
      1. 本函数的显式参数（llm_api_key / llm_model / llm_base_url）
      2. 环境变量（LLM_API_KEY / LLM_MODEL / LLM_BASE_URL / LLM_PROVIDER）
      3. .env 中 LLM_ACTIVE_PROVIDER 对应的配置块

    参数：
      llm_provider: 指定 provider 名称（glm5 / kimi / minimax / qwen / openai）
    """
    from .reasoning_pipeline import ReasoningPipelineConfig, LLMConfig
    from .webui import create_reasoning_web_ui

    cfg = ReasoningPipelineConfig()

    if fake_llm:
        logger.info("🧪 使用 Fake LLM 模式（不调用真实 API）")
        cfg.llm = None  # 使用内置 no-LLM 响应
    elif llm_api_key:
        # 显式传入 API KEY → 直接构造（跳过 yaml）
        cfg.llm = LLMConfig(
            api_key=llm_api_key,
            base_url=llm_base_url or '',
            model=llm_model or 'gpt-4-turbo',
            provider=llm_provider or 'custom',
        )
        logger.info(f"🤖 使用显式传入的 LLM 配置: model={cfg.llm.model!r}")
    else:
        # 从 .env 加载（provider 参数可覆盖 LLM_ACTIVE_PROVIDER）
        cfg.llm = LLMConfig.from_file(provider=llm_provider)

    if score_threshold is not None:
        cfg.score_threshold = score_threshold

    app = Flask(__name__)
    app.config['JSON_ENSURE_ASCII'] = False

    webui = create_reasoning_web_ui(cfg)
    bp = webui.create_blueprint()
    app.register_blueprint(bp)
    webui.register_websocket(app)

    return app


def run_test(fake_llm: bool = False):
    """运行测试查询"""
    from .reasoning_pipeline import create_reasoning_pipeline, ReasoningPipelineConfig
    from ._types import ReasoningRequest

    logger.info("🧪 运行测试查询...")
    pipeline = create_reasoning_pipeline()

    test_queries = [
        '如何提高混合检索召回率',
        '什么是 BM25 检索',
    ]

    for query in test_queries:
        logger.info(f"\n🔍 测试查询: {query}")
        try:
            chunks = pipeline.retrieve_chunks(query, top_k=3)
            logger.info(f"  检索到 {len(chunks)} 个 chunks")

            req = ReasoningRequest(query=query, chunks=chunks)
            resp = pipeline.reason(req)
            logger.info(f"  no_evidence={resp.no_evidence}, confidence={resp.confidence}")
            logger.info(f"  回答预览: {resp.answer[:100]}...")
        except Exception as e:
            logger.error(f"  ❌ 失败: {e}")


def main():
    parser = argparse.ArgumentParser(description='推理与引用层服务')
    parser.add_argument('--host', default='0.0.0.0', help='监听地址')
    parser.add_argument('--port', type=int, default=5050, help='监听端口')
    parser.add_argument('--fake-llm', action='store_true', help='使用 Fake LLM（测试模式）')
    parser.add_argument('--test', action='store_true', help='运行测试查询后退出')
    parser.add_argument('--score-threshold', type=float, default=None, help='拒答分数阈值')
    parser.add_argument(
        '--provider',
        default=None,
        help='指定 LLM provider（glm5/kimi/minimax/qwen/openai），覆盖 .env 中的 LLM_ACTIVE_PROVIDER',
    )
    args = parser.parse_args()

    # 环境变量（向后兼容，优先于 yaml，但低于 --provider 参数）
    llm_api_key = os.environ.get('LLM_API_KEY') or os.environ.get('OPENAI_API_KEY')
    llm_base_url = os.environ.get('LLM_BASE_URL') or os.environ.get('OPENAI_BASE_URL')
    llm_model = os.environ.get('LLM_MODEL')

    if args.test:
        run_test(args.fake_llm)
        return

    app = create_app(
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        llm_provider=args.provider,
        score_threshold=args.score_threshold,
        fake_llm=args.fake_llm,
    )

    logger.info(f"🚀 推理层服务启动: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == '__main__':
    main()
