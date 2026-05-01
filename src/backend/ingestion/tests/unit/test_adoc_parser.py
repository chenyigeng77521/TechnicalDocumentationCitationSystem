"""单元测试：adoc_parser
spec §3.3 + §4.2 T1-T6"""
from backend.ingestion.parser.adoc_parser import _slugify


def test_t5_slugify_matches_gold_anchors():
    """T5：slug 算法对照 4 个赛题真实 gold anchor。"""
    cases = [
        ("Migrating to `RestClient`", "migrating-to-restclient"),
        ("DataBufferFactory", "databufferfactory"),
        ("Using DataBuffer", "using-databuffer"),
        ("The ResourceLoader Interface", "the-resourceloader-interface"),
    ]
    for text, expected in cases:
        actual = _slugify(text)
        assert actual == expected, f"_slugify({text!r}) = {actual!r}, expected {expected!r}"


def test_slugify_empty_returns_empty():
    """空字符串 / 全标点 → 空 slug。"""
    assert _slugify("") == ""
    assert _slugify("...") == ""
    assert _slugify("!@#$") == ""


def test_slugify_chinese_preserved():
    """中文字符保留（赛题 anchor 全是英文，但中文不应被吃掉）。"""
    assert _slugify("数据治理") == "数据治理"
    assert _slugify("配置 K8s 集群") == "配置-k8s-集群"


# === T3: _extract_headings_with_anchors ===
from backend.ingestion.parser.adoc_parser import _extract_headings_with_anchors


def test_t1_basic_h1_with_explicit_anchor():
    """T1：[[aop]] 紧跟 H1 标题 → headings[0].anchor == 'aop'。"""
    raw = "[[aop]]\n= Aspect Oriented Programming with Spring\n\n正文..."
    headings = _extract_headings_with_anchors(raw)
    assert len(headings) == 1
    assert headings[0].level == 1
    assert headings[0].text == "Aspect Oriented Programming with Spring"
    assert headings[0].anchor == "aop"


def test_t2_h3_with_explicit_anchor():
    """T2：[[migrating-to-restclient]] 紧跟 H3 → anchor == 'migrating-to-restclient'。"""
    raw = "[[migrating-to-restclient]]\n=== Migrating to `RestClient`\n\n正文..."
    headings = _extract_headings_with_anchors(raw)
    assert len(headings) == 1
    assert headings[0].level == 3
    assert headings[0].anchor == "migrating-to-restclient"


def test_t3_heading_without_explicit_anchor_uses_slug():
    """T3：标题前无 [[xxx]] → 自动 slug。"""
    raw = "== Using DataBuffer\n\n正文..."
    headings = _extract_headings_with_anchors(raw)
    assert len(headings) == 1
    assert headings[0].level == 2
    assert headings[0].anchor == "using-databuffer"


def test_t4_block_anchor_ignored():
    """T4：[[xxx]] 后面跟 .caption（块锚点，不是章节）→ 不出现在 headings。

    spec §2 类型 4：[[xxx]] 紧跟 .Caption / 表格 / 代码块的不是章节锚点。
    我们的算法只识别"前 1-2 行有 [[xxx]] 的 = 标题"，块锚点对应的下一行
    是 .Caption（不是 = 标题），所以 [[xxx]] 不会被关联到任何 heading。
    """
    raw = """== Real Section

[[rest-overview-of-resttemplate-methods-tbl]]
.RestTemplate methods
[cols="2,3"]
|===
| HTTP Method | Description
| GET | Retrieve a resource
|===
"""
    headings = _extract_headings_with_anchors(raw)
    # 应该只有 1 个 heading（"Real Section"），不包含块锚点
    assert len(headings) == 1
    assert headings[0].text == "Real Section"
    # 块锚点 "rest-overview-of-resttemplate-methods-tbl" 不应被任何 heading 关联
    assert headings[0].anchor == "real-section"  # 自动 slug，不是块锚点


def test_anchor_with_blank_line_between_anchor_and_heading():
    """边界：[[xxx]] 和标题之间有空行（spec §3.3 算法看前 1-2 行跳空行）。"""
    raw = "[[anchor-name]]\n\n== Section Title\n\n正文..."
    headings = _extract_headings_with_anchors(raw)
    assert len(headings) == 1
    assert headings[0].anchor == "anchor-name"


