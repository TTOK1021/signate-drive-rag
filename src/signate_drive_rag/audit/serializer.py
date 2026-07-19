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
REPORT_FILE_NAME = "report.md"


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
    _write_text_atomic(output_dir / REPORT_FILE_NAME, _build_report(result))


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


def _write_text_atomic(path: Path, text: str) -> None:
    """テキストを一時ファイルへ書き、成功後に置き換える。"""
    temporary_path = path.with_name(f"{path.name}.tmp")
    try:
        temporary_path.write_text(text, encoding="utf-8", newline="\n")
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
        "pdf_pages": summary.pdf_pages,
        "pdf_pages_with_text": summary.pdf_pages_with_text,
        "pdf_pages_needing_ocr": summary.pdf_pages_needing_ocr,
        "total_issues": summary.total_issues,
        "issues_by_severity": dict(sorted(summary.issues_by_severity.items())),
        "issues_by_type": dict(sorted(summary.issues_by_type.items())),
        "units_by_type": dict(sorted(summary.units_by_type.items())),
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
        "issues": summary.issues,
        "document_character_statistics": _distribution_to_record(
            summary.document_character_statistics
        ),
        "unit_character_statistics": _distribution_to_record(summary.unit_character_statistics),
    }


def _build_report(result: AuditResult) -> str:
    """主要なOffice・PDF抽出品質をMarkdownで要約する。"""
    summary = result.summary
    lines = [
        "# 抽出品質監査レポート",
        "",
        "## Office・PDF抽出結果",
        "",
        "| parser | 文書数 | unit数 | 文字数 | issue数 |",
        "|---|---:|---:|---:|---:|",
    ]
    for parser_name in ("docling_docx", "docling_pptx", "pypdf"):
        parser_summary = summary.by_parser.get(parser_name)
        if parser_summary is None:
            lines.append(f"| {parser_name} | 0 | 0 | 0 | 0 |")
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    parser_name,
                    str(parser_summary.documents),
                    str(parser_summary.units),
                    str(parser_summary.characters),
                    str(parser_summary.issues),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## PDF OCR候補",
            "",
            f"- PDFページ数: {summary.pdf_pages}",
            f"- テキストありページ: {summary.pdf_pages_with_text}",
            f"- OCR候補ページ: {summary.pdf_pages_needing_ocr}",
            f"- OCR候補文書: {_pdf_documents_with_ocr_issue(result)}",
            "",
        ]
    )
    return "\n".join(lines)


def _pdf_documents_with_ocr_issue(result: AuditResult) -> int:
    return len(
        {
            issue.relative_path
            for issue in result.issues
            if issue.issue_type
            in {"pdf_page_needs_ocr", "pdf_partially_needs_ocr", "image_dominant_document"}
        }
    )


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
        "metadata": issue.metadata or {},
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
