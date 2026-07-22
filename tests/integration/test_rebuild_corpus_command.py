"""rebuild-corpusコマンドの統合テスト。"""

import json
from pathlib import Path

from typer.testing import CliRunner

from signate_drive_rag.cli import app

runner = CliRunner()


def test_rebuild_corpus_command_runs_and_writes_pipeline_artifacts(tmp_path: Path) -> None:
    """CLIからsourceとoutput-dirを受け取り、主要成果物を生成する。"""
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("検索対象テキスト", encoding="utf-8")
    (source / "image.png").write_bytes(b"not a real image")
    output_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        [
            "rebuild-corpus",
            "--source",
            str(source),
            "--output-dir",
            str(output_dir),
            "--overwrite",
        ],
    )

    assert result.exit_code == 0
    assert "全文書コーパス再構築を完了しました" in result.stdout
    assert "scan: success" in result.stdout
    assert "evaluate_search: skipped" in result.stdout
    for relative_path in (
        "manifest.json",
        "stage_status.json",
        "source_snapshot.jsonl",
        "report.md",
        "scan/summary.json",
        "extraction/documents.jsonl",
        "extraction/errors.jsonl",
        "chunks/chunks.jsonl",
        "validation/errors.jsonl",
        "indexes/bm25/manifest.json",
    ):
        assert (output_dir / relative_path).exists()
    extraction_summary = json.loads(
        (output_dir / "extraction" / "summary.json").read_text(encoding="utf-8")
    )
    assert extraction_summary["succeeded_files"] == 1
    assert extraction_summary["unsupported_files"] == 1


def test_rebuild_corpus_command_handles_empty_directory(tmp_path: Path) -> None:
    """空ディレクトリでも一括パイプラインを正常終了できる。"""
    source = tmp_path / "source"
    source.mkdir()
    output_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        [
            "rebuild-corpus",
            "--source",
            str(source),
            "--output-dir",
            str(output_dir),
            "--overwrite",
        ],
    )

    assert result.exit_code == 0
    assert "build_bm25: success" in result.stdout
    scan_summary = json.loads((output_dir / "scan" / "summary.json").read_text(encoding="utf-8"))
    assert scan_summary["discovered_files"] == 0


def test_rebuild_corpus_command_fails_for_missing_source(tmp_path: Path) -> None:
    """存在しないsourceでは成果物を作らずエラー終了する。"""
    output_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        [
            "rebuild-corpus",
            "--source",
            str(tmp_path / "missing"),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 2
    assert "入力ルートが存在しません" in result.stderr
    assert not output_dir.exists()
