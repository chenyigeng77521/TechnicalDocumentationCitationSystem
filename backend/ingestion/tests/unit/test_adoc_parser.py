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
