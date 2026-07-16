"""検索評価で使用する不変モデル。"""

from dataclasses import dataclass

from signate_drive_rag.domain.extracted_document import JsonValue


@dataclass(frozen=True, slots=True)
class ExpectedRelevantResult:
    """評価上、関連すると定義した検索対象。"""

    relative_path: str
    locator: str | None


@dataclass(frozen=True, slots=True)
class SearchEvaluationQuery:
    """検索評価に使用する質問。"""

    query_id: str
    query: str
    query_type: str
    expected_relevant: tuple[ExpectedRelevantResult, ...]
    notes: str


@dataclass(frozen=True, slots=True)
class EvaluatedSearchResult:
    """評価情報を付与した検索結果。"""

    rank: int
    chunk_id: str
    relative_path: str
    locator: str | None
    parser_name: str
    unit_type: str
    score: float
    channel_ranks: dict[str, int]
    text: str
    metadata: dict[str, JsonValue]
    is_expected_match: bool


@dataclass(frozen=True, slots=True)
class QueryEvaluationResult:
    """1質問に対する検索評価結果。"""

    query_id: str
    query: str
    query_type: str
    is_auto_evaluated: bool
    hit_at_1: bool | None
    hit_at_3: bool | None
    hit_at_5: bool | None
    hit_at_10: bool | None
    first_relevant_rank: int | None
    reciprocal_rank: float | None
    results: tuple[EvaluatedSearchResult, ...]
    notes: str


@dataclass(frozen=True, slots=True)
class SearchEvaluationSummary:
    """複数質問による検索評価の集計結果。"""

    total_queries: int
    auto_evaluated_queries: int
    manual_review_queries: int
    hit_at_1_count: int
    hit_at_1_rate: float
    hit_at_3_count: int
    hit_at_3_rate: float
    hit_at_5_count: int
    hit_at_5_rate: float
    hit_at_10_count: int
    hit_at_10_rate: float
    mean_reciprocal_rank: float
    queries_with_no_results: int
    by_query_type: dict[str, JsonValue]
    index_source_sha256: str
    query_file_sha256: str
    top_k: int
    candidate_multiplier: int
    rrf_k: int
    preview_chars: int
    report_results_per_query: int


@dataclass(frozen=True, slots=True)
class SearchEvaluationResult:
    """複数質問による検索評価の結果。"""

    query_results: tuple[QueryEvaluationResult, ...]
    summary: SearchEvaluationSummary
