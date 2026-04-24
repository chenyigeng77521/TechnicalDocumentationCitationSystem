# knowledge_api.py - 修复后的完整版本
"""
知识库查询 HTTP 服务 - 直接调用大模型 API
大模型根据规则只读取 wiki/ 目录，不使用训练数据
"""

import os
import json
import asyncio
from typing import Optional, List, Dict, Any
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
import uvicorn
from datetime import datetime
import logging
from pathlib import Path
from dotenv import load_dotenv
import time

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==================== 数据模型 ====================

class QueryRequest(BaseModel):
    """查询请求模型"""
    query: str = Field(..., description="查询内容", example="AUTH CRBT USER 说明")
    timeout: int = Field(default=60, description="超时时间(秒)", ge=10, le=300)
    return_raw: bool = Field(default=False, description="是否返回原始输出")


class QueryResponse(BaseModel):
    """查询响应模型"""
    success: bool
    query: str
    answer: Optional[str] = None
    raw_output: Optional[str] = None
    error: Optional[str] = None
    execution_time: float
    timestamp: str
    sources: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    version: str
    timestamp: str
    wiki_dir_exists: bool
    wiki_files_count: int
    llm_available: bool


# ==================== 配置 ====================

class Config:
    """服务配置"""
    # 工作目录配置
    WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", os.getcwd())
    WIKI_DIR_NAME = os.getenv("WIKI_DIR_NAME", "wiki")
    RAW_DIR_NAME = os.getenv("RAW_DIR_NAME", "raw")

    # 大模型 API 配置
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "gpt-3.5-turbo")

    # 服务配置
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"

    # 缓存配置
    CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))

    # 安全配置
    API_KEY = os.getenv("API_KEY", None)
    ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")


config = Config()


# ==================== Wiki 目录读取器 ====================

class WikiReader:
    """读取 wiki 目录中的所有文件"""

    def __init__(self, workspace_dir: str, wiki_dir_name: str):
        self.wiki_path = Path(workspace_dir) / wiki_dir_name
        self.content_cache = None
        self.file_list_cache = None

    def get_all_files(self) -> List[str]:
        """获取所有文件路径"""
        if self.file_list_cache is not None:
            return self.file_list_cache

        files = []
        if not self.wiki_path.exists():
            logger.warning(f"wiki 目录不存在: {self.wiki_path}")
            return files

        for file_path in self.wiki_path.rglob("*"):
            if file_path.is_file() and file_path.suffix in ['.md', '.txt', '.rst', '.html']:
                rel_path = file_path.relative_to(self.wiki_path)
                files.append(str(rel_path))

        self.file_list_cache = files
        return files

    def get_all_content(self) -> str:
        """获取 wiki 目录中所有文件的内容"""
        if self.content_cache is not None:
            return self.content_cache

        if not self.wiki_path.exists():
            return f"错误：wiki 目录不存在 ({self.wiki_path})"

        all_content = []
        files_loaded = []

        for file_path in self.wiki_path.rglob("*"):
            if file_path.is_file() and file_path.suffix in ['.md', '.txt', '.rst', '.html']:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()

                    rel_path = file_path.relative_to(self.wiki_path)
                    all_content.append(f"\n## 文件: {rel_path}\n\n{content}\n")
                    files_loaded.append(str(rel_path))
                    logger.info(f"已加载: {rel_path}")
                except Exception as e:
                    logger.error(f"读取文件失败 {file_path}: {e}")

        if not all_content:
            return f"wiki 目录中没有找到任何文档文件: {self.wiki_path}"

        header = f"# 知识库内容\n\n共有 {len(files_loaded)} 个文档文件：\n\n"
        for f in files_loaded:
            header += f"- {f}\n"
        header += "\n---\n"

        self.content_cache = header + "\n".join(all_content)
        self.file_list_cache = files_loaded

        logger.info(f"已加载 {len(files_loaded)} 个文件到缓存")
        return self.content_cache

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        if not self.wiki_path.exists():
            return {
                "exists": False,
                "path": str(self.wiki_path),
                "files_count": 0,
                "files": []
            }

        files = self.get_all_files()
        return {
            "exists": True,
            "path": str(self.wiki_path),
            "files_count": len(files),
            "files": files[:50]
        }

    def refresh(self):
        """刷新缓存"""
        self.content_cache = None
        self.file_list_cache = None
        logger.info("Wiki 缓存已刷新")


# ==================== 大模型客户端 ====================

