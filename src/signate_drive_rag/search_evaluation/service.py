"""BM25検索結果を複数質問で評価する処理。"""

from collections import defaultdict

from signate_drive_rag.domain.extracted_document import JsonValue
from signate_drive_rag.retrieval import Retriever
from signate_drive_rag.retrieval.models import SearchResult
from signate_drive_rag.search_evaluation.models import (
    EvaluatedSearchResult,
    ExpectedRelevantResult,
    QueryEvaluationResult,
    SearchEvaluationQuery,
    SearchEvaluationResult,
    SearchEvaluationSummary,
)


def is_expected_match(
    search_result: SearchResult | EvaluatedSearchResult,
    expected: ExpectedRelevantResult,
) -> bool:
    """検索結果が評価用期待結果に一致するか判定する。"""
    if search_result.relative_path != expected.relative_path:
        return False
    if expected.locator is None:
        return True
    return search_result.locator == expected.locator


class SearchEvaluationService:
    """複数質問に対して検索を実行し、検索性能を評価する。"""

    def __init__(self, retriever: Retriever) -> None:
        """検索器を1つだけ保持する。"""
        self._retriever = retriever

    def evaluate(
        self,
        queries: tuple[SearchEvaluationQuery, ...],
        *,
        top_k: int,
        index_source_sha256: str,
        query_file_sha256: str,
        candidate_multiplier: int,
        rrf_k: int,
        preview_chars: int,
        report_results_per_query: int,
    ) -> SearchEvaluationResult:
        """質問入力順に検索し、質問単位と全体の指標を計算する。"""
        if top_k <= 0:
            raise ValueError("top_kは1以上である必要があります。")
        query_results = tuple(self._evaluate_query(query, top_k=top_k) for query in queries)
        summary = _build_summary(
            query_results,
            index_source_sha256=index_source_sha256,
            query_file_sha256=query_file_sha256,
            top_k=top_k,
            candidate_multiplier=candidate_multiplier,
            rrf_k=rrf_k,
            preview_chars=preview_chars,
            report_results_per_query=report_results_per_query,
        )
        return SearchEvaluationResult(query_results=query_results, summary=summary)

    def _evaluate_query(
        self,
        query: SearchEvaluationQuery,
        *,
        top_k: int,
    ) -> QueryEvaluationResult:
        """1質問の検索結果に評価情報を付ける。"""
        search_results = self._retriever.search(query.query, top_k=top_k)
        evaluated_results = tuple(
            _to_evaluated_result(
                search_result,
                expected_relevant=query.expected_relevant,
            )
            for search_result in search_results
        )
        is_auto_evaluated = len(query.expected_relevant) > 0
        if not is_auto_evaluated:
            return QueryEvaluationResult(
                query_id=query.query_id,
                query=query.query,
                query_type=query.query_type,
                is_auto_evaluated=False,
                hit_at_1=None,
                hit_at_3=None,
                hit_at_5=None,
                hit_at_10=None,
                first_relevant_rank=None,
                reciprocal_rank=None,
                results=evaluated_results,
                notes=query.notes,
            )

        first_relevant_rank = _first_relevant_rank(evaluated_results)
        reciprocal_rank = 0.0 if first_relevant_rank is None else 1.0 / first_relevant_rank
        return QueryEvaluationResult(
            query_id=query.query_id,
            query=query.query,
            query_type=query.query_type,
            is_auto_evaluated=True,
            hit_at_1=_hit_at(first_relevant_rank, 1),
            hit_at_3=_hit_at(first_relevant_rank, 3),
            hit_at_5=_hit_at(first_relevant_rank, 5),
            hit_at_10=_hit_at(first_relevant_rank, 10),
            first_relevant_rank=first_relevant_rank,
            reciprocal_rank=reciprocal_rank,
            results=evaluated_results,
            notes=query.notes,
        )


def _to_evaluated_result(
    search_result: SearchResult,
    *,
    expected_relevant: tuple[ExpectedRelevantResult, ...],
) -> EvaluatedSearchResult:
    """既存SearchResultへ一致判定だけを付与する。"""
    return EvaluatedSearchResult(
        rank=search_result.rank,
        chunk_id=search_result.chunk_id,
        relative_path=search_result.relative_path,
        locator=search_result.locator,
        parser_name=search_result.parser_name,
        unit_type=search_result.unit_type,
        score=search_result.score,
        channel_ranks=search_result.channel_ranks,
        text=search_result.text,
        metadata=search_result.metadata,
        is_expected_match=any(
            is_expected_match(search_result, expected) for expected in expected_relevant
        ),
    )


