"""
推理与引用层 (Reasoning Layer)
服务启动入口
对齐 TypeScript: backend/chunking-rag/src/server.ts（部分）
"""

from __future__ import annotations
import os
import sys
import argparse
import logging

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
    score_threshold: float = None,
    fake_llm: bool = False,
) -> Flask:
    """创建 Flask 应用"""
    from .reasoning_pipeline import ReasoningPipelineConfig, LLMConfig
    from .webui import create_reasoning_web_ui

    cfg = ReasoningPipelineConfig()

    # LLM 配置
    if fake_llm:
        logger.info("🧪 使用 Fake LLM 模式（不调用真实 API）")
        cfg.llm = None  # 使用内置 no-LLM 响应
    elif llm_api_key:
        cfg.llm = LLMConfig(
            api_key=llm_api_key,
            base_url=llm_base_url,
            model=llm_model or 'gpt-4-turbo',
        )

    if score_threshold is not None:
        cfg.score_threshold = score_threshold

    # 创建应用
    app = Flask(__name__)
    app.config['JSON_ENSURE_ASCII'] = False

    webui = create_reasoning_web_ui(cfg)
    bp = webui.create_blueprint()
    app.register_blueprint(bp)

    # 注册 WebSocket（依赖 flask-sock）
    webui.register_websocket(app)

    return app


def run_test(fake_llm: bool = False):
    """运行测试查询"""
    from .reasoning_pipeline import create_reasoning_pipeline, ReasoningPipelineConfig
    from .types import ReasoningRequest

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
    args = parser.parse_args()

    # 从环境变量读取 LLM 配置
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
        score_threshold=args.score_threshold,
        fake_llm=args.fake_llm,
    )

    logger.info(f"🚀 推理层服务启动: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == '__main__':
    main()
