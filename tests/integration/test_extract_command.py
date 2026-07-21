"""extractコマンドの統合テスト。"""

import json
from pathlib import Path

from typer.testing import CliRunner

from signate_drive_rag.cli import app

runner = CliRunner()


def test_extract_command_writes_output_files_and_prints_counts(tmp_path: Path) -> None:
    """extractコマンドで成果物4ファイルを生成し、件数を表示する。"""
    root = tmp_path / "root"
    root.mkdir()
    (root / "ok.txt").write_text("hello", encoding="utf-8")
    (root / "broken.json").write_text("{invalid", encoding="utf-8")
    (root / "report.png").write_text("png", encoding="utf-8")
    output_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        ["extract", "--root", str(root), "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 0
    assert "探索ファイル数: 3" in result.stdout
    assert "抽出成功: 1" in result.stdout
    assert "抽出失敗: 1" in result.stdout
    assert "未対応: 1" in result.stdout
    for file_name in ("documents.jsonl", "failures.jsonl", "unsupported.jsonl", "summary.json"):
        assert (output_dir / file_name).exists()
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["supported_files"] == 2


def test_extract_command_handles_empty_directory(tmp_path: Path) -> None:
    """空ディレクトリでも正常実行して空の成果物を生成する。"""
    root = tmp_path / "root"
    root.mkdir()
    output_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        ["extract", "--root", str(root), "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 0
    assert "探索ファイル数: 0" in result.stdout
    assert (output_dir / "documents.jsonl").read_text(encoding="utf-8") == ""


def test_extract_command_fails_for_missing_root(tmp_path: Path) -> None:
    """存在しないルートでは既存の探索処理方針どおりエラーになる。"""
    output_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        ["extract", "--root", str(tmp_path / "missing"), "--output-dir", str(output_dir)],
    )

    assert result.exit_code != 0
    assert not output_dir.exists()


def test_extract_command_extracts_csv_and_tsv_files(tmp_path: Path) -> None:
    """extractコマンドでCSV・TSVをsuccessへ分類し、JSONLへ保存する。"""
    root = tmp_path / "root"
    root.mkdir()
    (root / "顧客.csv").write_text("顧客名,状態\n山田,承認済み", encoding="utf-8")
    (root / "売上.tsv").write_text("商品\t金額\nりんご\t100", encoding="utf-8")
    output_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        ["extract", "--root", str(root), "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 0
    assert "抽出成功: 2" in result.stdout
    assert "未対応: 0" in result.stdout
    documents = [
        json.loads(line)
        for line in (output_dir / "documents.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["by_parser"] == {"delimited_text": 2}
    assert summary["by_suffix"] == {".csv": 1, ".tsv": 1}
    documents_by_suffix = {document["source"]["suffix"]: document for document in documents}
    assert documents_by_suffix[".csv"]["parser_name"] == "delimited_text"
    assert documents_by_suffix[".csv"]["units"][1]["text"] == "顧客名=山田 | 状態=承認済み"
    assert documents_by_suffix[".tsv"]["units"][1]["text"] == "商品=りんご | 金額=100"
    assert str(tmp_path) not in (output_dir / "documents.jsonl").read_text(encoding="utf-8")