class LLMClient:
    """大模型 API 客户端 - 强制使用 wiki 内容"""

    def __init__(self, wiki_reader: WikiReader):
        self.wiki_reader = wiki_reader
        self.cache = {}

    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        return """你是一个知识库查询助手。请严格遵守以下规则：

## 核心规则（必须100%遵守）：
1. **只使用下面【知识库内容】中的信息**，绝对不要使用你的训练数据中的知识
2. 如果【知识库内容】中没有相关信息，必须直接说"知识库中暂无此信息"
3. 回答时必须说明信息来源（文件名）
4. 不要编造任何信息

## 回答格式：
- 先说明在哪个文件找到了信息
- 然后给出具体答案
- 最后列出信息来源
"""

    def _build_user_prompt(self, query: str, wiki_content: str) -> str:
        """构建用户提示词"""
        # 限制内容长度，避免超过 token 限制
        max_content_length = 8000
        if len(wiki_content) > max_content_length:
            wiki_content = wiki_content[:max_content_length] + "\n\n... (内容过长，已截断)"

        return f"""## 知识库内容：
{wiki_content}

## 用户问题：
{query}

请基于上述【知识库内容】回答问题。如果内容中没有相关信息，请直接说"知识库中暂无此信息"。
"""

    async def query(self, query: str, timeout: int = 60) -> Dict[str, Any]:
        """执行查询"""
        start_time = time.time()

        # 获取 wiki 内容
        wiki_content = self.wiki_reader.get_all_content()

        # 构建 prompts
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(query, wiki_content)

        logger.info(f"查询: {query[:50]}...")
        logger.info(f"Wiki 内容长度: {len(wiki_content)} 字符")

        try:
            # 尝试导入 OpenAI
            from openai import OpenAI

            client = OpenAI(
                api_key=config.LLM_API_KEY,
                base_url=config.LLM_BASE_URL,
                timeout=timeout
            )

            response = client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=2000
            )

            answer = response.choices[0].message.content
            execution_time = time.time() - start_time

            logger.info(f"查询成功，耗时 {execution_time:.2f}s")

            # 提取来源
            sources = self._extract_sources(answer)

            return {
                "success": True,
                "answer": answer,
                "raw_output": response.model_dump_json(),
                "error": None,
                "execution_time": execution_time,
                "sources": sources
            }

        except ImportError:
            error_msg = "请先安装 openai 包: pip install openai"
            logger.error(error_msg)
            return {
                "success": False,
                "answer": None,
                "raw_output": None,
                "error": error_msg,
                "execution_time": time.time() - start_time,
                "sources": []
            }

        except Exception as e:
            logger.exception(f"大模型调用失败")
            return {
                "success": False,
                "answer": None,
                "raw_output": None,
                "error": str(e),
                "execution_time": time.time() - start_time,
                "sources": []
            }

    def _extract_sources(self, answer: str) -> List[str]:
        """从答案中提取来源文件名"""
        sources = []

        # 匹配文件名模式
        import re
        patterns = [
            r'`?([^`\s]+\.(?:md|txt|rst|html))`?',
            r'文件[：:]\s*([^\n]+)',
            r'来源[：:]\s*([^\n]+)',
            r'在\s*`?([^`\n]+\.md)`?',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, answer, re.IGNORECASE)
            for m in matches:
                filename = m.strip().rstrip('》').rstrip('>')
                if filename and len(filename) < 200 and '/' not in filename:
                    sources.append(filename)

        # 去重
        unique_sources = []
        for s in sources:
            if s not in unique_sources:
                unique_sources.append(s)

        return unique_sources[:10]

    async def query_with_cache(self, query: str, timeout: int = 60, use_cache: bool = True) -> Dict[str, Any]:
        """带缓存的查询"""
        cache_key = f"{query}:{timeout}"

        if use_cache and cache_key in self.cache:
            cache_entry = self.cache[cache_key]
            if (datetime.now() - cache_entry['timestamp']).seconds < config.CACHE_TTL:
                logger.info(f"返回缓存结果: {query[:50]}...")
                return cache_entry['data']

        result = await self.query(query, timeout)

        if use_cache and result['success']:
            self.cache[cache_key] = {
                'data': result,
                'timestamp': datetime.now()
            }

        return result

    def clear_cache(self):
        """清空缓存"""
        self.cache.clear()
        logger.info("缓存已清空")


# ==================== FastAPI 应用 ====================

