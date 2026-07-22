"""検索用チャンク検証結果を保存する処理。"""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from signate_drive_rag.chunk_validation.models import (
    ChunkValidationError,
    ChunkValidationResult,
    ChunkValidationSummary,
)


def save_chunk_validation_result(result: ChunkValidationResult, output_dir: Path) -> None:
    """検証結果をJSON/JSONL/Markdownで保存する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(output_dir / "summary.json", _summary_to_record(result.summary))
    _write_jsonl_atomic(
        output_dir / "errors.jsonl",
        (_error_to_record(error) for error in result.errors),
    )
    _write_text_atomic(output_dir / "report.md", _build_report(result.summary))


def _write_json_atomic(path: Path, record: dict[str, Any]) -> None:
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


def _write_jsonl_atomic(path: Path, records: Iterable[dict[str, Any]]) -> None:
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


def _write_text_atomic(path: Path, text: str) -> None:
    temporary_path = path.with_name(f"{path.name}.tmp")
    try:
        temporary_path.write_text(text, encoding="utf-8", newline="\n")
        temporary_path.replace(path)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def _summary_to_record(summary: ChunkValidationSummary) -> dict[str, Any]:
    return {
        "chunks": summary.chunks,
        "source_documents": summary.source_documents,
        "source_units": summary.source_units,
        "errors": summary.errors,
        "warnings": summary.warnings,
        "duplicate_chunk_ids": summary.duplicate_chunk_ids,
        "duplicate_chunk_contents": summary.duplicate_chunk_contents,
        "empty_text_chunks": summary.empty_text_chunks,
        "nul_text_chunks": summary.nul_text_chunks,
        "invalid_document_references": summary.invalid_document_references,
        "invalid_unit_references": summary.invalid_unit_references,
        "absolute_path_violations": summary.absolute_path_violations,
        "invalid_locator_count": summary.invalid_locator_count,
        "json_metadata_errors": summary.json_metadata_errors,
        "oversized_chunks": summary.oversized_chunks,
        "maximum_chunk_characters": summary.maximum_chunk_characters,
        "mean_chunk_characters": summary.mean_chunk_characters,
        "median_chunk_characters": summary.median_chunk_characters,
        "p95_chunk_characters": summary.p95_chunk_characters,
        "text_chunks": summary.text_chunks,
        "table_chunks": summary.table_chunks,
        "ocr_chunks": summary.ocr_chunks,
    }


def _error_to_record(error: ChunkValidationError) -> dict[str, Any]:
    return {
        "chunk_id": error.chunk_id,
        "relative_path": error.relative_path,
        "issue_type": error.issue_type,
        "severity": error.severity,
        "message": error.message,
        "locator": error.locator,
    }


def _build_report(summary: ChunkValidationSummary) -> str:
    return "\n".join(
        [
            "# チャンク検証レポート",
            "",
            "| 指標 | 件数 |",
            "|---|---:|",
            f"| チャンク数 | {summary.chunks} |",
            f"| error | {summary.errors} |",
            f"| warning | {summary.warnings} |",
            f"| 重複chunk_id | {summary.duplicate_chunk_ids} |",
            f"| 重複本文 | {summary.duplicate_chunk_contents} |",
            f"| 空本文 | {summary.empty_text_chunks} |",
            f"| NUL文字 | {summary.nul_text_chunks} |",
            f"| 参照不能文書 | {summary.invalid_document_references} |",
            f"| 参照不能unit | {summary.invalid_unit_references} |",
            f"| 絶対パス | {summary.absolute_path_violations} |",
            f"| locator不正 | {summary.invalid_locator_count} |",
            f"| metadata不正 | {summary.json_metadata_errors} |",
            "",
        ]
    )
