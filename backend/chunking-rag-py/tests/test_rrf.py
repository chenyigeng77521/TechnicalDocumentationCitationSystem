from app.retriever.rrf import rrf_fuse


def test_rrf_two_lists_fully_overlap():
    a = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
    b = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
    out = rrf_fuse([a, b], k=60)
    assert [c["id"] for c in out] == ["1", "2", "3"]


def test_rrf_no_overlap_preserves_all():
    a = [{"id": "1"}, {"id": "2"}]
    b = [{"id": "3"}, {"id": "4"}]
    out = rrf_fuse([a, b], k=60)
    assert {c["id"] for c in out} == {"1", "2", "3", "4"}


def test_rrf_partial_overlap_rank_sum():
    a = [{"id": "1"}, {"id": "2"}]
    b = [{"id": "2"}, {"id": "3"}]
    out = rrf_fuse([a, b], k=60)
    assert out[0]["id"] == "2"
