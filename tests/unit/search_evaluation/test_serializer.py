"""検索評価結果シリアライザのテスト。"""

import csv
import json
from pathlib import Path

from signate_drive_rag.search_evaluation import save_search_evaluation_result
from signate_drive_rag.search_evaluation.models import (
    EvaluatedSearchResult,
    QueryEvaluationResult,
    SearchEvaluationResult,
    SearchEvaluationSummary,
)


def evaluation_result(text: str = '本文, "引用"\n改行あり') -> SearchEvaluationResult:
    """テスト用SearchEvaluationResultを作成する。"""
    query_results = (
        QueryEvaluationResult(
            query_id="q1",
            query="契約金額",
            query_type="exact",
            is_auto_evaluated=True,
            hit_at_1=True,
            hit_at_3=True,
            hit_at_5=True,
            hit_at_10=True,
            first_relevant_rank=1,
            reciprocal_rank=1.0,
            results=(
                EvaluatedSearchResult(
                    rank=1,
                    chunk_id="chunk-1",
                    relative_path="資料/契約.md",
                    locator="line:1-2",
                    parser_name="markdown",
                    unit_type="markdown_section",
                    score=0.5,
                    channel_ranks={"content_word": 1},
                    text=text,
                    metadata={"heading": "契約"},
                    is_expected_match=True,
                ),
            ),
            notes="",
        ),
        QueryEvaluationResult(
            query_id="q2",
            query="目視確認",
            query_type="natural",
            is_auto_evaluated=False,
            hit_at_1=None,
            hit_at_3=None,
            hit_at_5=None,
            hit_at_10=None,
            first_relevant_rank=None,
            reciprocal_rank=None,
            results=(),
            notes="manual",
        ),
    )
    summary = SearchEvaluationSummary(
        total_queries=2,
        auto_evaluated_queries=1,
        manual_review_queries=1,
        hit_at_1_count=1,
        hit_at_1_rate=1.0,
        hit_at_3_count=1,
        hit_at_3_rate=1.0,
        hit_at_5_count=1,
        hit_at_5_rate=1.0,
        hit_at_10_count=1,
        hit_at_10_rate=1.0,
        mean_reciprocal_rank=1.0,
        queries_with_no_results=1,
        by_query_type={
            "exact": {
                "total_queries": 1,
                "auto_evaluated_queries": 1,
                "manual_review_queries": 0,
                "hit_at_1_count": 1,
                "hit_at_1_rate": 1.0,
                "hit_at_3_count": 1,
                "hit_at_3_rate": 1.0,
                "hit_at_5_count": 1,
                "hit_at_5_rate": 1.0,
                "hit_at_10_count": 1,
                "hit_at_10_rate": 1.0,
                "mrr": 1.0,
            },
            "natural": {
                "total_queries": 1,
                "auto_evaluated_queries": 0,
                "manual_review_queries": 1,
                "hit_at_1_count": 0,
                "hit_at_1_rate": 0.0,
                "hit_at_3_count": 0,
                "hit_at_3_rate": 0.0,
                "hit_at_5_count": 0,
                "hit_at_5_rate": 0.0,
                "hit_at_10_count": 0,
                "hit_at_10_rate": 0.0,
                "mrr": 0.0,
            },
        },
        index_source_sha256="index",
        query_file_sha256="queries",
        top_k=10,
        candidate_multiplier=5,
        rrf_k=60,
        preview_chars=8,
        report_results_per_query=1,
    )
    return SearchEvaluationResult(query_results=query_results, summary=summary)


def test_save_search_evaluation_result_writes_valid_json_jsonl_csv_and_report(
    tmp_path: Path,
) -> None:
    """検索評価結果4ファイルを有効な形式で保存できる。"""
    output_dir = tmp_path / "evaluation"

    save_search_evaluation_result(evaluation_result(), output_dir)

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["total_queries"] == 2
    assert summary["parameters"]["top_k"] == 10

    query_records = [
        json.loads(line)
        for line in (output_dir / "query_results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [record["query_id"] for record in query_records] == ["q1", "q2"]
    assert query_records[0]["results"][0]["text"].startswith("本文")

    raw_csv = (output_dir / "review.csv").read_bytes()
    assert raw_csv.startswith(b"\xef\xbb\xbf")
    with (output_dir / "review.csv").open("r", encoding="utf-8-sig", newline="") as input_file:
        rows = list(csv.DictReader(input_file))
    assert rows[0]["query"] == "契約金額"
    assert rows[0]["manual_relevance"] == ""
    assert rows[0]["reviewer_notes"] == ""
    assert rows[0]["text_preview"].endswith("...")

    report = (output_dir / "report.md").read_text(encoding="utf-8")
    assert "# BM25検索評価レポート" in report
    assert "| Hit@1 | 100.0% |" in report
    assert "## q1: 契約金額" in report
    assert "検索結果はありません。" in report
    assert list(output_dir.glob("*.tmp")) == []


def test_save_search_evaluation_result_handles_empty_query_set(tmp_path: Path) -> None:
    """空質問セットでも4ファイルを生成できる。"""
    summary = SearchEvaluationSummary(
        total_queries=0,
        auto_evaluated_queries=0,
        manual_review_queries=0,
        hit_at_1_count=0,
        hit_at_1_rate=0.0,
        hit_at_3_count=0,
        hit_at_3_rate=0.0,
        hit_at_5_count=0,
        hit_at_5_rate=0.0,
        hit_at_10_count=0,
        hit_at_10_rate=0.0,
        mean_reciprocal_rank=0.0,
        queries_with_no_results=0,
        by_query_type={},
        index_source_sha256="index",
        query_file_sha256="queries",
        top_k=10,
        candidate_multiplier=5,
        rrf_k=60,
        preview_chars=300,
        report_results_per_query=5,
    )
    result = SearchEvaluationResult(query_results=(), summary=summary)
    output_dir = tmp_path / "evaluation"

    save_search_evaluation_result(result, output_dir)

    for file_name in ("summary.json", "query_results.jsonl", "review.csv", "report.md"):
        assert (output_dir / file_name).exists()
    assert (output_dir / "query_results.jsonl").read_text(encoding="utf-8") == ""
