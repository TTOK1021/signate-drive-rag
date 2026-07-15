"""RRF順位統合のテスト。"""

import pytest

from signate_drive_rag.retrieval.rrf import fuse_rankings


def test_fuse_rankings_combines_channels_and_deduplicates_items() -> None:
    """複数チャネルの順位を1件の結果へ統合する。"""
    results = fuse_rankings(
        {
            "content_word": ["a", "b"],
            "content_ngram": ["b", "a"],
        },
        rrf_k=60,
    )

    assert {result.item_id for result in results} == {"a", "b"}
    assert results[0].channel_ranks["content_word"] == 1
    assert results[0].score == pytest.approx(1 / 61 + 1 / 62)


def test_fuse_rankings_uses_deterministic_tie_break() -> None:
    """同点では最良順位、チャネル数、chunk_idで決定的に並べる。"""
    results = fuse_rankings({"x": ["b", "a"]}, rrf_k=60)

    assert [result.item_id for result in results] == ["b", "a"]
    assert fuse_rankings({}) == ()
    with pytest.raises(ValueError):
        fuse_rankings({"x": ["a"]}, rrf_k=0)
