"""検索評価ベースライン比較結果を保存する処理。"""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from signate_drive_rag.baseline_comparison.models import (
    BaselineComparisonResult,
    BaselineComparisonSummary,
    QueryComparisonResult,
)


def save_baseline_comparison_result(
    result: BaselineComparisonResult,
    output_dir: Path,
) -> None:
    """比較結果をJSON/JSONL/Markdownで保存する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(output_dir / "summary.json", _summary_to_record(result.summary))
    _write_jsonl_atomic(
        output_dir / "query_diff.jsonl",
        (_query_to_record(query_result) for query_result in result.query_results),
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


def _summary_to_record(summary: BaselineComparisonSummary) -> dict[str, Any]:
    return {
        "compared_queries": summary.compared_queries,
        "top1_changed_queries": summary.top1_changed_queries,
        "top5_changed_queries": summary.top5_changed_queries,
        "average_top5_jaccard": summary.average_top5_jaccard,
        "old_queries_with_no_results": summary.old_queries_with_no_results,
        "new_queries_with_no_results": summary.new_queries_with_no_results,
        "no_result_delta": summary.no_result_delta,
        "docx_new_top5_queries": summary.docx_new_top5_queries,
        "pptx_new_top5_queries": summary.pptx_new_top5_queries,
        "pdf_new_top5_queries": summary.pdf_new_top5_queries,
        "xlsx_new_top5_queries": summary.xlsx_new_top5_queries,
        "ocr_new_top5_queries": summary.ocr_new_top5_queries,
    }


def _query_to_record(result: QueryComparisonResult) -> dict[str, Any]:
    return {
        "query_id": result.query_id,
        "query": result.query,
        "old_top_paths": list(result.old_top_paths),
        "new_top_paths": list(result.new_top_paths),
        "top1_changed": result.top1_changed,
        "top5_overlap_count": result.top5_overlap_count,
        "top5_jaccard": result.top5_jaccard,
        "newly_retrieved_paths": list(result.newly_retrieved_paths),
        "removed_paths": list(result.removed_paths),
        "new_office_or_pdf_result_count": result.new_office_or_pdf_result_count,
        "new_xlsx_result_count": result.new_xlsx_result_count,
        "new_ocr_result_count": result.new_ocr_result_count,
    }


def _build_report(summary: BaselineComparisonSummary) -> str:
    return "\n".join(
        [
            "# 旧ベースライン比較レポート",
            "",
            "自動正解ラベルがない場合、改善・悪化は断定しません。",
            "",
            "| 指標 | 件数 |",
            "|---|---:|",
            f"| 比較質問数 | {summary.compared_queries} |",
            f"| Top1変化 | {summary.top1_changed_queries} |",
            f"| Top5変化 | {summary.top5_changed_queries} |",
            f"| Top5平均Jaccard | {summary.average_top5_jaccard:.4f} |",
            f"| 検索結果0件増減 | {summary.no_result_delta} |",
            f"| DOCX新規Top5質問 | {summary.docx_new_top5_queries} |",
            f"| PPTX新規Top5質問 | {summary.pptx_new_top5_queries} |",
            f"| PDF新規Top5質問 | {summary.pdf_new_top5_queries} |",
            f"| XLSX新規Top5質問 | {summary.xlsx_new_top5_queries} |",
            f"| OCR新規Top5質問 | {summary.ocr_new_top5_queries} |",
            "",
        ]
    )
