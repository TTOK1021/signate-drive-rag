"""監査結果をJSON/JSONLへ保存する処理。"""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from signate_drive_rag.audit.models import (
    AuditIssue,
    AuditResult,
    AuditSampleDocument,
    AuditSampleUnit,
    AuditSummary,
    DistributionStatistics,
    ParserAuditSummary,
)

SUMMARY_FILE_NAME = "summary.json"
ISSUES_FILE_NAME = "issues.jsonl"
SAMPLES_FILE_NAME = "samples.jsonl"


def save_audit_result(result: AuditResult, output_dir: Path) -> None:
    """監査結果を指定ディレクトリへ保存する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(output_dir / SUMMARY_FILE_NAME, _summary_to_record(result.summary))
    _write_jsonl_atomic(
        output_dir / ISSUES_FILE_NAME,
        (_issue_to_record(issue) for issue in sorted(result.issues, key=_issue_sort_key)),
    )
    _write_jsonl_atomic(
        output_dir / SAMPLES_FILE_NAME,
        (
            _sample_document_to_record(sample)
            for sample in sorted(
                result.samples, key=lambda item: (item.parser_name, item.relative_path)
            )
        ),
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


def _summary_to_record(summary: AuditSummary) -> dict[str, Any]:
    """AuditSummaryをJSON互換の辞書へ変換する。"""
    return {
        "documents": summary.documents,
        "total_units": summary.total_units,
        "total_characters": summary.total_characters,
        "total_source_bytes": summary.total_source_bytes,
        "documents_with_no_units": summary.documents_with_no_units,
        "documents_with_no_text": summary.documents_with_no_text,
        "empty_units": summary.empty_units,
        "units_without_required_locator": summary.units_without_required_locator,
        "duplicate_units": summary.duplicate_units,
        "large_units": summary.large_units,
        "total_issues": summary.total_issues,
        "issues_by_severity": dict(sorted(summary.issues_by_severity.items())),
        "issues_by_type": dict(sorted(summary.issues_by_type.items())),
        "by_parser": {
            parser_name: _parser_summary_to_record(parser_summary)
            for parser_name, parser_summary in sorted(summary.by_parser.items())
        },
        "document_character_statistics": _distribution_to_record(
            summary.document_character_statistics
        ),
        "unit_character_statistics": _distribution_to_record(summary.unit_character_statistics),
    }


def _parser_summary_to_record(summary: ParserAuditSummary) -> dict[str, Any]:
    """ParserAuditSummaryをJSON互換の辞書へ変換する。"""
    return {
        "documents": summary.documents,
        "units": summary.units,
        "characters": summary.characters,
        "source_bytes": summary.source_bytes,
        "documents_with_no_units": summary.documents_with_no_units,
        "documents_with_no_text": summary.documents_with_no_text,
        "empty_units": summary.empty_units,
        "units_without_required_locator": summary.units_without_required_locator,
        "duplicate_units": summary.duplicate_units,
        "document_character_statistics": _distribution_to_record(
            summary.document_character_statistics
        ),
        "unit_character_statistics": _distribution_to_record(summary.unit_character_statistics),
    }


def _distribution_to_record(statistics: DistributionStatistics) -> dict[str, Any]:
    """DistributionStatisticsをJSON互換の辞書へ変換する。"""
    return {
        "count": statistics.count,
        "minimum": statistics.minimum,
        "maximum": statistics.maximum,
        "mean": statistics.mean,
        "median": statistics.median,
        "percentile_95": statistics.percentile_95,
    }


def _issue_to_record(issue: AuditIssue) -> dict[str, Any]:
    """AuditIssueをJSON互換の辞書へ変換する。"""
    return {
        "relative_path": issue.relative_path,
        "parser_name": issue.parser_name,
        "issue_type": issue.issue_type,
        "severity": issue.severity,
        "message": issue.message,
        "unit_index": issue.unit_index,
        "locator": issue.locator,
    }


def _sample_document_to_record(sample: AuditSampleDocument) -> dict[str, Any]:
    """AuditSampleDocumentをJSON互換の辞書へ変換する。"""
    return {
        "relative_path": sample.relative_path,
        "parser_name": sample.parser_name,
        "source_size_bytes": sample.source_size_bytes,
        "unit_count": sample.unit_count,
        "character_count": sample.character_count,
        "sample_units": [_sample_unit_to_record(unit) for unit in sample.sample_units],
    }


def _sample_unit_to_record(unit: AuditSampleUnit) -> dict[str, Any]:
    """AuditSampleUnitをJSON互換の辞書へ変換する。"""
    return {
        "unit_index": unit.unit_index,
        "unit_type": unit.unit_type,
        "locator": unit.locator,
        "text_preview": unit.text_preview,
    }


def _issue_sort_key(issue: AuditIssue) -> tuple[str, int, str]:
    """issue出力を決定的に並べるためのキーを返す。"""
    unit_index = -1 if issue.unit_index is None else issue.unit_index
    return (issue.relative_path, unit_index, issue.issue_type)