app = FastAPI(
    title="知识库查询 API",
    description="大模型查询 wiki 目录 - 只使用 wiki/ 目录内容，不使用训练数据",
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局实例
wiki_reader = WikiReader(config.WORKSPACE_DIR, config.WIKI_DIR_NAME)
llm_client = LLMClient(wiki_reader)


# ==================== 中间件 ====================

@app.middleware("http")
async def api_key_auth(request, call_next):
    """API 密钥认证（可选）"""
    if config.API_KEY:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return await call_next(request)

        token = auth_header.replace("Bearer ", "")
        if token != config.API_KEY:
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid API key"}
            )

    return await call_next(request)


@app.middleware("http")
async def log_requests(request, call_next):
    """请求日志"""
    start_time = datetime.now()
    response = await call_next(request)
    duration = (datetime.now() - start_time).total_seconds()
    logger.info(f"{request.method} {request.url.path} - {duration:.3f}s")
    return response


# ==================== API 端点 ====================

@app.get("/", response_model=HealthResponse)
async def root():
    """根路径，健康检查"""
    stats = wiki_reader.get_stats()
    return HealthResponse(
        status="ok",
        version="3.0.0",
        timestamp=datetime.now().isoformat(),
        wiki_dir_exists=stats["exists"],
        wiki_files_count=stats["files_count"],
        llm_available=bool(config.LLM_API_KEY)
    )


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查端点"""
    stats = wiki_reader.get_stats()
    return HealthResponse(
        status="ok",
        version="3.0.0",
        timestamp=datetime.now().isoformat(),
        wiki_dir_exists=stats["exists"],
        wiki_files_count=stats["files_count"],
        llm_available=bool(config.LLM_API_KEY)
    )


@app.post("/query", response_model=QueryResponse)
async def query_knowledge_base(request: QueryRequest):
    """
    查询知识库 - 大模型根据规则从 wiki 目录查找

    规则：
    1. 只读取 wiki/ 目录下的文件
    2. 不使用训练数据中的知识
    3. 以 wiki/ 目录中的内容为准
    4. 如果 wiki/ 中没有相关信息，明确告知
    5. 必须说明来源
    """
    logger.info(f"收到查询: {request.query}")

    # 检查 wiki 目录
    stats = wiki_reader.get_stats()
    if not stats["exists"]:
        return QueryResponse(
            success=False,
            query=request.query,
            answer=None,
            error=f"Wiki 目录不存在: {config.WORKSPACE_DIR}/{config.WIKI_DIR_NAME}",
            execution_time=0,
            timestamp=datetime.now().isoformat(),
            sources=[],
            metadata={"error_type": "wiki_not_found"}
        )

    if stats["files_count"] == 0:
        return QueryResponse(
            success=False,
            query=request.query,
            answer=f"知识库中暂无「{request.query}」的相关信息。\n\n原因：wiki 目录为空。\n\n建议：请将文档放入 {config.WORKSPACE_DIR}/{config.WIKI_DIR_NAME}/ 目录后重试。",
            error=None,
            execution_time=0,
            timestamp=datetime.now().isoformat(),
            sources=[],
            metadata={"files_count": 0}
        )

    # 检查 LLM 配置
    if not config.LLM_API_KEY:
        return QueryResponse(
            success=False,
            query=request.query,
            answer=None,
            error="未配置大模型 API Key，请设置 LLM_API_KEY 环境变量",
            execution_time=0,
            timestamp=datetime.now().isoformat(),
            sources=[],
            metadata={"error_type": "llm_not_configured"}
        )

    # 调用大模型
    result = await llm_client.query_with_cache(
        request.query,
        request.timeout,
        use_cache=not request.return_raw
    )

    # 判断是否使用了缓存
    cache_key = f"{request.query}:{request.timeout}"
    is_cached = cache_key in llm_client.cache

    return QueryResponse(
        success=result['success'],
        query=request.query,
        answer=result.get('answer'),
        raw_output=result.get('raw_output') if request.return_raw else None,
        error=result.get('error'),
        execution_time=result['execution_time'],
        timestamp=datetime.now().isoformat(),
        sources=result.get('sources', []),
        metadata={
            "files_in_wiki": stats["files_count"],
            "wiki_path": stats["path"],
            "cached": is_cached and not request.return_raw
        }
    )


@app.post("/query/stream")
async def query_knowledge_base_stream(request: QueryRequest):
    """流式查询知识库（Server-Sent Events）"""

    async def generate():
        try:
            yield f"data: {json.dumps({'type': 'start', 'query': request.query})}\n\n"

            # 获取 wiki 内容
            stats = wiki_reader.get_stats()

            if stats["files_count"] == 0:
                yield f"data: {json.dumps({'type': 'error', 'error': 'wiki目录为空'})}\n\n"
                return

            # 检查 LLM 配置
            if not config.LLM_API_KEY:
                yield f"data: {json.dumps({'type': 'error', 'error': '未配置大模型 API Key'})}\n\n"
                return

            wiki_content = wiki_reader.get_all_content()

            # 构建 prompts
            system_prompt = "你是一个知识库查询助手。只使用知识库内容回答，不要使用训练数据。"
            user_prompt = f"""## 知识库内容：
{wiki_content[:8000]}

