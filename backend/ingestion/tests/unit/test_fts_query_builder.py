"""单元测试：_build_fts_query / _is_meaningful_token / _escape_fts_phrase

spec §3.2 + §5 T5 + §6.4 AC3
"""
from backend.ingestion.db.chunks_repo import (
    _build_fts_query,
    _is_meaningful_token,
    _escape_fts_phrase,
)


def test_is_meaningful_token():
    """spec §6.4 AC3 单一规则：含字母/数字字符的 token 才算 meaningful。"""
    assert _is_meaningful_token("F5") is True
    assert _is_meaningful_token("数据") is True
    assert _is_meaningful_token("a1") is True
    assert _is_meaningful_token("'") is False
    assert _is_meaningful_token("...") is False
    assert _is_meaningful_token("（）") is False
    assert _is_meaningful_token("😀") is False
    assert _is_meaningful_token("") is False


def test_escape_fts_phrase():
    """phrase escape：包引号 + 内部引号转义为 ""。"""
    assert _escape_fts_phrase("F5") == '"F5"'
    assert _escape_fts_phrase("数据治理") == '"数据治理"'
    assert _escape_fts_phrase('a"b') == '"a""b"'


def test_build_fts_query_chinese():
    """中文 query → jieba 切词 + 各 token phrase OR 拼接。"""
    result = _build_fts_query("数据治理")
    assert result == '"数据" OR "治理"'


def test_build_fts_query_english():
    """英文 query → 按空格切（jieba 行为）+ phrase OR 拼接。"""
    result = _build_fts_query("F5 DNS")
    assert result == '"F5" OR "DNS"'


def test_build_fts_query_empty():
    """空字符串 → 返空字符串（调用方据此短路）。"""
    assert _build_fts_query("") == ""
    assert _build_fts_query("   ") == ""


# === T5 sub-case 矩阵 ===

def test_t5a_boolean_keyword_AND():
    """T5a: F5 AND DNS → 'AND' 被当 phrase 不再是 boolean keyword。"""
    result = _build_fts_query("F5 AND DNS")
    assert result == '"F5" OR "AND" OR "DNS"'


def test_t5b_apostrophe_filtered():
    """T5b: company's profile → 撇号单独成 token 被过滤；'s' 含字母保留。"""
    result = _build_fts_query("company's profile")
    tokens_in_result = result.split(' OR ')
    assert '"company"' in tokens_in_result
    assert '"profile"' in tokens_in_result
    assert "\"'\"" not in tokens_in_result  # 撇号被过滤


def test_t5c_parens_filtered():
    """T5c: F5 (DNS) → 括号被过滤。"""
    result = _build_fts_query("F5 (DNS)")
    tokens_in_result = result.split(' OR ')
    assert '"F5"' in tokens_in_result
    assert '"DNS"' in tokens_in_result
    assert '"("' not in tokens_in_result
    assert '")"' not in tokens_in_result


def test_t5d_asterisk_filtered():
    """T5d: F5* → 星号被过滤。"""
    result = _build_fts_query("F5*")
    assert result == '"F5"'


def test_t5e_NEAR_phrased():
    """T5e: NEAR(F5 DNS) → NEAR 被 phrase 化成普通词，不再是 FTS5 函数。"""
    result = _build_fts_query("NEAR(F5 DNS)")
    tokens_in_result = result.split(' OR ')
    assert '"NEAR"' in tokens_in_result
    assert '"F5"' in tokens_in_result
    assert '"DNS"' in tokens_in_result


def test_t5f_minus_filtered():
    """T5f: -F5 → 负号被过滤。"""
    result = _build_fts_query("-F5")
    assert result == '"F5"'


def test_t5g_punctuation_only_returns_empty():
    """T5g: 纯标点 → 全过滤 → 返空字符串。"""
    assert _build_fts_query("...") == ""
    assert _build_fts_query("！？。") == ""


def test_t5h_empty_returns_empty():
    """T5h: 空 query → 返空字符串（_build_fts_query 层）。"""
    assert _build_fts_query("") == ""


def test_t5i_emoji_filtered():
    """T5i: emoji 被过滤（unicode category 不是 L/N）。"""
    result = _build_fts_query("😀F5")
    assert result == '"F5"'
