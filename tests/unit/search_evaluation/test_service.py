"""検索評価サービスのテスト。"""

from signate_drive_rag.retrieval.models import SearchResult
from signate_drive_rag.search_evaluation.models import (
    ExpectedRelevantResult,
    SearchEvaluationQuery,
)
from signate_drive_rag.search_evaluation.service import SearchEvaluationService, is_expected_match


class FakeRetriever:
    """テスト用Retriever。"""

    def __init__(self, results_by_query: dict[str, tuple[SearchResult, ...]]) -> None:
        self.results_by_query = results_by_query
        self.calls: list[str] = []

    def search(self, query: str, top_k: int) -> tuple[SearchResult, ...]:
        """事前に用意した検索結果を返す。"""
        self.calls.append(query)
        return self.results_by_query.get(query, ())[:top_k]


def result(
    rank: int,
    relative_path: str,
    locator: str | None = None,
    chunk_id: str | None = None,
) -> SearchResult:
    """テスト用SearchResultを作成する。"""
    return SearchResult(
        rank=rank,
        chunk_id=chunk_id or f"chunk-{rank}",
        relative_path=relative_path,
        locator=locator,
        parser_name="markdown",
        unit_type="markdown_section",
        score=1.0 / rank,
        channel_ranks={"content_word": rank},
        text=f"text {rank}",
        metadata={},
    )


def query(
    query_id: str,
    text: str,
    expected: tuple[ExpectedRelevantResult, ...] = (),
    query_type: str = "exact",
) -> SearchEvaluationQuery:
    """テスト用SearchEvaluationQueryを作成する。"""
    return SearchEvaluationQuery(
        query_id=query_id,
        query=text,
        query_type=query_type,
        expected_relevant=expected,
        notes="",
    )


def test_is_expected_match_uses_exact_path_and_locator_rules() -> None:
    """relative_pathとlocatorの完全一致規則を確認する。"""
    search_result = result(1, "資料/契約.md", "line:1-2")

    assert is_expected_match(search_result, ExpectedRelevantResult("資料/契約.md", None))
    assert is_expected_match(search_result, ExpectedRelevantResult("資料/契約.md", "line:1-2"))
    assert not is_expected_match(search_result, ExpectedRelevantResult("契約.md", None))
    assert not is_expected_match(search_result, ExpectedRelevantResult("資料", None))
    assert not is_expected_match(search_result, ExpectedRelevantResult("資料/契約.md", "line:1"))


def test_search_evaluation_service_computes_hit_at_k_and_mrr() -> None:
    """Hit@kとMRRを自動評価対象だけで計算する。"""
    expected = (ExpectedRelevantResult("資料/relevant.md", "line:2"),)
    retriever = FakeRetriever(
        {
            "q1": (result(1, "資料/relevant.md", "line:2"),),
            "q2": (
                result(1, "資料/other.md"),
                result(2, "資料/relevant.md", "line:2"),
            ),
            "q3": (
                *(result(rank, f"資料/{rank}.md") for rank in range(1, 6)),
                result(6, "資料/relevant.md", "line:2"),
            ),
            "q4": (result(1, "資料/none.md"),),
            "manual": (result(1, "資料/relevant.md", "line:2"),),
        }
    )
    queries = (
        query("q1", "q1", expected),
        query("q2", "q2", expected),
        query("q3", "q3", expected),
        query("q4", "q4", expected),
        query("manual", "manual"),
    )

    evaluation = SearchEvaluationService(retriever).evaluate(
        queries,
        top_k=10,
        index_source_sha256="index",
        query_file_sha256="queries",
        candidate_multiplier=5,
        rrf_k=60,
        preview_chars=100,
        report_results_per_query=3,
    )

    results = evaluation.query_results
    assert results[0].hit_at_1 is True
    assert results[0].reciprocal_rank == 1.0
    assert results[1].hit_at_1 is False
    assert results[1].hit_at_3 is True
    assert results[1].reciprocal_rank == 0.5
    assert results[2].hit_at_5 is False
    assert results[2].hit_at_10 is True
    assert results[2].reciprocal_rank == 1 / 6
    assert results[3].hit_at_10 is False
    assert results[3].reciprocal_rank == 0.0
    assert results[4].hit_at_1 is None
    assert results[4].reciprocal_rank is None
    assert evaluation.summary.auto_evaluated_queries == 4
    assert evaluation.summary.manual_review_queries == 1
    assert evaluation.summary.hit_at_1_count == 1
    assert evaluation.summary.hit_at_3_count == 2
    assert evaluation.summary.hit_at_5_count == 2
    assert evaluation.summary.hit_at_10_count == 3
    assert evaluation.summary.mean_reciprocal_rank == (1.0 + 0.5 + 1 / 6) / 4
    assert retriever.calls == ["q1", "q2", "q3", "q4", "manual"]


def test_search_evaluation_service_handles_multiple_expected_and_empty_auto_denominator() -> None:
    """複数期待結果のうち1件一致でHitし、自動評価0件では率を0にする。"""
    retriever = FakeRetriever({"q": (result(1, "資料/b.md"),)})
    expected = (
        ExpectedRelevantResult("資料/a.md", None),
        ExpectedRelevantResult("資料/b.md", None),
    )

    evaluation = SearchEvaluationService(retriever).evaluate(
        (query("q", "q", expected),),
        top_k=1,
        index_source_sha256="index",
        query_file_sha256="queries",
        candidate_multiplier=5,
        rrf_k=60,
        preview_chars=100,
        report_results_per_query=1,
    )
    assert evaluation.query_results[0].hit_at_1 is True

    manual_only = SearchEvaluationService(FakeRetriever({"m": ()})).evaluate(
        (query("m", "m"),),
        top_k=1,
        index_source_sha256="index",
        query_file_sha256="queries",
        candidate_multiplier=5,
        rrf_k=60,
        preview_chars=100,
        report_results_per_query=1,
    )
    assert manual_only.summary.hit_at_1_rate == 0.0
    assert manual_only.summary.mean_reciprocal_rank == 0.0


def test_search_evaluation_service_builds_query_type_summary_and_preserves_order() -> None:
    """query_type別集計をキー昇順にし、入力質問順を維持する。"""
    expected = (ExpectedRelevantResult("資料/a.md", None),)
    evaluation = SearchEvaluationService(
        FakeRetriever({"b": (), "a": (result(1, "資料/a.md"),)})
    ).evaluate(
        (
            query("b", "b", expected, "natural"),
            query("a", "a", expected, "exact"),
        ),
        top_k=1,
        index_source_sha256="index",
        query_file_sha256="queries",
        candidate_multiplier=5,
        rrf_k=60,
        preview_chars=100,
        report_results_per_query=1,
    )

    assert [result.query_id for result in evaluation.query_results] == ["b", "a"]
    assert list(evaluation.summary.by_query_type) == ["exact", "natural"]
    assert evaluation.summary.queries_with_no_results == 1
    assert evaluation == SearchEvaluationService(
        FakeRetriever({"b": (), "a": (result(1, "資料/a.md"),)})
    ).evaluate(
        (
            query("b", "b", expected, "natural"),
            query("a", "a", expected, "exact"),
        ),
        top_k=1,
        index_source_sha256="index",
        query_file_sha256="queries",
        candidate_multiplier=5,
        rrf_k=60,
        preview_chars=100,
        report_results_per_query=1,
    )