## 用户问题：
{request.query}

请基于知识库内容回答，如果找不到相关信息请明确说明。"""

            from openai import OpenAI
            client = OpenAI(
                api_key=config.LLM_API_KEY,
                base_url=config.LLM_BASE_URL
            )

            stream = client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                stream=True
            )

            for chunk in stream:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    yield f"data: {json.dumps({'type': 'chunk', 'content': content})}\n\n"

            yield f"data: {json.dumps({'type': 'end', 'success': True})}\n\n"

        except Exception as e:
            logger.exception("流式查询失败")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.get("/wiki/stats")
async def get_wiki_stats():
    """获取 wiki 目录统计信息"""
    return wiki_reader.get_stats()


@app.get("/wiki/files")
async def list_wiki_files():
    """列出 wiki 目录中的所有文件"""
    stats = wiki_reader.get_stats()
    return {
        "total": stats["files_count"],
        "files": stats.get("files", [])
    }


@app.post("/wiki/refresh")
async def refresh_wiki():
    """刷新 wiki 索引"""
    wiki_reader.refresh()
    return {"success": True, "message": "Wiki 缓存已刷新"}


@app.delete("/cache")
async def clear_cache():
    """清空查询缓存"""
    llm_client.clear_cache()
    return {"success": True, "message": "缓存已清空"}


@app.get("/stats")
async def get_stats():
    """获取服务统计信息"""
    wiki_stats = wiki_reader.get_stats()
    return {
        "cache_size": len(llm_client.cache),
        "cache_ttl": config.CACHE_TTL,
        "workspace": config.WORKSPACE_DIR,
        "wiki": wiki_stats,
        "llm_configured": bool(config.LLM_API_KEY),
        "llm_model": config.LLM_MODEL
    }


# ==================== 启动脚本 ====================

def main():
    """启动服务"""
    logger.info("=" * 60)
    logger.info("知识库查询服务 v3.0 - 大模型查询 wiki 目录")
    logger.info("=" * 60)
    logger.info("查询规则:")
    logger.info("  1. 大模型只读取 wiki/ 目录下的文件")
    logger.info("  2. 不使用训练数据中的知识")
    logger.info("  3. 以 wiki/ 目录中的内容为准")
    logger.info("  4. 无信息时明确告知")
    logger.info("  5. 必须说明来源")
    logger.info("=" * 60)
    logger.info(f"配置:")
    logger.info(f"  - Host: {config.HOST}:{config.PORT}")
    logger.info(f"  - Workspace: {config.WORKSPACE_DIR}")
    logger.info(f"  - Wiki Dir: {config.WIKI_DIR_NAME}")
    logger.info(f"  - LLM Model: {config.LLM_MODEL}")
    logger.info(f"  - LLM Base URL: {config.LLM_BASE_URL}")

    wiki_stats = wiki_reader.get_stats()
    logger.info(f"  - Wiki 文件数: {wiki_stats['files_count']}")

    if not wiki_stats['exists']:
        logger.warning(f"  ⚠️ Wiki 目录不存在: {config.WORKSPACE_DIR}/{config.WIKI_DIR_NAME}")
    elif wiki_stats['files_count'] == 0:
        logger.warning(f"  ⚠️ Wiki 目录为空")
    else:
        logger.info(f"  ✅ Wiki 目录就绪")
        for f in wiki_stats.get('files', [])[:5]:
            logger.info(f"      📄 {f}")

    if not config.LLM_API_KEY:
        logger.warning("  ⚠️ 未配置 LLM_API_KEY，请设置环境变量")
    else:
        logger.info(f"  ✅ LLM API 配置完成")

    logger.info("=" * 60)

    uvicorn.run(
        "knowledge_api:app",
        host=config.HOST,
        port=config.PORT,
        reload=config.DEBUG,
        log_level="info"
    )


if __name__ == "__main__":
    main()