"""indexコマンドの統合テスト。"""

import json
from pathlib import Path

from typer.testing import CliRunner

from signate_drive_rag.cli import app

runner = CliRunner()


def write_chunks_jsonl(path: Path) -> None:
    """テスト用chunks.jsonlを書き込む。"""
    records = [
        {
            "chunk_id": "chunk-1",
            "relative_path": "資料/契約.md",
            "parser_name": "markdown",
            "unit_type": "markdown_section",
            "text": "契約金額 TASK-001",
            "locator": "heading:1",
            "source_unit_indices": [0],
            "chunk_index": 0,
            "metadata": {"heading": "契約"},
        }
    ]
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def test_index_command_builds_outputs_with_options(tmp_path: Path) -> None:
    """indexコマンドでchunksを受け取り成果物を生成できる。"""
    chunks_path = tmp_path / "chunks.jsonl"
    output_dir = tmp_path / "bm25"
    write_chunks_jsonl(chunks_path)

    result = runner.invoke(
        app,
        [
            "index",
            "--chunks",
            str(chunks_path),
            "--output-dir",
            str(output_dir),
            "--ngram-min",
            "2",
            "--ngram-max",
            "3",
        ],
    )

    assert result.exit_code == 0
    assert "チャンク数: 1" in result.stdout
    for file_name in ("manifest.json", "records.jsonl"):
        assert (output_dir / file_name).exists()
    for channel_name in ("content_word", "content_ngram", "context_word"):
        assert (output_dir / channel_name).is_dir()


def test_index_command_does_not_overwrite_existing_index_without_option(tmp_path: Path) -> None:
    """既存インデックスは--overwriteなしでは安全にエラーにする。"""
    chunks_path = tmp_path / "chunks.jsonl"
    output_dir = tmp_path / "bm25"
    write_chunks_jsonl(chunks_path)
    first = runner.invoke(
        app, ["index", "--chunks", str(chunks_path), "--output-dir", str(output_dir)]
    )
    second = runner.invoke(
        app, ["index", "--chunks", str(chunks_path), "--output-dir", str(output_dir)]
    )

    assert first.exit_code == 0
    assert second.exit_code == 2
    assert "既に存在します" in second.stderr

    overwritten = runner.invoke(
        app,
        ["index", "--chunks", str(chunks_path), "--output-dir", str(output_dir), "--overwrite"],
    )
    assert overwritten.exit_code == 0


def test_index_command_rejects_invalid_ngram_options(tmp_path: Path) -> None:
    """不正なN-gram設定ではエラーになる。"""
    chunks_path = tmp_path / "chunks.jsonl"
    write_chunks_jsonl(chunks_path)

    result = runner.invoke(
        app, ["index", "--chunks", str(chunks_path), "--ngram-min", "3", "--ngram-max", "2"]
    )

    assert result.exit_code == 2