def _first_relevant_rank(results: tuple[EvaluatedSearchResult, ...]) -> int | None:
    """最初に関連結果が現れる順位を返す。"""
    for result in results:
        if result.is_expected_match:
            return result.rank
    return None


def _hit_at(first_relevant_rank: int | None, k: int) -> bool:
    """指定順位以内に関連結果があるか判定する。"""
    return first_relevant_rank is not None and first_relevant_rank <= k


def _build_summary(
    query_results: tuple[QueryEvaluationResult, ...],
    *,
    index_source_sha256: str,
    query_file_sha256: str,
    top_k: int,
    candidate_multiplier: int,
    rrf_k: int,
    preview_chars: int,
    report_results_per_query: int,
) -> SearchEvaluationSummary:
    """質問単位の結果から全体サマリーを構築する。"""
    auto_results = tuple(result for result in query_results if result.is_auto_evaluated)
    auto_count = len(auto_results)
    hit_at_1_count = sum(1 for result in auto_results if result.hit_at_1)
    hit_at_3_count = sum(1 for result in auto_results if result.hit_at_3)
    hit_at_5_count = sum(1 for result in auto_results if result.hit_at_5)
    hit_at_10_count = sum(1 for result in auto_results if result.hit_at_10)
    reciprocal_rank_sum = sum(
        0.0 if result.reciprocal_rank is None else result.reciprocal_rank for result in auto_results
    )
    return SearchEvaluationSummary(
        total_queries=len(query_results),
        auto_evaluated_queries=auto_count,
        manual_review_queries=len(query_results) - auto_count,
        hit_at_1_count=hit_at_1_count,
        hit_at_1_rate=_rate(hit_at_1_count, auto_count),
        hit_at_3_count=hit_at_3_count,
        hit_at_3_rate=_rate(hit_at_3_count, auto_count),
        hit_at_5_count=hit_at_5_count,
        hit_at_5_rate=_rate(hit_at_5_count, auto_count),
        hit_at_10_count=hit_at_10_count,
        hit_at_10_rate=_rate(hit_at_10_count, auto_count),
        mean_reciprocal_rank=0.0 if auto_count == 0 else reciprocal_rank_sum / auto_count,
        queries_with_no_results=sum(1 for result in query_results if len(result.results) == 0),
        by_query_type=_build_query_type_summary(query_results),
        index_source_sha256=index_source_sha256,
        query_file_sha256=query_file_sha256,
        top_k=top_k,
        candidate_multiplier=candidate_multiplier,
        rrf_k=rrf_k,
        preview_chars=preview_chars,
        report_results_per_query=report_results_per_query,
    )


def _build_query_type_summary(
    query_results: tuple[QueryEvaluationResult, ...],
) -> dict[str, JsonValue]:
    """query_typeごとの指標を決定的な順序で集計する。"""
    grouped_results: dict[str, list[QueryEvaluationResult]] = defaultdict(list)
    for result in query_results:
        grouped_results[result.query_type].append(result)

    summary: dict[str, JsonValue] = {}
    for query_type in sorted(grouped_results):
        results = tuple(grouped_results[query_type])
        auto_results = tuple(result for result in results if result.is_auto_evaluated)
        auto_count = len(auto_results)
        hit_at_1_count = sum(1 for result in auto_results if result.hit_at_1)
        hit_at_3_count = sum(1 for result in auto_results if result.hit_at_3)
        hit_at_5_count = sum(1 for result in auto_results if result.hit_at_5)
        hit_at_10_count = sum(1 for result in auto_results if result.hit_at_10)
        reciprocal_rank_sum = sum(
            0.0 if result.reciprocal_rank is None else result.reciprocal_rank
            for result in auto_results
        )
        summary[query_type] = {
            "total_queries": len(results),
            "auto_evaluated_queries": auto_count,
            "manual_review_queries": len(results) - auto_count,
            "hit_at_1_count": hit_at_1_count,
            "hit_at_1_rate": _rate(hit_at_1_count, auto_count),
            "hit_at_3_count": hit_at_3_count,
            "hit_at_3_rate": _rate(hit_at_3_count, auto_count),
            "hit_at_5_count": hit_at_5_count,
            "hit_at_5_rate": _rate(hit_at_5_count, auto_count),
            "hit_at_10_count": hit_at_10_count,
            "hit_at_10_rate": _rate(hit_at_10_count, auto_count),
            "mrr": 0.0 if auto_count == 0 else reciprocal_rank_sum / auto_count,
        }
    return summary


def _rate(count: int, denominator: int) -> float:
    """分母0では0.0に固定し、評価対象外を指標へ混ぜない。"""
    if denominator == 0:
        return 0.0
    return count / denominator
