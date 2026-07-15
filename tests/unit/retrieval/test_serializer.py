"""BM25インデックスと検索結果のシリアライズテスト。"""

import json
from pathlib import Path

import pytest

from signate_drive_rag.chunking.models import RetrievalChunk
from signate_drive_rag.retrieval.bm25_retriever import Bm25Retriever
from signate_drive_rag.retrieval.index_builder import build_bm25_index
from signate_drive_rag.retrieval.index_store import (
    RetrievalIndexError,
    load_bm25_index,
    save_bm25_index,
)
from signate_drive_rag.retrieval.serializer import save_search_results


def chunk(chunk_id: str = "chunk") -> RetrievalChunk:
    """テスト用RetrievalChunkを作成する。"""
    return RetrievalChunk(
        chunk_id=chunk_id,
        relative_path="資料/契約.md",
        parser_name="markdown",
        unit_type="markdown_section",
        text="契約金額",
        locator="heading:1",
        source_unit_indices=(0,),
        chunk_index=0,
        metadata={"heading": "契約"},
    )


def test_save_and_load_bm25_index_preserves_search_results(tmp_path: Path) -> None:
    """保存前後で同じ検索結果を返せる。"""
    index = build_bm25_index((chunk(),), source_sha256="sha")
    output_dir = tmp_path / "index"

    save_bm25_index(index, output_dir)
    loaded = load_bm25_index(output_dir)

    assert (output_dir / "manifest.json").exists()
    assert (
        json.loads((output_dir / "records.jsonl").read_text(encoding="utf-8"))["relative_path"]
        == "資料/契約.md"
    )
    assert Bm25Retriever(loaded).search("契約", 1)[0].chunk_id == "chunk"
    assert list(output_dir.glob("*.tmp")) == []


def test_save_bm25_index_does_not_overwrite_without_permission(tmp_path: Path) -> None:
    """既存インデックスは--overwrite相当の指定なしでは上書きしない。"""
    output_dir = tmp_path / "index"
    save_bm25_index(build_bm25_index((chunk("old"),), source_sha256="old"), output_dir)

    with pytest.raises(RetrievalIndexError):
        save_bm25_index(build_bm25_index((chunk("new"),), source_sha256="new"), output_dir)

    loaded = load_bm25_index(output_dir)
    assert loaded.records[0].chunk_id == "old"
    save_bm25_index(
        build_bm25_index((chunk("new"),), source_sha256="new"), output_dir, overwrite=True
    )
    assert load_bm25_index(output_dir).records[0].chunk_id == "new"


def test_load_bm25_index_detects_manifest_and_record_inconsistencies(tmp_path: Path) -> None:
    """manifest不整合、欠番record_index、重複chunk_idを検出する。"""
    output_dir = tmp_path / "index"
    save_bm25_index(build_bm25_index((chunk("a"), chunk("b")), source_sha256="sha"), output_dir)

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["record_count"] = 999
    (output_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    try:
        load_bm25_index(output_dir)
    except RetrievalIndexError as error:
        assert "record_count" in str(error)

    save_bm25_index(
        build_bm25_index((chunk("a"), chunk("b")), source_sha256="sha"), output_dir, overwrite=True
    )
    records = [
        json.loads(line)
        for line in (output_dir / "records.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    records[1]["record_index"] = 3
    (output_dir / "records.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    try:
        load_bm25_index(output_dir)
    except RetrievalIndexError as error:
        assert "record_index" in str(error)

    save_bm25_index(
        build_bm25_index((chunk("a"), chunk("b")), source_sha256="sha"), output_dir, overwrite=True
    )
    records = [
        json.loads(line)
        for line in (output_dir / "records.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    records[1]["chunk_id"] = records[0]["chunk_id"]
    (output_dir / "records.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    try:
        load_bm25_index(output_dir)
    except RetrievalIndexError as error:
        assert "重複chunk_id" in str(error)


def test_save_search_results_writes_json_and_preserves_order(tmp_path: Path) -> None:
    """検索結果JSONを順序を保って保存できる。"""
    index = build_bm25_index((chunk("a"),), source_sha256="sha")
    result = Bm25Retriever(
        load_bm25_index(_saved_index(tmp_path, index)),
    ).search("契約", 1)
    output_path = tmp_path / "result.json"

    save_search_results(output_path, query="契約", top_k=1, results=result)

    record = json.loads(output_path.read_text(encoding="utf-8"))
    assert record["query"] == "契約"
    assert record["results"][0]["chunk_id"] == "a"
    assert not any(path.name.endswith(".tmp") for path in tmp_path.iterdir())


def _saved_index(tmp_path: Path, index) -> Path:  # type: ignore[no-untyped-def]
    """テスト内で保存済みインデックスを用意する。"""
    output_dir = tmp_path / "saved-index"
    save_bm25_index(index, output_dir)
    return output_dir
