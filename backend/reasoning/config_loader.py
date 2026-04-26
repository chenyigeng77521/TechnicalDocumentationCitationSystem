"""
配置加载器
负责加载 prompts/prompts.yaml 和 .env（LLM 配置），
向 PromptBuilder / ReasoningPipeline 提供统一的配置对象。

优先级（从高到低）：
  1. 环境变量（LLM_API_KEY / LLM_MODEL / LLM_BASE_URL / LLM_PROVIDER）
  2. .env 中的 LLM 配置（LLM_ACTIVE_PROVIDER / LLM_<PROVIDER>_API_KEY 等）
  3. 内置默认值

用法示例：
    from .config_loader import load_prompts_config, load_llm_config, get_active_llm_config

    prompts = load_prompts_config()
    llm    = get_active_llm_config()
"""

from __future__ import annotations

import os
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

logger = logging.getLogger(__name__)

# ── 配置文件路径（相对于本文件所在目录）────────────────────────────────
_HERE = Path(__file__).parent
_PROMPTS_FILE         = _HERE / 'prompts' / 'prompts.yaml'
_REASONING_CONFIG_FILE = _HERE / 'reasoning_config.yaml'

try:
    from dotenv import load_dotenv
    load_dotenv(_HERE / '.env')
except ImportError:
    pass


# ============================================================
# 提示词配置数据类
# ============================================================
class PromptsConfig:
    """从 prompts.yaml 加载的提示词配置"""

    def __init__(self, data: Dict[str, Any]):
        self.system_prompt: str = data.get(
            'system_prompt',
            '你是一个严格的技术文档问答助手。'
        ).strip()

        self.user_prompt_template: str = data.get(
            'user_prompt_template',
            '【Context】\n{context}\n\n---\n\n【问题】\n{query}\n\n---\n\n【回答要求】\n请严格基于 Context 回答，每个事实陈述后标注引用。'
        ).strip()

        self.rejection_prompt: str = data.get(
            'rejection_prompt',
            '根据现有文档无法回答此问题。\n\n提示：当前检索得分（{max_score}）低于系统阈值。'
        ).strip()

        self.no_llm_prompt: str = data.get(
            'no_llm_prompt',
            '【问题】\n{query}\n\n【检索到的相关文档】\n{context}\n\n---\n根据上述检索结果，以下是相关信息汇总：\n\n{summary}'
        ).strip()

        self.no_llm_system_prompt: str = data.get(
            'no_llm_system_prompt',
            '你是一个信息检索助手，负责汇总检索结果。'
        ).strip()

        self.stream_message_template: str = data.get(
            'stream_message_template',
            '【Context】\n{context}\n\n{truncation_warning}【问题】{query}\n\n请严格基于 Context 回答，每个事实陈述后标注 [引用ID]。'
        ).strip()

        self.stream_truncation_warning: str = data.get(
            'stream_truncation_warning',
            '⚠️ 注意：Context 因长度限制被截断，以下回答可能不完整。\n\n'
        )

        self.system_truncation_suffix: str = data.get(
            'system_truncation_suffix',
            '\n\n⚠️ 警告：以下 Context 因长度限制被截断，可能不包含完整信息。'
        )


# ============================================================
# LLM Provider 配置数据类
# ============================================================
class LLMProviderConfig:
    """单个 provider 的 LLM 配置"""

    def __init__(self, provider_name: str, data: Dict[str, Any], defaults: Dict[str, Any]):
        self.provider: str = provider_name
        self.api_key: str = data.get('api_key', '')
        self.base_url: str = data.get('base_url', '')
        self.model: str = data.get('model', 'gpt-4-turbo')
        self.temperature: float = float(
            data.get('temperature', defaults.get('temperature', 0.1))
        )
        self.max_tokens: int = int(
            data.get('max_tokens', defaults.get('max_tokens', 2000))
        )
        self.extra_body: Dict[str, Any] = data.get('extra_body', {})

    def is_configured(self) -> bool:
        """判断 api_key 是否已填写（非占位符）"""
        placeholder_prefixes = ('your-', 'sk-xxx', 'YOUR_', '')
        key = self.api_key.strip()
        return bool(key) and not any(key.startswith(p) for p in placeholder_prefixes if p)

    def __repr__(self) -> str:
        masked = (self.api_key[:6] + '...' + self.api_key[-4:]) if len(self.api_key) > 10 else '****'
        return (
            f"LLMProviderConfig(provider={self.provider!r}, model={self.model!r}, "
            f"base_url={self.base_url!r}, api_key={masked!r})"
        )


