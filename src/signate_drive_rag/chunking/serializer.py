"""検索用チャンク生成結果をJSON/JSONLへ保存する処理。"""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from signate_drive_rag.chunking.models import (
    ChunkingResult,
    ChunkingSummary,
    ChunkIssue,
    RetrievalChunk,
)

CHUNKS_FILE_NAME = "chunks.jsonl"
SUMMARY_FILE_NAME = "summary.json"
ISSUES_FILE_NAME = "issues.jsonl"


def save_chunking_result(result: ChunkingResult, output_dir: Path) -> None:
    """チャンク生成結果を指定ディレクトリへ保存する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl_atomic(
        output_dir / CHUNKS_FILE_NAME,
        (_chunk_to_record(chunk) for chunk in sorted(result.chunks, key=_chunk_sort_key)),
    )
    _write_json_atomic(output_dir / SUMMARY_FILE_NAME, _summary_to_record(result.summary))
    _write_jsonl_atomic(
        output_dir / ISSUES_FILE_NAME,
        (_issue_to_record(issue) for issue in sorted(result.issues, key=_issue_sort_key)),
    )


def _write_jsonl_atomic(path: Path, records: Iterable[dict[str, Any]]) -> None:
    """JSONLを一時ファイルへ書き、成功後に置き換える。"""
    temporary_path = path.with_name(f"{path.name}.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as output_file:
            for record in records:
                output_file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        temporary_path.replace(path)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def _write_json_atomic(path: Path, record: dict[str, Any]) -> None:
    """JSONを一時ファイルへ書き、成功後に置き換える。"""
    temporary_path = path.with_name(f"{path.name}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def _chunk_to_record(chunk: RetrievalChunk) -> dict[str, Any]:
    """RetrievalChunkをJSON互換の辞書へ変換する。"""
    return {
        "chunk_id": chunk.chunk_id,
        "relative_path": chunk.relative_path,
        "parser_name": chunk.parser_name,
        "unit_type": chunk.unit_type,
        "text": chunk.text,
        "locator": chunk.locator,
        "source_unit_indices": list(chunk.source_unit_indices),
        "chunk_index": chunk.chunk_index,
        "metadata": chunk.metadata,
    }


def _issue_to_record(issue: ChunkIssue) -> dict[str, Any]:
    """ChunkIssueをJSON互換の辞書へ変換する。"""
    return {
        "relative_path": issue.relative_path,
        "parser_name": issue.parser_name,
        "issue_type": issue.issue_type,
        "severity": issue.severity,
        "message": issue.message,
        "source_unit_index": issue.source_unit_index,
        "locator": issue.locator,
    }


def _summary_to_record(summary: ChunkingSummary) -> dict[str, Any]:
    """ChunkingSummaryをJSON互換の辞書へ変換する。"""
    return {
        "source_documents": summary.source_documents,
        "source_units": summary.source_units,
        "source_characters": summary.source_characters,
        "generated_chunks": summary.generated_chunks,
        "chunk_characters": summary.chunk_characters,
        "maximum_chunk_characters": summary.maximum_chunk_characters,
        "average_chunk_characters": summary.average_chunk_characters,
        "character_reduction_rate": summary.character_reduction_rate,
        "empty_units_skipped": summary.empty_units_skipped,
        "fallback_units": summary.fallback_units,
        "total_issues": summary.total_issues,
        "issues_by_severity": dict(sorted(summary.issues_by_severity.items())),
        "issues_by_type": dict(sorted(summary.issues_by_type.items())),
        "by_parser": dict(sorted(summary.by_parser.items())),
        "by_unit_type": dict(sorted(summary.by_unit_type.items())),
    }


def _chunk_sort_key(chunk: RetrievalChunk) -> tuple[str, int]:
    """チャンクを決定的に並べるキーを返す。"""
    return (chunk.relative_path, chunk.chunk_index)


def _issue_sort_key(issue: ChunkIssue) -> tuple[str, int, str]:
    """issueを決定的に並べるキーを返す。"""
    source_unit_index = -1 if issue.source_unit_index is None else issue.source_unit_index
    return (issue.relative_path, source_unit_index, issue.issue_type)
