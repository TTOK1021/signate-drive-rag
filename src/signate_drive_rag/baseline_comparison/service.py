"""旧BM25評価結果と新評価結果を比較するサービス。"""

import json
from pathlib import Path
from typing import Any

from signate_drive_rag.baseline_comparison.models import (
    BaselineComparisonResult,
    BaselineComparisonSummary,
    QueryComparisonResult,
)


class BaselineComparisonService:
    """検索評価結果の差分を機械的に集計する。"""

    def compare(self, *, baseline_dir: Path, current_dir: Path) -> BaselineComparisonResult:
        """旧・新のquery_results.jsonlを読み込み、質問単位で比較する。"""
        old_results = _load_query_results(baseline_dir / "query_results.jsonl")
        new_results = _load_query_results(current_dir / "query_results.jsonl")
        query_ids = sorted(set(old_results) & set(new_results))
        comparisons = tuple(
            _compare_query(old_results[query_id], new_results[query_id]) for query_id in query_ids
        )
        return BaselineComparisonResult(
            summary=_build_summary(comparisons),
            query_results=comparisons,
        )


def _load_query_results(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"検索評価結果が存在しません: {path}")
    results: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number}: JSON objectが必要です。")
            query_id = record.get("query_id")
            if not isinstance(query_id, str) or query_id == "":
                raise ValueError(f"{path}:{line_number}: query_idが不正です。")
            results[query_id] = record
    return results


def _compare_query(
    old_record: dict[str, Any],
    new_record: dict[str, Any],
) -> QueryComparisonResult:
    old_results = _result_records(old_record)
    new_results = _result_records(new_record)
    old_top_paths = _top_paths(old_results)
    new_top_paths = _top_paths(new_results)
    old_top5_set = set(old_top_paths)
    new_top5_set = set(new_top_paths)
    overlap = old_top5_set & new_top5_set
    union = old_top5_set | new_top5_set
    newly_retrieved_paths = tuple(sorted(new_top5_set - old_top5_set))
    removed_paths = tuple(sorted(old_top5_set - new_top5_set))
    return QueryComparisonResult(
        query_id=_string_field(new_record, "query_id"),
        query=_string_field(new_record, "query"),
        old_top_paths=old_top_paths,
        new_top_paths=new_top_paths,
        top1_changed=_first_or_empty(old_top_paths) != _first_or_empty(new_top_paths),
        top5_overlap_count=len(overlap),
        top5_jaccard=0.0 if not union else len(overlap) / len(union),
        newly_retrieved_paths=newly_retrieved_paths,
        removed_paths=removed_paths,
        new_office_or_pdf_result_count=sum(
            1 for result in new_results[:5] if _is_office_or_pdf_result(result)
        ),
        new_xlsx_result_count=sum(1 for result in new_results[:5] if _suffix(result) == ".xlsx"),
        new_ocr_result_count=sum(1 for result in new_results[:5] if _is_ocr_result(result)),
    )


def _result_records(record: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    value = record.get("results")
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _top_paths(results: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    return tuple(_string_field(result, "relative_path") for result in results[:5])


def _first_or_empty(values: tuple[str, ...]) -> str:
    return values[0] if values else ""


def _string_field(record: dict[str, Any], field_name: str) -> str:
    value = record.get(field_name)
    return value if isinstance(value, str) else ""


def _suffix(result: dict[str, Any]) -> str:
    path = _string_field(result, "relative_path")
    return Path(path).suffix.lower()


def _is_office_or_pdf_result(result: dict[str, Any]) -> bool:
    return _suffix(result) in {".docx", ".pptx", ".pdf"}


def _is_ocr_result(result: dict[str, Any]) -> bool:
    if "ocr" in _string_field(result, "unit_type"):
        return True
    metadata = result.get("metadata")
    if not isinstance(metadata, dict):
        return False
    return "ocr_engine" in metadata or "ocr" in str(metadata.get("extraction_method", ""))


def _build_summary(
    comparisons: tuple[QueryComparisonResult, ...],
) -> BaselineComparisonSummary:
    compared = len(comparisons)
    return BaselineComparisonSummary(
        compared_queries=compared,
        top1_changed_queries=sum(1 for result in comparisons if result.top1_changed),
        top5_changed_queries=sum(
            1 for result in comparisons if result.newly_retrieved_paths or result.removed_paths
        ),
        average_top5_jaccard=(
            0.0 if compared == 0 else sum(result.top5_jaccard for result in comparisons) / compared
        ),
        old_queries_with_no_results=sum(1 for result in comparisons if not result.old_top_paths),
        new_queries_with_no_results=sum(1 for result in comparisons if not result.new_top_paths),
        no_result_delta=(
            sum(1 for result in comparisons if not result.new_top_paths)
            - sum(1 for result in comparisons if not result.old_top_paths)
        ),
        docx_new_top5_queries=_new_suffix_queries(comparisons, ".docx"),
        pptx_new_top5_queries=_new_suffix_queries(comparisons, ".pptx"),
        pdf_new_top5_queries=_new_suffix_queries(comparisons, ".pdf"),
        xlsx_new_top5_queries=_new_suffix_queries(comparisons, ".xlsx"),
        ocr_new_top5_queries=sum(1 for result in comparisons if result.new_ocr_result_count > 0),
    )


def _new_suffix_queries(
    comparisons: tuple[QueryComparisonResult, ...],
    suffix: str,
) -> int:
    return sum(
        1
        for result in comparisons
        if any(
            Path(relative_path).suffix.lower() == suffix for relative_path in result.new_top_paths
        )
    )
