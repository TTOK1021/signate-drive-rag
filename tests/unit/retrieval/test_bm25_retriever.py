"""BM25 Retrieverのテスト。"""

import pytest

from signate_drive_rag.chunking.models import RetrievalChunk
from signate_drive_rag.retrieval.bm25_retriever import Bm25Retriever, SearchInputError
from signate_drive_rag.retrieval.index_builder import build_bm25_index
from signate_drive_rag.retrieval.models import LoadedBm25Index


def chunk(chunk_id: str, text: str, relative_path: str = "資料.txt") -> RetrievalChunk:
    """テスト用RetrievalChunkを作成する。"""
    return RetrievalChunk(
        chunk_id=chunk_id,
        relative_path=relative_path,
        parser_name="plain_text",
        unit_type="text",
        text=text,
        locator="line:1-1",
        source_unit_indices=(0,),
        chunk_index=0,
        metadata={},
    )


def retriever_for(chunks: tuple[RetrievalChunk, ...]) -> Bm25Retriever:
    """テスト用Retrieverを作成する。"""
    index = build_bm25_index(chunks, source_sha256="sha")
    return Bm25Retriever(
        LoadedBm25Index(
            manifest=index.manifest,
            records=index.records,
            channel_indexes=index.channel_indexes,
        )
    )


def test_bm25_retriever_searches_japanese_partial_ids_numbers_and_limits_top_k() -> None:
    """主要な検索語種別を検索し、top_kを尊重する。"""
    retriever = retriever_for(
        (
            chunk("a", "契約金額 5,000,000 customer_id", "契約一覧.csv"),
            chunk("b", "TASK-001 分析結果", "分析結果.md"),
        )
    )

    assert retriever.search("契約金額", 1)[0].chunk_id == "a"
    assert retriever.search("約金", 1)[0].chunk_id == "a"
    assert retriever.search("customer_id", 1)[0].chunk_id == "a"
    assert retriever.search("TASK-001", 1)[0].chunk_id == "b"
    assert retriever.search("5000000", 1)[0].chunk_id == "a"
    assert len(retriever.search("結果", 1)) == 1


def test_bm25_retriever_preserves_source_fields_and_channel_ranks() -> None:
    """検索結果に相対パス、locator、チャネル順位を保持する。"""
    result = retriever_for((chunk("a", "契約金額"),)).search("契約", 1)[0]

    assert result.relative_path == "資料.txt"
    assert result.locator == "line:1-1"
    assert result.channel_ranks
    assert result.rank == 1


def test_bm25_retriever_rejects_invalid_query_and_options() -> None:
    """空質問や不正な検索設定では明確な例外にする。"""
    retriever = retriever_for((chunk("a", "契約金額"),))

    with pytest.raises(SearchInputError):
        retriever.search("   ", 10)
    with pytest.raises(ValueError):
        retriever.search("契約", 0)
    with pytest.raises(ValueError):
        Bm25Retriever(
            LoadedBm25Index(
                manifest=build_bm25_index((), source_sha256="sha").manifest,
                records=(),
                channel_indexes={},
            ),
            candidate_multiplier=0,
        )


def test_bm25_retriever_is_deterministic_for_same_query() -> None:
    """同じ質問では同じ順位を返す。"""
    retriever = retriever_for((chunk("b", "契約"), chunk("a", "契約")))

    first = retriever.search("契約", 10)
    second = retriever.search("契約", 10)

    assert [result.chunk_id for result in first] == [result.chunk_id for result in second]
