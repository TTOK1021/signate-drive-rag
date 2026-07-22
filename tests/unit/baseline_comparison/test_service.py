"""BaselineComparisonServiceのテスト。"""

import json
from pathlib import Path

import pytest

from signate_drive_rag.baseline_comparison import (
    BaselineComparisonService,
    save_baseline_comparison_result,
)


def test_baseline_comparison_reports_top_path_and_format_differences(tmp_path: Path) -> None:
    """Top1/Top5差分と新結果に含まれる形式・OCR件数を集計する。"""
    baseline_dir = tmp_path / "baseline"
    current_dir = tmp_path / "current"
    _write_query_results(
        baseline_dir,
        [
            _query_record("q1", ["old/a.md", "docs/manual.pdf"]),
            _query_record("q2", []),
        ],
    )
    _write_query_results(
        current_dir,
        [
            _query_record(
                "q1",
                ["docs/new.docx", "docs/manual.pdf", "tables/book.xlsx", "画像/page.png"],
                unit_types=["text", "text", "xlsx_table_rows", "image_ocr_text"],
            ),
            _query_record("q2", []),
        ],
    )

    result = BaselineComparisonService().compare(
        baseline_dir=baseline_dir,
        current_dir=current_dir,
    )

    first = result.query_results[0]
    assert first.query_id == "q1"
    assert first.top1_changed is True
    assert first.top5_overlap_count == 1
    assert first.newly_retrieved_paths == (
        "docs/new.docx",
        "tables/book.xlsx",
        "画像/page.png",
    )
    assert result.summary.compared_queries == 2
    assert result.summary.top1_changed_queries == 1
    assert result.summary.docx_new_top5_queries == 1
    assert result.summary.xlsx_new_top5_queries == 1
    assert result.summary.ocr_new_top5_queries == 1
    assert result.summary.no_result_delta == 0


def test_baseline_comparison_serializer_writes_stable_outputs(tmp_path: Path) -> None:
    """比較結果をJSON/JSONL/Markdownとして保存し、一時ファイルを残さない。"""
    baseline_dir = tmp_path / "baseline"
    current_dir = tmp_path / "current"
    _write_query_results(baseline_dir, [_query_record("q1", ["old/a.md"])])
    _write_query_results(current_dir, [_query_record("q1", ["new/a.md"])])
    result = BaselineComparisonService().compare(
        baseline_dir=baseline_dir,
        current_dir=current_dir,
    )
    output_dir = tmp_path / "comparison"

    save_baseline_comparison_result(result, output_dir)
    first_write = (output_dir / "query_diff.jsonl").read_text(encoding="utf-8")
    save_baseline_comparison_result(result, output_dir)

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    query_diff = [
        json.loads(line)
        for line in (output_dir / "query_diff.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert summary["compared_queries"] == 1
    assert query_diff[0]["new_top_paths"] == ["new/a.md"]
    assert (output_dir / "query_diff.jsonl").read_text(encoding="utf-8") == first_write
    assert (output_dir / "report.md").exists()
    assert not list(output_dir.glob("*.tmp"))


def test_baseline_comparison_fails_when_query_results_are_missing(tmp_path: Path) -> None:
    """比較元または比較先の評価JSONLがない場合は明確に失敗する。"""
    with pytest.raises(ValueError):
        BaselineComparisonService().compare(
            baseline_dir=tmp_path / "missing",
            current_dir=tmp_path / "current",
        )


def _write_query_results(output_dir: Path, records: list[dict[str, object]]) -> None:
    output_dir.mkdir(parents=True)
    with (output_dir / "query_results.jsonl").open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _query_record(
    query_id: str,
    paths: list[str],
    *,
    unit_types: list[str] | None = None,
) -> dict[str, object]:
    resolved_unit_types = unit_types if unit_types is not None else ["text"] * len(paths)
    return {
        "query_id": query_id,
        "query": f"{query_id}の質問",
        "results": [
            {
                "rank": index + 1,
                "relative_path": path,
                "unit_type": resolved_unit_types[index],
                "metadata": {},
            }
            for index, path in enumerate(paths)
        ],
    }
