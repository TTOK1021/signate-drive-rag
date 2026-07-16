"""検索評価結果をJSON/JSONL/CSV/Markdownへ保存する処理。"""

import csv
import json
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from signate_drive_rag.search_evaluation.models import (
    EvaluatedSearchResult,
    QueryEvaluationResult,
    SearchEvaluationResult,
    SearchEvaluationSummary,
)

SUMMARY_FILE_NAME = "summary.json"
QUERY_RESULTS_FILE_NAME = "query_results.jsonl"
REVIEW_FILE_NAME = "review.csv"
REPORT_FILE_NAME = "report.md"


def save_search_evaluation_result(
    result: SearchEvaluationResult,
    output_dir: Path,
) -> None:
    """検索評価結果を指定ディレクトリへ保存する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(output_dir / SUMMARY_FILE_NAME, _summary_to_record(result.summary))
    _write_jsonl_atomic(
        output_dir / QUERY_RESULTS_FILE_NAME,
        (_query_result_to_record(query_result) for query_result in result.query_results),
    )
    _write_review_csv_atomic(output_dir / REVIEW_FILE_NAME, result)
    _write_text_atomic(output_dir / REPORT_FILE_NAME, _build_report_markdown(result))


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


def _write_review_csv_atomic(path: Path, result: SearchEvaluationResult) -> None:
    """目視確認用CSVを一時ファイルへ書き、成功後に置き換える。"""
    temporary_path = path.with_name(f"{path.name}.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8-sig", newline="") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=_review_csv_fieldnames())
            writer.writeheader()
            for row in _review_rows(result):
                writer.writerow(row)
        temporary_path.replace(path)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def _write_text_atomic(path: Path, text: str) -> None:
    """Markdownを一時ファイルへ書き、成功後に置き換える。"""
    temporary_path = path.with_name(f"{path.name}.tmp")
    try:
        temporary_path.write_text(text, encoding="utf-8", newline="\n")
        temporary_path.replace(path)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def _summary_to_record(summary: SearchEvaluationSummary) -> dict[str, Any]:
    """SearchEvaluationSummaryをJSON互換の辞書へ変換する。"""
    return {
        "total_queries": summary.total_queries,
        "auto_evaluated_queries": summary.auto_evaluated_queries,
        "manual_review_queries": summary.manual_review_queries,
        "hit_at_1_count": summary.hit_at_1_count,
        "hit_at_1_rate": summary.hit_at_1_rate,
        "hit_at_3_count": summary.hit_at_3_count,
        "hit_at_3_rate": summary.hit_at_3_rate,
        "hit_at_5_count": summary.hit_at_5_count,
        "hit_at_5_rate": summary.hit_at_5_rate,
        "hit_at_10_count": summary.hit_at_10_count,
        "hit_at_10_rate": summary.hit_at_10_rate,
        "mean_reciprocal_rank": summary.mean_reciprocal_rank,
        "queries_with_no_results": summary.queries_with_no_results,
        "index_source_sha256": summary.index_source_sha256,
        "query_file_sha256": summary.query_file_sha256,
        "parameters": {
            "top_k": summary.top_k,
            "candidate_multiplier": summary.candidate_multiplier,
            "rrf_k": summary.rrf_k,
            "preview_chars": summary.preview_chars,
            "report_results_per_query": summary.report_results_per_query,
        },
        "by_query_type": dict(sorted(summary.by_query_type.items())),
    }


def _query_result_to_record(query_result: QueryEvaluationResult) -> dict[str, Any]:
    """QueryEvaluationResultをJSON互換の辞書へ変換する。"""
    return {
        "query_id": query_result.query_id,
        "query": query_result.query,
        "query_type": query_result.query_type,
        "is_auto_evaluated": query_result.is_auto_evaluated,
        "hit_at_1": query_result.hit_at_1,
        "hit_at_3": query_result.hit_at_3,
        "hit_at_5": query_result.hit_at_5,
        "hit_at_10": query_result.hit_at_10,
        "first_relevant_rank": query_result.first_relevant_rank,
        "reciprocal_rank": query_result.reciprocal_rank,
        "notes": query_result.notes,
        "results": [_evaluated_result_to_record(result) for result in query_result.results],
    }


def _evaluated_result_to_record(result: EvaluatedSearchResult) -> dict[str, Any]:
    """EvaluatedSearchResultをJSON互換の辞書へ変換する。"""
    return {
        "rank": result.rank,
        "chunk_id": result.chunk_id,
        "relative_path": result.relative_path,
        "locator": result.locator,
        "parser_name": result.parser_name,
        "unit_type": result.unit_type,
        "score": result.score,
        "channel_ranks": dict(sorted(result.channel_ranks.items())),
        "text": result.text,
        "metadata": result.metadata,
        "is_expected_match": result.is_expected_match,
    }


def _review_csv_fieldnames() -> list[str]:
    """review.csvの列順を返す。"""
    return [
        "query_id",
        "query",
        "query_type",
        "auto_evaluated",
        "rank",
        "score",
        "relative_path",
        "locator",
        "parser_name",
        "unit_type",
        "channel_ranks",
        "expected_match",
        "text_preview",
        "manual_relevance",
        "reviewer_notes",
    ]


def _review_rows(result: SearchEvaluationResult) -> Iterable[dict[str, str]]:
    """検索結果を目視確認用CSV行へ変換する。"""
    preview_chars = result.summary.preview_chars
    for query_result in result.query_results:
        for search_result in query_result.results:
            yield {
                "query_id": query_result.query_id,
                "query": query_result.query,
                "query_type": query_result.query_type,
                "auto_evaluated": str(query_result.is_auto_evaluated).lower(),
                "rank": str(search_result.rank),
                "score": f"{search_result.score:.12g}",
                "relative_path": search_result.relative_path,
                "locator": "" if search_result.locator is None else search_result.locator,
                "parser_name": search_result.parser_name,
                "unit_type": search_result.unit_type,
                "channel_ranks": json.dumps(
                    search_result.channel_ranks,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "expected_match": str(search_result.is_expected_match).lower(),
                "text_preview": _preview_text(search_result.text, preview_chars),
                "manual_relevance": "",
                "reviewer_notes": "",
            }


def _build_report_markdown(result: SearchEvaluationResult) -> str:
    """人が確認しやすいMarkdownレポートを作成する。"""
    summary = result.summary
    lines = [
        "# BM25検索評価レポート",
        "",
        "## 全体結果",
        "",
        "| 指標 | 結果 |",
        "|---|---:|",
        f"| 質問数 | {summary.total_queries} |",
        f"| 自動評価対象 | {summary.auto_evaluated_queries} |",
        f"| 目視確認対象 | {summary.manual_review_queries} |",
        f"| Hit@1 | {_format_percent(summary.hit_at_1_rate)} |",
        f"| Hit@3 | {_format_percent(summary.hit_at_3_rate)} |",
        f"| Hit@5 | {_format_percent(summary.hit_at_5_rate)} |",
        f"| Hit@10 | {_format_percent(summary.hit_at_10_rate)} |",
        f"| MRR | {summary.mean_reciprocal_rank:.4f} |",
        f"| 検索結果0件 | {summary.queries_with_no_results} |",
        "",
        "## query_type別結果",
        "",
        "| query_type | 質問数 | 自動評価 | 目視確認 | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for query_type, value in summary.by_query_type.items():
        if not isinstance(value, dict):
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    str(query_type),
                    str(_json_int(value, "total_queries")),
                    str(_json_int(value, "auto_evaluated_queries")),
                    str(_json_int(value, "manual_review_queries")),
                    _format_percent(_json_float(value, "hit_at_1_rate")),
                    _format_percent(_json_float(value, "hit_at_3_rate")),
                    _format_percent(_json_float(value, "hit_at_5_rate")),
                    _format_percent(_json_float(value, "hit_at_10_rate")),
                    f"{_json_float(value, 'mrr'):.4f}",
                ]
            )
            + " |"
        )
    lines.append("")

    for query_result in result.query_results:
        lines.extend(_query_report_lines(query_result, summary))
    return "\n".join(lines) + "\n"


def _query_report_lines(
    query_result: QueryEvaluationResult,
    summary: SearchEvaluationSummary,
) -> list[str]:
    """1質問分のMarkdownレポートを作る。"""
    lines = [
        f"## {query_result.query_id}: {query_result.query}",
        "",
        f"- 種別: {query_result.query_type}",
        f"- 自動評価: {'対象' if query_result.is_auto_evaluated else '対象外'}",
        f"- Hit@1: {_format_optional_bool(query_result.hit_at_1)}",
        f"- Hit@3: {_format_optional_bool(query_result.hit_at_3)}",
        f"- Hit@5: {_format_optional_bool(query_result.hit_at_5)}",
        f"- Hit@10: {_format_optional_bool(query_result.hit_at_10)}",
        f"- 最初の関連順位: {_format_optional_int(query_result.first_relevant_rank)}",
        f"- Reciprocal Rank: {_format_optional_float(query_result.reciprocal_rank)}",
        "",
        "### 上位結果",
        "",
    ]
    if not query_result.results:
        lines.extend(["検索結果はありません。", ""])
        return lines

    for search_result in query_result.results[: summary.report_results_per_query]:
        lines.extend(
            [
                f"{search_result.rank}. `{search_result.relative_path}`",
                f"   - Locator: `{search_result.locator}`",
                f"   - Score: {search_result.score:.6f}",
                f"   - Expected match: {_format_bool(search_result.is_expected_match)}",
                f"   - Preview: {_preview_text(search_result.text, summary.preview_chars)}",
                "",
            ]
        )
    return lines


def _preview_text(text: str, preview_chars: int) -> str:
    """本文全体を成果物へ広げすぎないためのプレビューを作る。"""
    if preview_chars == 0:
        return ""
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    normalized = " ".join(part.strip() for part in normalized.split("\n"))
    if len(normalized) <= preview_chars:
        return normalized
    return normalized[:preview_chars] + "..."


def _format_percent(value: float) -> str:
    """割合をMarkdown表示用に整える。"""
    return f"{value * 100:.1f}%"


def _format_bool(value: bool) -> str:
    """真偽値をレポート表示用に整える。"""
    return "Yes" if value else "No"


def _format_optional_bool(value: bool | None) -> str:
    """評価対象外の真偽値をレポート表示用に整える。"""
    if value is None:
        return "-"
    return _format_bool(value)


def _format_optional_int(value: int | None) -> str:
    """Noneをレポート表示用に整える。"""
    if value is None:
        return "-"
    return str(value)


def _format_optional_float(value: float | None) -> str:
    """Noneをレポート表示用に整える。"""
    if value is None:
        return "-"
    return f"{value:.4f}"


def _json_int(mapping: dict[str, Any], key: str) -> int:
    """レポート生成時にJSON互換値から整数を取り出す。"""
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key}は整数である必要があります。")
    return value


def _json_float(mapping: dict[str, Any], key: str) -> float:
    """レポート生成時にJSON互換値から数値を取り出す。"""
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{key}は数値である必要があります。")
    return float(value)
