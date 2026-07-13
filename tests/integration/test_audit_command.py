"""auditコマンドの統合テスト。"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from signate_drive_rag.cli import app

runner = CliRunner()


def write_documents_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    """documents.jsonlテストファイルを書き込む。"""
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def document_record(
    *,
    relative_path: str = "資料.md",
    parser_name: str = "markdown",
    text: str = "本文",
    locator: str | None = "line:1-1",
) -> dict[str, object]:
    """テスト用documents.jsonlレコードを作成する。"""
    return {
        "source": {
            "relative_path": relative_path,
            "name": Path(relative_path).name,
            "suffix": Path(relative_path).suffix,
            "mime_type": None,
            "size_bytes": 10,
            "modified_at": "2026-07-11T12:00:00+00:00",
        },
        "parser_name": parser_name,
        "units": [
            {
                "unit_type": "markdown_section",
                "text": text,
                "locator": locator,
                "metadata": {},
            }
        ],
    }


def test_audit_command_writes_outputs_and_prints_summary(tmp_path: Path) -> None:
    """auditコマンドを実行し、成果物3ファイルとサマリーを生成する。"""
    documents_path = tmp_path / "documents.jsonl"
    output_dir = tmp_path / "audit"
    write_documents_jsonl(
        documents_path,
        [document_record(relative_path="日本語.md", text="あいう", locator=None)],
    )

    result = runner.invoke(
        app,
        [
            "audit",
            "--documents",
            str(documents_path),
            "--output-dir",
            str(output_dir),
            "--samples-per-parser",
            "1",
            "--preview-chars",
            "2",
            "--large-unit-chars",
            "2",
        ],
    )

    assert result.exit_code == 0
    assert "文書数: 1" in result.stdout
    assert "合計:" in result.stdout
    for file_name in ("summary.json", "issues.jsonl", "samples.jsonl"):
        assert (output_dir / file_name).exists()
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    sample = json.loads((output_dir / "samples.jsonl").read_text(encoding="utf-8"))
    assert summary["total_issues"] >= 1
    assert sample["sample_units"][0]["text_preview"] == "あい..."


def test_audit_command_succeeds_with_issues(tmp_path: Path) -> None:
    """issueが存在しても監査成果物を生成できれば正常終了する。"""
    documents_path = tmp_path / "documents.jsonl"
    output_dir = tmp_path / "audit"
    write_documents_jsonl(documents_path, [document_record(locator=None)])

    result = runner.invoke(
        app, ["audit", "--documents", str(documents_path), "--output-dir", str(output_dir)]
    )

    assert result.exit_code == 0
    assert (
        json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))["total_issues"] == 1
    )


def test_audit_command_succeeds_with_empty_documents_jsonl(tmp_path: Path) -> None:
    """空のdocuments.jsonlでも正常終了する。"""
    documents_path = tmp_path / "documents.jsonl"
    documents_path.write_text("", encoding="utf-8")
    output_dir = tmp_path / "audit"

    result = runner.invoke(
        app, ["audit", "--documents", str(documents_path), "--output-dir", str(output_dir)]
    )

    assert result.exit_code == 0
    assert "文書数: 0" in result.stdout
    assert (output_dir / "issues.jsonl").read_text(encoding="utf-8") == ""


def test_audit_command_fails_for_missing_documents(tmp_path: Path) -> None:
    """存在しないdocuments.jsonlではエラー終了する。"""
    output_dir = tmp_path / "audit"

    result = runner.invoke(
        app,
        ["audit", "--documents", str(tmp_path / "missing.jsonl"), "--output-dir", str(output_dir)],
    )

    assert result.exit_code != 0
    assert not output_dir.exists()


@pytest.mark.parametrize(
    ("option_name", "value"),
    [
        ("--samples-per-parser", "-1"),
        ("--preview-chars", "-1"),
        ("--large-unit-chars", "-1"),
    ],
)
def test_audit_command_fails_for_negative_numeric_options(
    tmp_path: Path,
    option_name: str,
    value: str,
) -> None:
    """負の数値オプションではエラー終了する。"""
    documents_path = tmp_path / "documents.jsonl"
    write_documents_jsonl(documents_path, [])

    result = runner.invoke(app, ["audit", "--documents", str(documents_path), option_name, value])

    assert result.exit_code != 0
