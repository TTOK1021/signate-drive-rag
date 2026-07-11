"""CLIの単体テスト。"""

import json
from pathlib import Path

from typer.testing import CliRunner

from signate_drive_rag.cli import app

runner = CliRunner()


def test_scan_command_uses_root_option_and_prints_extension_summary(tmp_path: Path) -> None:
    """--rootで指定した探索ルートの件数と拡張子別集計を表示できる。"""
    (tmp_path / "document.PDF").write_text("pdf", encoding="utf-8")
    (tmp_path / "table.xlsx").write_text("xlsx", encoding="utf-8")
    (tmp_path / "note.txt").write_text("txt", encoding="utf-8")

    result = runner.invoke(app, ["scan", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert f"探索ルート: {tmp_path.resolve()}" in result.stdout
    assert "検出ファイル数: 3" in result.stdout
    assert ".pdf" in result.stdout
    assert ".xlsx" in result.stdout
    assert "その他" in result.stdout


def test_scan_command_prints_other_extension_breakdown(tmp_path: Path) -> None:
    """主要表示対象に含まれない拡張子の内訳を表示できる。"""
    (tmp_path / "a.txt").write_text("txt", encoding="utf-8")
    (tmp_path / "b.txt").write_text("txt", encoding="utf-8")
    (tmp_path / "c.md").write_text("md", encoding="utf-8")
    (tmp_path / "README").write_text("no extension", encoding="utf-8")

    result = runner.invoke(app, ["scan", "--root", str(tmp_path)])

    assert result.exit_code == 0
    assert "その他     4" in result.stdout
    assert "その他内訳:" in result.stdout
    assert ".txt    2" in result.stdout
    assert ".md     1" in result.stdout
    assert "拡張子なし   1" in result.stdout


def test_scan_command_uses_source_root_from_dotenv(tmp_path: Path, monkeypatch) -> None:
    """--rootがない場合は.envのSOURCE_ROOTを探索ルートとして使用できる。"""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    source_root = tmp_path / "share"
    source_root.mkdir()
    (source_root / "answer.docx").write_text("docx", encoding="utf-8")
    (project_dir / ".env").write_text(f"SOURCE_ROOT={source_root}\n", encoding="utf-8")
    monkeypatch.chdir(project_dir)
    monkeypatch.delenv("SOURCE_ROOT", raising=False)

    result = runner.invoke(app, ["scan"])

    assert result.exit_code == 0
    assert f"探索ルート: {source_root.resolve()}" in result.stdout
    assert "検出ファイル数: 1" in result.stdout


def test_scan_command_writes_manifest_jsonl_when_manifest_is_specified(tmp_path: Path) -> None:
    """--manifestを指定した場合は検出結果をJSON Linesで保存できる。"""
    source_path = tmp_path / "共有" / "資料.py"
    source_path.parent.mkdir()
    source_path.write_text("print('hello')", encoding="utf-8")
    manifest_path = tmp_path / "artifacts" / "manifest.jsonl"

    result = runner.invoke(
        app,
        ["scan", "--root", str(source_path.parent), "--manifest", str(manifest_path)],
    )

    assert result.exit_code == 0
    records = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()]
    assert records == [
        {
            "path": str(source_path.resolve()),
            "relative_path": "資料.py",
            "name": "資料.py",
            "suffix": ".py",
            "mime_type": "text/x-python",
            "size_bytes": 14,
            "modified_at": records[0]["modified_at"],
        }
    ]


def test_scan_command_requires_root_option_or_source_root(tmp_path: Path, monkeypatch) -> None:
    """--rootもSOURCE_ROOTもない場合はエラーとして終了する。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SOURCE_ROOT", raising=False)

    result = runner.invoke(app, ["scan"])

    assert result.exit_code == 2
    assert "--root または SOURCE_ROOT を指定してください。" in result.stderr
