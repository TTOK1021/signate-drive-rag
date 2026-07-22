"""検索評価ベースライン比較のモデル。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QueryComparisonResult:
    """1質問に対する旧・新検索結果の比較。"""

    query_id: str
    query: str
    old_top_paths: tuple[str, ...]
    new_top_paths: tuple[str, ...]
    top1_changed: bool
    top5_overlap_count: int
    top5_jaccard: float
    newly_retrieved_paths: tuple[str, ...]
    removed_paths: tuple[str, ...]
    new_office_or_pdf_result_count: int
    new_xlsx_result_count: int
    new_ocr_result_count: int


@dataclass(frozen=True, slots=True)
class BaselineComparisonSummary:
    """旧・新検索評価比較の集計。"""

    compared_queries: int
    top1_changed_queries: int
    top5_changed_queries: int
    average_top5_jaccard: float
    old_queries_with_no_results: int
    new_queries_with_no_results: int
    no_result_delta: int
    docx_new_top5_queries: int
    pptx_new_top5_queries: int
    pdf_new_top5_queries: int
    xlsx_new_top5_queries: int
    ocr_new_top5_queries: int


@dataclass(frozen=True, slots=True)
class BaselineComparisonResult:
    """旧・新検索評価比較の結果。"""

    summary: BaselineComparisonSummary
    query_results: tuple[QueryComparisonResult, ...]
