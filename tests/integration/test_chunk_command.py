"""chunkコマンドの統合テスト。"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from signate_drive_rag.cli import app

runner = CliRunner()


def write_documents_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    """documents.jsonlを書き込む。"""
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def record(text: str = "本文", relative_path: str = "資料.txt") -> dict[str, object]:
    """documents.jsonlのテストレコードを作成する。"""
    return {
        "source": {
            "relative_path": relative_path,
            "name": Path(relative_path).name,
            "suffix": Path(relative_path).suffix,
            "mime_type": None,
            "size_bytes": len(text),
            "modified_at": "2026-07-11T12:00:00+00:00",
        },
        "parser_name": "plain_text",
        "units": [
            {
                "unit_type": "text",
                "text": text,
                "locator": None,
                "metadata": {},
            }
        ],
    }


def test_chunk_command_writes_outputs_and_prints_summary(tmp_path: Path) -> None:
    """chunkコマンドを実行し、成果物3ファイルとサマリーを生成する。"""
    documents_path = tmp_path / "documents.jsonl"
    output_dir = tmp_path / "chunks"
    write_documents_jsonl(documents_path, [record("あいうえお", "日本語.txt")])

    result = runner.invoke(
        app,
        [
            "chunk",
            "--documents",
            str(documents_path),
            "--output-dir",
            str(output_dir),
            "--max-chars",
            "3",
            "--overlap-chars",
            "0",
            "--table-max-rows",
            "2",
        ],
    )

    assert result.exit_code == 0
    assert "元文書数: 1" in result.stdout
    assert "生成チャンク数:" in result.stdout
    for file_name in ("chunks.jsonl", "summary.json", "issues.jsonl"):
        assert (output_dir / file_name).exists()
    chunks = [
        json.loads(line)
        for line in (output_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert chunks[0]["text"] == "あいう"


def test_chunk_command_handles_empty_documents_jsonl(tmp_path: Path) -> None:
    """空のdocuments.jsonlを正常に処理できる。"""
    documents_path = tmp_path / "documents.jsonl"
    documents_path.write_text("", encoding="utf-8")
    output_dir = tmp_path / "chunks"

    result = runner.invoke(
        app, ["chunk", "--documents", str(documents_path), "--output-dir", str(output_dir)]
    )

    assert result.exit_code == 0
    assert "元文書数: 0" in result.stdout
    assert (output_dir / "chunks.jsonl").read_text(encoding="utf-8") == ""


def test_chunk_command_fails_for_missing_documents(tmp_path: Path) -> None:
    """存在しないdocuments.jsonlではエラーになる。"""
    output_dir = tmp_path / "chunks"

    result = runner.invoke(
        app,
        ["chunk", "--documents", str(tmp_path / "missing.jsonl"), "--output-dir", str(output_dir)],
    )

    assert result.exit_code != 0
    assert not output_dir.exists()


@pytest.mark.parametrize(
    ("option_name", "value"),
    [
        ("--max-chars", "0"),
        ("--overlap-chars", "-1"),
        ("--table-max-rows", "0"),
    ],
)
def test_chunk_command_fails_for_invalid_numeric_options(
    tmp_path: Path,
    option_name: str,
    value: str,
) -> None:
    """不正な数値オプションではエラーになる。"""
    documents_path = tmp_path / "documents.jsonl"
    write_documents_jsonl(documents_path, [record()])

    result = runner.invoke(app, ["chunk", "--documents", str(documents_path), option_name, value])

    assert result.exit_code != 0