# ============================================================
# LLM 全量配置数据类
# ============================================================
class LLMConfig:
    """从 .env / 环境变量加载的完整 LLM 配置"""

    def __init__(self, data: Dict[str, Any]):
        self.active_provider: str = data.get('active_provider', 'openai')
        self.defaults: Dict[str, Any] = data.get('defaults', {})
        self.providers: Dict[str, LLMProviderConfig] = {}

        raw_providers = data.get('providers', {}) or {}
        for name, cfg in raw_providers.items():
            self.providers[name] = LLMProviderConfig(name, cfg or {}, self.defaults)

    def get_provider(self, name: Optional[str] = None) -> Optional[LLMProviderConfig]:
        """获取指定 provider 配置；name=None 时返回 active_provider"""
        key = name or self.active_provider
        return self.providers.get(key)

    def list_providers(self) -> list[str]:
        return list(self.providers.keys())


# ============================================================
# 加载函数
# ============================================================

def _load_yaml(path: Path) -> Dict[str, Any]:
    """加载 YAML 文件，返回 dict。"""
    if not _YAML_AVAILABLE:
        logger.warning("⚠️ PyYAML 未安装，将使用内置默认配置。请执行: pip install pyyaml")
        return {}
    if not path.exists():
        logger.warning(f"⚠️ 配置文件不存在: {path}")
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        logger.debug(f"✅ 已加载配置: {path}")
        return data
    except Exception as e:
        logger.error(f"❌ 加载配置文件失败 {path}: {e}")
        return {}


def _load_llm_from_env() -> Dict[str, Any]:
    """从环境变量加载 LLM 配置，返回与 yaml 兼容的 dict 结构。"""
    providers: Dict[str, Any] = {}
    provider_names = ['glm5', 'kimi', 'minimax', 'qwen', 'openai']

    for name in provider_names:
        prefix = f'LLM_{name.upper()}_'
        cfg: Dict[str, Any] = {
            'api_key': os.environ.get(f'{prefix}API_KEY', ''),
            'base_url': os.environ.get(f'{prefix}BASE_URL', ''),
            'model': os.environ.get(f'{prefix}MODEL', 'gpt-4-turbo'),
        }
        temperature = os.environ.get(f'{prefix}TEMPERATURE', '')
        if temperature:
            cfg['temperature'] = temperature
        max_tokens = os.environ.get(f'{prefix}MAX_TOKENS', '')
        if max_tokens:
            cfg['max_tokens'] = max_tokens
        extra_body = os.environ.get(f'{prefix}EXTRA_BODY', '')
        if extra_body:
            try:
                import json
                cfg['extra_body'] = json.loads(extra_body)
            except Exception:
                cfg['extra_body'] = {}
        providers[name] = cfg

    defaults: Dict[str, Any] = {}
    default_temperature = os.environ.get('LLM_DEFAULT_TEMPERATURE', '')
    if default_temperature:
        defaults['temperature'] = default_temperature
    default_max_tokens = os.environ.get('LLM_DEFAULT_MAX_TOKENS', '')
    if default_max_tokens:
        defaults['max_tokens'] = default_max_tokens

    return {
        'active_provider': os.environ.get('LLM_ACTIVE_PROVIDER', 'openai'),
        'defaults': defaults,
        'providers': providers,
    }


@lru_cache(maxsize=1)
def load_prompts_config(prompts_file: Optional[str] = None) -> PromptsConfig:
    """
    加载提示词配置（带缓存）。
    prompts_file: 可指定自定义路径；None 时使用默认 prompts/prompts.yaml
    """
    path = Path(prompts_file) if prompts_file else _PROMPTS_FILE
    data = _load_yaml(path)
    cfg = PromptsConfig(data)
    logger.info(f"📝 提示词配置已加载: {path}")
    return cfg


