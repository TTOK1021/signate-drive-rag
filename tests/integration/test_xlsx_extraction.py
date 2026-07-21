"""XLSX抽出パイプラインの統合テスト。"""

import json
from pathlib import Path

from openpyxl import Workbook
from typer.testing import CliRunner

from signate_drive_rag.cli import app

runner = CliRunner()


def make_workbook(path: Path) -> None:
    """統合テスト用XLSXを作成する。"""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "集計"
    sheet.append(["ID", "値"])
    sheet.append(["A", 1])
    sheet.append(["B", "=SUM(B2:B2)"])
    workbook.save(path)


def test_xlsx_pipeline_extracts_audits_and_chunks(tmp_path: Path) -> None:
    """scan、extract、audit、chunkでXLSXが既存パイプラインに接続される。"""
    root = tmp_path / "root"
    root.mkdir()
    make_workbook(root / "集計.xlsx")
    make_workbook(root / "~$一時.xlsx")
    (root / "bad.xlsx").write_text("not zip", encoding="utf-8")
    extracted_dir = tmp_path / "extracted"
    audit_dir = tmp_path / "audit"
    chunks_dir = tmp_path / "chunks"

    scan_result = runner.invoke(app, ["scan", "--root", str(root)])
    assert scan_result.exit_code == 0
    assert "検出ファイル数: 2" in scan_result.stdout
    assert "除外ファイル数: 1" in scan_result.stdout

    extract_result = runner.invoke(
        app,
        ["extract", "--root", str(root), "--output-dir", str(extracted_dir)],
    )
    assert extract_result.exit_code == 0
    assert "抽出成功: 1" in extract_result.stdout
    assert "抽出失敗: 1" in extract_result.stdout

    documents = [
        json.loads(line)
        for line in (extracted_dir / "documents.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert documents[0]["parser_name"] == "openpyxl_xlsx"
    assert {unit["unit_type"] for unit in documents[0]["units"]} >= {
        "xlsx_workbook_summary",
        "xlsx_sheet_summary",
        "xlsx_table_rows",
    }
    assert (extracted_dir / "failures.jsonl").read_text(encoding="utf-8")

    audit_result = runner.invoke(
        app,
        [
            "audit",
            "--documents",
            str(extracted_dir / "documents.jsonl"),
            "--output-dir",
            str(audit_dir),
        ],
    )
    assert audit_result.exit_code == 0
    audit_summary = json.loads((audit_dir / "summary.json").read_text(encoding="utf-8"))
    assert audit_summary["xlsx_sheets"] == 1
    assert audit_summary["xlsx_row_blocks"] >= 1

    chunk_result = runner.invoke(
        app,
        [
            "chunk",
            "--documents",
            str(extracted_dir / "documents.jsonl"),
            "--output-dir",
            str(chunks_dir),
        ],
    )
    assert chunk_result.exit_code == 0
    chunks = [
        json.loads(line)
        for line in (chunks_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    row_chunk = next(chunk for chunk in chunks if chunk["unit_type"] == "xlsx_table_rows")
    assert row_chunk["metadata"]["sheet_name"] == "集計"
    assert row_chunk["metadata"]["range"]
