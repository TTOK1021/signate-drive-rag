"""OCR有効時の抽出統合テスト。"""

import json
from pathlib import Path

from PIL import Image
from typer.testing import CliRunner

from signate_drive_rag.cli import app

runner = CliRunner()


def test_extract_command_with_ocr_registers_png_without_model_download(tmp_path: Path) -> None:
    """OCR有効時にPNGが対応形式となり、モデル不足はissueとして保存される。"""
    root = tmp_path / "root"
    root.mkdir()
    Image.new("RGB", (10, 10), color="white").save(root / "画像.png", format="PNG")
    output_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        [
            "extract",
            "--root",
            str(root),
            "--output-dir",
            str(output_dir),
            "--enable-ocr",
            "--ocr-model-dir",
            str(tmp_path / "missing-models"),
        ],
    )

    assert result.exit_code == 0
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    documents = [
        json.loads(line)
        for line in (output_dir / "documents.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert summary["by_parser"] == {"easyocr_png": 1}
    assert summary["unsupported_files"] == 0
    assert documents[0]["parser_name"] == "easyocr_png"
    assert documents[0]["issues"][0]["issue_type"] == "ocr_model_unavailable"


def test_extract_command_without_ocr_keeps_png_unsupported(tmp_path: Path) -> None:
    """OCR無効時は従来どおりPNGを未対応として扱う。"""
    root = tmp_path / "root"
    root.mkdir()
    Image.new("RGB", (10, 10), color="white").save(root / "画像.png", format="PNG")
    output_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        ["extract", "--root", str(root), "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 0
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["unsupported_files"] == 1
