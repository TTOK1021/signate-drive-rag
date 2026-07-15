"""チャンク生成結果シリアライザーの単体テスト。"""

import json
from pathlib import Path

from signate_drive_rag.chunking.models import (
    ChunkingResult,
    ChunkingSummary,
    ChunkIssue,
    RetrievalChunk,
)
from signate_drive_rag.chunking.serializer import save_chunking_result


def result(include_issue: bool = True) -> ChunkingResult:
    """テスト用チャンク生成結果を作成する。"""
    chunks = (
        RetrievalChunk(
            chunk_id="a" * 64,
            relative_path="案件/資料.txt",
            parser_name="plain_text",
            unit_type="text",
            text="日本語本文",
            locator=None,
            source_unit_indices=(0,),
            chunk_index=0,
            metadata={"source_locator": None},
        ),
    )
    issues = (
        (
            ChunkIssue(
                relative_path="案件/資料.txt",
                parser_name="plain_text",
                issue_type="empty_source_unit_skipped",
                severity="info",
                message="空unit",
                source_unit_index=1,
                locator=None,
            ),
        )
        if include_issue
        else ()
    )
    summary = ChunkingSummary(
        source_documents=1,
        source_units=1,
        source_characters=5,
        generated_chunks=1,
        chunk_characters=5,
        maximum_chunk_characters=5,
        average_chunk_characters=5.0,
        character_reduction_rate=0.0,
        empty_units_skipped=0,
        fallback_units=0,
        total_issues=len(issues),
        issues_by_severity={"error": 0, "warning": 0, "info": len(issues)},
        issues_by_type={
            "source_document_has_no_units": 0,
            "empty_source_unit_skipped": len(issues),
            "fallback_chunking_used": 0,
            "table_metadata_missing": 0,
            "chunk_limit_violation": 0,
        },
        by_parser={"plain_text": {"generated_chunks": 1}},
        by_unit_type={"text": {"generated_chunks": 1}},
    )
    return ChunkingResult(chunks=chunks, issues=issues, summary=summary)


def test_save_chunking_result_writes_valid_jsonl_and_summary(tmp_path: Path) -> None:
    """chunks.jsonlとsummary.jsonを有効なJSONとして保存する。"""
    output_dir = tmp_path / "chunks"

    save_chunking_result(result(), output_dir)

    chunk = json.loads((output_dir / "chunks.jsonl").read_text(encoding="utf-8"))
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    issue = json.loads((output_dir / "issues.jsonl").read_text(encoding="utf-8"))
    assert chunk["text"] == "日本語本文"
    assert "path" not in chunk
    assert summary["generated_chunks"] == 1
    assert issue["issue_type"] == "empty_source_unit_skipped"


def test_save_chunking_result_writes_empty_issues_file(tmp_path: Path) -> None:
    """issueが0件でも空のissues.jsonlを生成する。"""
    output_dir = tmp_path / "chunks"

    save_chunking_result(result(include_issue=False), output_dir)

    assert (output_dir / "issues.jsonl").read_text(encoding="utf-8") == ""


def test_save_chunking_result_creates_output_replaces_files_and_removes_tmp(
    tmp_path: Path,
) -> None:
    """出力先作成、既存ファイル置換、tmp削除を確認する。"""
    output_dir = tmp_path / "chunks"
    output_dir.mkdir()
    (output_dir / "summary.json").write_text("old", encoding="utf-8")

    save_chunking_result(result(), output_dir)

    assert (
        json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))["source_documents"]
        == 1
    )
    assert list(output_dir.glob("*.tmp")) == []


def test_save_chunking_result_keeps_deterministic_output(tmp_path: Path) -> None:
    """同じ入力を2回保存しても出力が変わらない。"""
    output_dir = tmp_path / "chunks"
    chunking_result = result()

    save_chunking_result(chunking_result, output_dir)
    first = (output_dir / "chunks.jsonl").read_text(encoding="utf-8")
    save_chunking_result(chunking_result, output_dir)
    second = (output_dir / "chunks.jsonl").read_text(encoding="utf-8")

    assert first == second
