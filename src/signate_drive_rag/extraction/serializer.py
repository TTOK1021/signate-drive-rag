"""一括抽出結果をJSONL/JSONへ保存する処理。"""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from signate_drive_rag.domain import ExtractedDocument, ExtractedUnit, ExtractionIssue, SourceFile
from signate_drive_rag.extraction.models import (
    BatchExtractionResult,
    ExtractionFailure,
    ExtractionSummary,
)

DOCUMENTS_FILE_NAME = "documents.jsonl"
FAILURES_FILE_NAME = "failures.jsonl"
UNSUPPORTED_FILE_NAME = "unsupported.jsonl"
SUMMARY_FILE_NAME = "summary.json"


def save_extraction_result(result: BatchExtractionResult, output_dir: Path) -> None:
    """一括抽出結果を指定ディレクトリへ保存する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    documents = sorted(result.documents, key=_document_sort_key)
    failures = sorted(result.failures, key=_failure_sort_key)
    unsupported_files = sorted(result.unsupported_files, key=_source_file_sort_key)
    _write_jsonl_atomic(
        output_dir / DOCUMENTS_FILE_NAME,
        (_document_to_record(document) for document in documents),
    )
    _write_jsonl_atomic(
        output_dir / FAILURES_FILE_NAME,
        (_failure_to_record(failure) for failure in failures),
    )
    _write_jsonl_atomic(
        output_dir / UNSUPPORTED_FILE_NAME,
        (_unsupported_to_record(source_file) for source_file in unsupported_files),
    )
    _write_json_atomic(output_dir / SUMMARY_FILE_NAME, _summary_to_record(result.summary))


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


def _document_to_record(document: ExtractedDocument) -> dict[str, Any]:
    """ExtractedDocumentをJSON互換の辞書へ変換する。"""
    return {
        "source": _source_file_to_record(document.source_file),
        "parser_name": document.parser_name,
        "units": [_unit_to_record(unit) for unit in document.units],
        "issues": [_issue_to_record(issue) for issue in document.issues],
    }


def _source_file_to_record(source_file: SourceFile) -> dict[str, Any]:
    """SourceFileを絶対パスなしのJSON互換辞書へ変換する。"""
    return {
        "relative_path": source_file.relative_path.as_posix(),
        "name": source_file.name,
        "suffix": source_file.suffix,
        "mime_type": source_file.mime_type,
        "size_bytes": source_file.size_bytes,
        "modified_at": source_file.modified_at.isoformat(),
    }


def _unit_to_record(unit: ExtractedUnit) -> dict[str, Any]:
    """ExtractedUnitをJSON互換の辞書へ変換する。"""
    return {
        "unit_type": unit.unit_type,
        "text": unit.text,
        "locator": unit.locator,
        "metadata": unit.metadata,
    }


def _issue_to_record(issue: ExtractionIssue) -> dict[str, Any]:
    """ExtractionIssueをJSON互換の辞書へ変換する。"""
    return {
        "issue_type": issue.issue_type,
        "severity": issue.severity,
        "message": issue.message,
        "locator": issue.locator,
        "metadata": issue.metadata,
    }


def _failure_to_record(failure: ExtractionFailure) -> dict[str, Any]:
    """ExtractionFailureをJSON互換の辞書へ変換する。"""
    return {
        "relative_path": failure.source_file.relative_path.as_posix(),
        "suffix": failure.source_file.suffix,
        "parser_name": failure.parser_name,
        "error_type": failure.error_type,
        "error_message": failure.error_message,
    }


def _unsupported_to_record(source_file: SourceFile) -> dict[str, Any]:
    """未対応SourceFileをJSON互換の辞書へ変換する。"""
    return {
        "relative_path": source_file.relative_path.as_posix(),
        "name": source_file.name,
        "suffix": source_file.suffix,
        "mime_type": source_file.mime_type,
        "size_bytes": source_file.size_bytes,
    }


def _summary_to_record(summary: ExtractionSummary) -> dict[str, Any]:
    """ExtractionSummaryをJSON互換の辞書へ変換する。"""
    return {
        "discovered_files": summary.discovered_files,
        "supported_files": summary.supported_files,
        "succeeded_files": summary.succeeded_files,
        "failed_files": summary.failed_files,
        "unsupported_files": summary.unsupported_files,
        "total_units": summary.total_units,
        "total_characters": summary.total_characters,
        "total_issues": summary.total_issues,
        "by_parser": dict(sorted(summary.by_parser.items())),
        "by_suffix": dict(sorted(summary.by_suffix.items())),
        "issues_by_type": dict(sorted(summary.issues_by_type.items())),
    }


def _source_file_sort_key(source_file: SourceFile) -> str:
    """SourceFileを相対パス順に並べるためのキーを返す。"""
    return source_file.relative_path.as_posix()


def _document_sort_key(document: ExtractedDocument) -> str:
    """ExtractedDocumentを原本相対パス順に並べるためのキーを返す。"""
    return _source_file_sort_key(document.source_file)


def _failure_sort_key(failure: ExtractionFailure) -> str:
    """ExtractionFailureを原本相対パス順に並べるためのキーを返す。"""
    return _source_file_sort_key(failure.source_file)
