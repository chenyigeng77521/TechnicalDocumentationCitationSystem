"""
大模型客户端模块
"""
import json
import re
from pathlib import Path
from typing import List, Dict, Optional
from openai import OpenAI, AzureOpenAI

from logger import Logger
from config import AppConfig


class LLMClient:
    """大模型客户端"""

    def __init__(self, config: AppConfig, logger: Logger):
        self.config = config
        self.logger = logger
        self.client = self._create_client()

    def _create_client(self):
        """创建大模型客户端"""
        llm = self.config.llm

        if llm.api_type == "openai":
            return OpenAI(
                api_key=llm.api_key,
                base_url=llm.api_base if llm.api_base else None
            )
        elif llm.api_type == "azure":
            return AzureOpenAI(
                api_key=llm.api_key,
                azure_endpoint=llm.api_base,
                api_version="2024-02-15-preview"
            )
        else:
            return OpenAI(
                api_key=llm.api_key,
                base_url=llm.api_base
            )

    def _load_prompt_template(self, name: str) -> str:
        """从 prompts.md 加载指定 prompt 模板"""
        prompts_file = Path(__file__).parent / "prompts.md"
        if not prompts_file.exists():
            raise FileNotFoundError(f"prompts.md 不存在: {prompts_file}")

        content = prompts_file.read_text(encoding='utf-8')

        # 查找 ## name 后面的内容，直到下一个 ## 或文件结束
        pattern = rf'^## {re.escape(name)}\s*\n(.*?)(?=\n## |\Z)'
        match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        if not match:
            raise ValueError(f"prompts.md 中未找到 prompt: {name}")

        return match.group(1).strip()

    def _load_agents_rules(self) -> str:
        """加载 AGENTS.md 中的规则"""
        agents_file = self.config.paths.agents_path
        if agents_file.exists():
            try:
                with open(agents_file, 'r', encoding='utf-8') as f:
                    return f.read()
            except IOError as e:
                self.logger.warning(f"读取 AGENTS.md 失败: {e}")
        return ""

    def _read_file_content(self, file_path: Path, max_length: int) -> str:
        """读取文件内容，支持文本文件及常见 Office/PDF 文件"""
        if not file_path.exists():
            return ""

        suffix = file_path.suffix.lower()
        content = ""

        try:
            if suffix in ('.xls', '.xlsx'):
                content = self._read_excel(file_path)
            elif suffix == '.docx':
                content = self._read_docx(file_path)
            elif suffix == '.pdf':
                content = self._read_pdf(file_path)
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
        except Exception as e:
            self.logger.error(f"读取文件失败 {file_path}: {e}")
            return f"[读取失败: {e}]"

        if len(content) > max_length:
            content = content[:max_length] + "\n... (内容已截断)"
        return content

    def _read_excel(self, file_path: Path) -> str:
        """读取 Excel 文件并转为 Markdown 表格"""
        import pandas as pd
        df = pd.read_excel(file_path)
        return self._dataframe_to_markdown(df)

    def _dataframe_to_markdown(self, df) -> str:
        """将 DataFrame 转为 Markdown 表格"""
        import pandas as pd
        if df.empty:
            return "(空表格)"
        lines = []
        headers = [str(c) for c in df.columns]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for _, row in df.iterrows():
            row_vals = [str(v) if pd.notna(v) else "" for v in row]
            lines.append("| " + " | ".join(row_vals) + " |")
        return "\n".join(lines)

    def _read_docx(self, file_path: Path) -> str:
        """读取 Word 文件"""
        from docx import Document
        doc = Document(str(file_path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)

    def _read_pdf(self, file_path: Path) -> str:
        """读取 PDF 文件"""
        from PyPDF2 import PdfReader
        reader = PdfReader(str(file_path))
        texts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                texts.append(text)
        return "\n\n".join(texts)

    def _get_wiki_files(self) -> List[Path]:
        """获取所有 wiki 文件"""
        wiki_dir = self.config.paths.wiki_path
        if not wiki_dir.exists():
            return []
        return [f for f in wiki_dir.rglob('*.md') if f.is_file()]

    def _read_index_content(self) -> str:
        """读取 index.md 内容"""
        index_path = self.config.paths.wiki_path / "index.md"
        if index_path.exists():
            try:
                with open(index_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except IOError:
                pass
        return ""

    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        agents_rules = self._load_agents_rules()
        base_prompt = self._load_prompt_template("system_prompt")

        if agents_rules:
            base_prompt = f"{agents_rules}\n\n{base_prompt}"

        return base_prompt

    def _build_user_prompt(
        self,
        changed_files: List[str],
        is_first_run: bool
    ) -> str:
        """构建用户提示词"""

        # 读取变更文件的内容
        raw_contents: List[str] = []
        for file_path in changed_files:
            full_path = self.config.paths.project_root / file_path
            if full_path.exists():
                content = self._read_file_content(full_path, self.config.max_content_length)
                raw_contents.append(
                    "\n### 文件: " + file_path + "\n\n```\n" + content + "\n```\n"
                )
            else:
                raw_contents.append(
                    "\n### 文件: " + file_path + "\n**注意：此文件已删除**\n"
                )

        # 获取现有 wiki 文件列表
        wiki_files = self._get_wiki_files()
        wiki_list_lines = []
        for f in wiki_files:
            wiki_list_lines.append(f"- {f.relative_to(self.config.paths.wiki_path)}")
        wiki_list = "\n".join(wiki_list_lines) if wiki_list_lines else "(无现有 wiki 文件)"

        index_content = self._read_index_content()
        if not index_content:
            index_content = "(不存在)"

        # 构建动态变量
        run_mode = "**首次运行 - 需要全量构建**" if is_first_run else "**增量更新模式**"
        changed_list = "\n".join(f"- {f}" for f in changed_files)

        # 加载模板并替换占位符
        prompt = self._load_prompt_template("user_prompt")
        prompt = prompt.replace("{run_mode}", run_mode)
        prompt = prompt.replace("{changed_list}", changed_list)
        prompt = prompt.replace("{raw_contents}", "".join(raw_contents))
        prompt = prompt.replace("{wiki_list}", wiki_list)
        prompt = prompt.replace("{index_content}", index_content)

        return prompt

    def update_knowledge_base(
        self,
        changed_files: List[str],
        is_first_run: bool
    ) -> Optional[Dict]:
        """调用大模型更新知识库"""

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(changed_files, is_first_run)

        self.logger.info(f"正在调用大模型: {self.config.llm.model}")
        self.logger.debug(f"用户提示词长度: {len(user_prompt)} 字符")

        try:
            response = self.client.chat.completions.create(
                model=self.config.llm.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.config.llm.temperature,
                max_tokens=self.config.llm.max_tokens,
                response_format={"type": "json_object"}
            )

            result_text = response.choices[0].message.content
            self.logger.debug(f"大模型响应长度: {len(result_text)} 字符")

            # 解析 JSON
            result = json.loads(result_text)
            self.logger.info("大模型响应解析成功")

            # 验证必要字段
            required_fields = [
                "deleted_files", "updated_files", "created_files",
                "files_content", "index_content", "log_entry"
            ]
            for field in required_fields:
                if field not in result:
                    if field == "files_content":
                        result[field] = {}
                    else:
                        result[field] = []

            # 统计操作数量
            self.logger.info(f"待删除文件: {len(result['deleted_files'])} 个")
            self.logger.info(f"待更新文件: {len(result['updated_files'])} 个")
            self.logger.info(f"待创建文件: {len(result['created_files'])} 个")

            return result

        except json.JSONDecodeError as e:
            self.logger.error(f"JSON 解析失败: {e}")
            if 'result_text' in dir():
                self.logger.debug(f"原始响应: {result_text[:500]}")
            return None
        except Exception as e:
            self.logger.error(f"调用大模型失败: {e}")
            return None

    def query_knowledge_base(
        self,
        query: str,
        context_files: Optional[List[str]] = None
    ) -> Optional[str]:
        """查询知识库（简单查询接口）"""
    
        # 获取 wiki 内容
        wiki_content = self._read_index_content()
    
        # 加载模板并替换占位符
        system_prompt = self._load_prompt_template("query_system_prompt")
    
        user_prompt = self._load_prompt_template("query_user_prompt")
        user_prompt = user_prompt.replace("{wiki_content}", wiki_content if wiki_content else "(知识库为空)")
        user_prompt = user_prompt.replace("{query}", query)
    
        try:
            response = self.client.chat.completions.create(
                model=self.config.llm.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=2000
            )
    
            return response.choices[0].message.content
                
        except Exception as e:
            self.logger.error(f"查询知识库失败: {e}")
            return f"查询失败: {str(e)}"