# === T4 / T6 / AC5: parse() 入口 + dispatcher + 真实文件 e2e ===
import asyncio
from pathlib import Path
import pytest

# 赛题真实 adoc 路径（开发机本地）
SPRING_ADOC_DIR = Path("/Users/tuyh3/Downloads/初赛试题材料-题目1/data/docs/spring")


def _flatten_tree(tree):
    """把 title_tree 平铺成扁平 list（递归）。"""
    out = []
    for node in tree:
        out.append(node)
        out.extend(_flatten_tree(node.children or []))
    return out


@pytest.mark.skipif(not SPRING_ADOC_DIR.exists(),
                    reason="赛题数据不在开发机上，跳过真实文件测试")
def test_t6_parse_real_aop_adoc():
    """T6：真实 aop.adoc 解析能跑通，headings 非空，anchor 字段都填上。"""
    from backend.ingestion.parser.adoc_parser import parse
    aop_path = SPRING_ADOC_DIR / "aop.adoc"
    result = asyncio.run(parse(aop_path))
    assert result.content_type == "document"
    assert len(result.raw_text) > 0
    flat = _flatten_tree(result.title_tree)
    # aop.adoc 是"门户文档"（用 xref 引用子章节），实际只有 1 个 H1
    assert len(flat) >= 1, f"aop.adoc 应有 ≥1 个标题，实际 {len(flat)}"
    # 抽查：第 1 个 heading 应该是 "Aspect Oriented Programming with Spring"
    assert "Aspect" in flat[0].text or "AOP" in flat[0].text
    # 显式 anchor [[aop]] 应该被识别
    assert flat[0].anchor == "aop"
    # 所有 anchor 字段都填上
    for h in flat:
        assert h.anchor is not None and h.anchor != "", \
            f"heading {h.text!r} 的 anchor 没填: {h.anchor!r}"


@pytest.mark.skipif(not SPRING_ADOC_DIR.exists(),
                    reason="赛题数据不在开发机上，跳过批量验证")
def test_ac5_all_56_spring_adoc_parse_ok():
    """AC5：56 个真实赛题 adoc 文件批量 parse 不报错，所有 heading anchor 填上。"""
    from backend.ingestion.parser.adoc_parser import parse
    files = sorted(SPRING_ADOC_DIR.glob("*.adoc"))
    assert len(files) >= 50, f"预期 ≥50 个 adoc 文件，实际 {len(files)}"

    failed = []
    no_anchor = []
    for f in files:
        try:
            result = asyncio.run(parse(f))
            for h in _flatten_tree(result.title_tree):
                if h.anchor is None or h.anchor == "":
                    no_anchor.append((f.name, h.text))
        except Exception as e:
            failed.append((f.name, str(e)))

    assert not failed, f"以下文件 parse 报错: {failed[:5]}"
    assert not no_anchor, f"以下 heading 没填 anchor: {no_anchor[:5]}"


def test_dispatcher_routes_adoc():
    """dispatcher 应能识别 .adoc 和 .asciidoc。"""
    from backend.ingestion.parser.dispatcher import get_parser_name
    assert get_parser_name(Path("foo.adoc")) == "adoc"
    assert get_parser_name(Path("bar.asciidoc")) == "adoc"
    # 大写后缀也行（dispatcher 用 .lower()）
    assert get_parser_name(Path("BAZ.ADOC")) == "adoc"


def test_dispatcher_e2e_adoc(tmp_path):
    """dispatcher.parse_document() 集成：手造 adoc 文件能解析。"""
    from backend.ingestion.parser.dispatcher import parse_document
    adoc_file = tmp_path / "test.adoc"
    adoc_file.write_text("[[hello]]\n= Hello World\n\nThis is content.\n", encoding="utf-8")
    result = asyncio.run(parse_document(adoc_file))
    assert result.content_type == "document"
    flat = _flatten_tree(result.title_tree)
    assert len(flat) == 1
    assert flat[0].text == "Hello World"
    assert flat[0].anchor == "hello"
