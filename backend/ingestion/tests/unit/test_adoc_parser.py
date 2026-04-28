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