@lru_cache(maxsize=1)
def load_llm_config(llm_config_file: Optional[str] = None) -> LLMConfig:
    """
    加载 LLM 配置（带缓存）。
    已从 llm_config.yaml 迁移到 .env，llm_config_file 参数已弃用。
    """
    data = _load_llm_from_env()
    cfg = LLMConfig(data)
    logger.info(
        f"🤖 LLM 配置已加载: active_provider={cfg.active_provider!r}  "
        f"providers={cfg.list_providers()}"
    )
    return cfg


def get_active_llm_config(
    provider_override: Optional[str] = None,
    llm_config_file: Optional[str] = None,
) -> Optional[LLMProviderConfig]:
    """
    获取当前激活的 provider 配置，并应用环境变量覆盖。

    环境变量优先级（从高到低）：
      LLM_PROVIDER   → 覆盖 active_provider
      LLM_API_KEY    → 覆盖 api_key
      LLM_BASE_URL   → 覆盖 base_url
      LLM_MODEL      → 覆盖 model

    参数：
      provider_override: 运行时强制指定 provider（优先于环境变量和文件配置）
    """
    config = load_llm_config(llm_config_file)

    # 确定 provider 名称（优先级：参数 > 环境变量 > .env active_provider）
    env_provider = os.environ.get('LLM_PROVIDER', '').strip()
    provider_name = provider_override or env_provider or config.active_provider

    provider_cfg = config.get_provider(provider_name)
    if provider_cfg is None:
        logger.warning(
            f"⚠️ provider '{provider_name}' 未在 .env 中定义，"
            f"可用: {config.list_providers()}"
        )
        return None

    # 应用环境变量覆盖（不修改缓存对象，创建副本）
    env_api_key  = os.environ.get('LLM_API_KEY') or os.environ.get('OPENAI_API_KEY', '').strip()
    env_base_url = os.environ.get('LLM_BASE_URL') or os.environ.get('OPENAI_BASE_URL', '').strip()
    env_model    = os.environ.get('LLM_MODEL', '').strip()

    if env_api_key or env_base_url or env_model:
        # 创建副本以避免污染 lru_cache 中的原始对象
        overridden = LLMProviderConfig(
            provider_name,
            {
                'api_key':     env_api_key  or provider_cfg.api_key,
                'base_url':    env_base_url or provider_cfg.base_url,
                'model':       env_model    or provider_cfg.model,
                'temperature': provider_cfg.temperature,
                'max_tokens':  provider_cfg.max_tokens,
                'extra_body':  provider_cfg.extra_body,
            },
            config.defaults,
        )
        logger.info(f"🔧 已从环境变量覆盖 LLM 配置: {overridden}")
        return overridden

    return provider_cfg


# ============================================================
# 推理层参数配置 (reasoning_config.yaml)
# ============================================================

