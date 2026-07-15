"""searchコマンドの統合テスト。"""

import json
from pathlib import Path

from typer.testing import CliRunner

from signate_drive_rag.cli import app

runner = CliRunner()


def build_index(tmp_path: Path) -> Path:
    """CLI経由で検索用インデックスを作成する。"""
    chunks_path = tmp_path / "chunks.jsonl"
    records = [
        {
            "chunk_id": "contract",
            "relative_path": "資料/契約一覧.csv",
            "parser_name": "delimited_text",
            "unit_type": "table_rows",
            "text": "列: 顧客名 | 契約金額\n行2: A | 5,000,000",
            "locator": "row:2-2",
            "source_unit_indices": [0, 1],
            "chunk_index": 0,
            "metadata": {"headers": ["顧客名", "契約金額"]},
        },
        {
            "chunk_id": "analysis",
            "relative_path": "資料/分析結果.md",
            "parser_name": "markdown",
            "unit_type": "markdown_section",
            "text": "TASK-001 customer_id 分析結果",
            "locator": "heading:1",
            "source_unit_indices": [0],
            "chunk_index": 0,
            "metadata": {"heading": "分析結果"},
        },
    ]
    chunks_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    index_dir = tmp_path / "bm25"
    result = runner.invoke(
        app, ["index", "--chunks", str(chunks_path), "--output-dir", str(index_dir)]
    )
    assert result.exit_code == 0
    return index_dir


def test_search_command_prints_results_and_writes_json_output(tmp_path: Path) -> None:
    """searchコマンドで検索結果を表示し、JSON保存できる。"""
    index_dir = build_index(tmp_path)
    output_path = tmp_path / "search.json"

    result = runner.invoke(
        app,
        [
            "search",
            "--index-dir",
            str(index_dir),
            "--query",
            "契約金額",
            "--top-k",
            "1",
            "--candidate-multiplier",
            "2",
            "--rrf-k",
            "30",
            "--preview-chars",
            "20",
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    assert "検索語: 契約金額" in result.stdout
    assert "取得件数: 1" in result.stdout
    assert "file: 資料/契約一覧.csv" in result.stdout
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["results"][0]["chunk_id"] == "contract"


def test_search_command_can_search_ids_numbers_and_context_file_name(tmp_path: Path) -> None:
    """ID、数値、ファイル名由来のcontextで検索できる。"""
    index_dir = build_index(tmp_path)

    assert (
        "資料/分析結果.md"
        in runner.invoke(
            app, ["search", "--index-dir", str(index_dir), "--query", "customer_id", "--top-k", "1"]
        ).stdout
    )
    assert (
        "資料/契約一覧.csv"
        in runner.invoke(
            app, ["search", "--index-dir", str(index_dir), "--query", "5000000", "--top-k", "1"]
        ).stdout
    )
    assert (
        "資料/分析結果.md"
        in runner.invoke(
            app, ["search", "--index-dir", str(index_dir), "--query", "分析結果.md", "--top-k", "1"]
        ).stdout
    )


def test_search_command_rejects_empty_query_invalid_options_and_missing_index(
    tmp_path: Path,
) -> None:
    """空質問、不正オプション、存在しないインデックスではエラーになる。"""
    index_dir = build_index(tmp_path)

    assert (
        runner.invoke(app, ["search", "--index-dir", str(index_dir), "--query", " "]).exit_code == 2
    )
    assert (
        runner.invoke(
            app, ["search", "--index-dir", str(index_dir), "--query", "契約", "--top-k", "0"]
        ).exit_code
        == 2
    )
    assert (
        runner.invoke(
            app, ["search", "--index-dir", str(tmp_path / "missing"), "--query", "契約"]
        ).exit_code
        == 2
    )
