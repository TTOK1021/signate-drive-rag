"""BM25インデックス構築のテスト。"""

from pathlib import Path

from signate_drive_rag.chunking.models import RetrievalChunk
from signate_drive_rag.retrieval.bm25_retriever import Bm25Retriever
from signate_drive_rag.retrieval.index_builder import build_bm25_index
from signate_drive_rag.retrieval.index_store import load_bm25_index, save_bm25_index
from signate_drive_rag.retrieval.loader import calculate_file_sha256
from signate_drive_rag.retrieval.models import SEARCH_CHANNELS, LoadedBm25Index


def chunk(
    chunk_id: str,
    text: str,
    *,
    relative_path: str = "資料/契約一覧.csv",
    chunk_index: int = 0,
    metadata: dict[str, object] | None = None,
) -> RetrievalChunk:
    """テスト用RetrievalChunkを作成する。"""
    return RetrievalChunk(
        chunk_id=chunk_id,
        relative_path=relative_path,
        parser_name="delimited_text",
        unit_type="table_rows",
        text=text,
        locator="row:2-3",
        source_unit_indices=(0,),
        chunk_index=chunk_index,
        metadata={} if metadata is None else metadata,  # type: ignore[arg-type]
    )


def test_build_bm25_index_builds_three_channels_and_sorts_records(tmp_path: Path) -> None:
    """3チャネルを構築し、record_indexを決定的な順序へ付与する。"""
    chunks = (
        chunk("b", "TASK-001 customer_id 5,000,000", relative_path="b.txt"),
        chunk("a", "契約金額", relative_path="a.txt"),
    )
    source_path = tmp_path / "chunks.jsonl"
    source_path.write_text("dummy", encoding="utf-8")

    index = build_bm25_index(
        chunks,
        source_sha256=calculate_file_sha256(source_path),
        ngram_min=2,
        ngram_max=3,
    )

    assert tuple(index.channel_indexes) == SEARCH_CHANNELS
    assert [record.chunk_id for record in index.records] == ["a", "b"]
    assert [record.record_index for record in index.records] == [0, 1]
    assert index.manifest["record_count"] == 2
    assert index.manifest["source_sha256"] == calculate_file_sha256(source_path)


def test_build_bm25_index_supports_japanese_partial_ids_numbers_and_context(
    tmp_path: Path,
) -> None:
    """日本語部分一致、ID、数値、ファイル名contextを検索できる。"""
    index = build_bm25_index(
        (
            chunk("contract", "契約金額は5,000,000です", metadata={"headers": ["契約金額"]}),
            chunk("task", "TASK-001 customer_idを確認", relative_path="tasks/report.md"),
        ),
        source_sha256="sha",
    )
    output_dir = tmp_path / "index"
    save_bm25_index(index, output_dir)
    loaded = load_bm25_index(output_dir)
    retriever = Bm25Retriever(loaded)

    assert retriever.search("約金", 1)[0].chunk_id == "contract"
    assert retriever.search("TASK-001", 1)[0].chunk_id == "task"
    assert retriever.search("5000000", 1)[0].chunk_id == "contract"
    assert retriever.search("report.md", 1)[0].chunk_id == "task"


def test_build_bm25_index_handles_empty_corpus() -> None:
    """空コーパスではBM25本体を作らずmanifestとrecordsを構成する。"""
    index = build_bm25_index((), source_sha256="empty")

    assert index.records == ()
    assert index.channel_indexes == {}
    assert index.manifest["record_count"] == 0


def test_loaded_empty_corpus_returns_empty_results(tmp_path: Path) -> None:
    """空コーパスの保存・読込後検索は空結果を返す。"""
    index = build_bm25_index((), source_sha256="empty")
    save_bm25_index(index, tmp_path / "index")
    loaded = load_bm25_index(tmp_path / "index")

    assert loaded == LoadedBm25Index(
        manifest=loaded.manifest,
        records=(),
        channel_indexes={},
    )
    assert Bm25Retriever(loaded).search("契約", 10) == ()