class ReasoningConfig:
    """
    从 reasoning_config.yaml 加载的推理层静态参数。

    所有字段均有内置默认值，reasoning_config.yaml 缺失时自动回退。
    """

    def __init__(self, data: Dict[str, Any]):
        rej  = data.get('rejection',    {})
        gov  = data.get('governance',   {})
        inj  = data.get('injection',    {})
        ver  = data.get('verification', {})
        ret  = data.get('retrieval',    {})

        # ── 拒答守卫
        self.score_threshold: float = float(rej.get('score_threshold', 0.4))

        # ── 上下文治理
        self.max_context_tokens: int           = int(gov.get('max_context_tokens', 6000))
        self.gov_deduplication_threshold: float = float(gov.get('deduplication_threshold', 0.95))
        self.conflict_resolution: str          = gov.get('conflict_resolution', 'keep_higher_score')
        self.min_score_threshold: float        = float(gov.get('min_score_threshold', 0.1))
        self.conflict_offset_threshold: int    = int(gov.get('conflict_offset_threshold', 500))
        self.conflict_similarity_threshold: float = float(gov.get('conflict_similarity_threshold', 0.7))
        self.token_min_length: int             = int(gov.get('token_min_length', 2))

        # ── 上下文注入
        self.max_tokens: int                    = int(inj.get('max_tokens', 6000))
        self.inj_deduplication_threshold: float = float(inj.get('deduplication_threshold', 0.95))
        self.chars_per_token: int               = int(inj.get('chars_per_token', 4))

        # ── 引用验证
        self.verified_threshold: float   = float(ver.get('verified_threshold', 0.8))
        self.context_window_chars: int   = int(ver.get('context_window_chars', 50))
        self.snippet_length: int         = int(ver.get('snippet_length', 100))

        # ── 检索
        self.default_top_k: int          = int(ret.get('default_top_k', 5))
        self.anchor_offset_step: int     = int(ret.get('anchor_offset_step', 1000))

    def __repr__(self) -> str:
        return (
            f"ReasoningConfig("
            f"score_threshold={self.score_threshold}, "
            f"max_tokens={self.max_tokens}, "
            f"verified_threshold={self.verified_threshold}, "
            f"default_top_k={self.default_top_k})"
        )


@lru_cache(maxsize=1)
def load_reasoning_config(config_file: Optional[str] = None) -> ReasoningConfig:
    """
    加载推理层参数配置（带缓存）。

    config_file: 可指定自定义路径；None 时使用默认 reasoning_config.yaml。
    修改配置后调用 reload_configs() 使缓存失效。
    """
    path = Path(config_file) if config_file else _REASONING_CONFIG_FILE
    data = _load_yaml(path)
    cfg  = ReasoningConfig(data)
    logger.info(f"⚙️ 推理参数配置已加载: {path}  → {cfg}")
    return cfg


def reload_configs() -> None:
    """清除缓存，强制重新加载配置文件（热重载场景）"""
    load_prompts_config.cache_clear()
    load_llm_config.cache_clear()
    load_reasoning_config.cache_clear()
    logger.info("🔄 配置缓存已清除，下次访问将重新加载")


# ============================================================
# CLI 快速检查
# ============================================================
if __name__ == '__main__':
    import json
    logging.basicConfig(level=logging.DEBUG)

    print('\n=== 提示词配置 ===')
    p = load_prompts_config()
    print(f'system_prompt (前60字): {p.system_prompt[:60]!r}')
    print(f'rejection_prompt       : {p.rejection_prompt[:60]!r}')

    print('\n=== 推理层参数配置 ===')
    rc = load_reasoning_config()
    print(f'score_threshold           : {rc.score_threshold}')
    print(f'max_context_tokens        : {rc.max_context_tokens}')
    print(f'gov_deduplication_threshold: {rc.gov_deduplication_threshold}')
    print(f'conflict_resolution       : {rc.conflict_resolution}')
    print(f'min_score_threshold       : {rc.min_score_threshold}')
    print(f'conflict_offset_threshold : {rc.conflict_offset_threshold}')
    print(f'conflict_similarity       : {rc.conflict_similarity_threshold}')
    print(f'token_min_length          : {rc.token_min_length}')
    print(f'inj_dedup_threshold       : {rc.inj_deduplication_threshold}')
    print(f'chars_per_token           : {rc.chars_per_token}')
    print(f'verified_threshold        : {rc.verified_threshold}')
    print(f'context_window_chars      : {rc.context_window_chars}')
    print(f'snippet_length            : {rc.snippet_length}')
    print(f'default_top_k             : {rc.default_top_k}')
    print(f'anchor_offset_step        : {rc.anchor_offset_step}')
    print(f'no_llm_system_prompt   : {p.no_llm_system_prompt!r}')

    print('\n=== LLM 配置 ===')
    lc = load_llm_config()
    print(f'active_provider: {lc.active_provider}')
    print(f'providers      : {lc.list_providers()}')

    print('\n=== 当前激活 Provider ===')
    active = get_active_llm_config()
    if active:
        print(active)
        print(f'is_configured: {active.is_configured()}')
    else:
        print('（未找到可用 provider）')
