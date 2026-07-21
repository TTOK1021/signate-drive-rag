"""diagnose-documentsコマンドの統合テスト。"""

from pathlib import Path

from pypdf import PdfWriter
from typer.testing import CliRunner

from signate_drive_rag import cli
from signate_drive_rag.docling_poc.models import ConversionOutput
from signate_drive_rag.domain.extracted_document import JsonValue


class FakeAdapter:
    """CLI統合テスト用の偽Doclingアダプター。"""

    def convert(
        self,
        source_path: Path,
        *,
        profile: str,
        timeout_seconds: int,
    ) -> ConversionOutput:
        """外部処理を行わず成功扱いの変換結果を返す。"""
        json_document: dict[str, JsonValue] = {"name": source_path.name}
        return ConversionOutput(
            status="success",
            markdown="",
            text="",
            json_document=json_document,
            document=None,
            warnings=(),
            errors=(),
        )


def write_blank_pdf(path: Path) -> None:
    """最小限のPDFを作成する。"""
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as output_file:
        writer.write(output_file)


def test_diagnose_documents_command_writes_outputs_and_prints_summary(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """diagnose-documentsコマンドで成果物と件数表示を生成できる。"""
    source = tmp_path / "share"
    output_dir = tmp_path / "diagnostics"
    source.mkdir()
    write_blank_pdf(source / "資料.pdf")
    (source / "~$一時.docx").write_text("lock", encoding="utf-8")
    monkeypatch.setattr(cli, "create_docling_conversion_adapter", lambda: FakeAdapter())

    result = CliRunner().invoke(
        cli.app,
        [
            "diagnose-documents",
            "--source",
            str(source),
            "--output-dir",
            str(output_dir),
            "--formats",
            "pdf",
            "--sample-pages",
            "1",
            "--try-docling",
            "--no-diagnose-ocr",
        ],
    )

    assert result.exit_code == 0
    assert "文書入力・環境診断を完了しました" in result.stdout
    assert "PDF候補数: 1" in result.stdout
    assert "Office一時ファイル除外数: 1" in result.stdout
    for file_name in [
        "manifest.json",
        "pdf_results.jsonl",
        "ocr_environment.json",
        "ignored.jsonl",
        "summary.json",
        "report.md",
    ]:
        assert (output_dir / file_name).exists()


def test_diagnose_documents_command_handles_empty_directory(tmp_path: Path) -> None:
    """空ディレクトリでも正常終了し、空の成果物を生成する。"""
    source = tmp_path / "share"
    output_dir = tmp_path / "diagnostics"
    source.mkdir()

    result = CliRunner().invoke(
        cli.app,
        [
            "diagnose-documents",
            "--source",
            str(source),
            "--output-dir",
            str(output_dir),
            "--no-diagnose-ocr",
        ],
    )

    assert result.exit_code == 0
    assert "PDF候補数: 0" in result.stdout
    assert (output_dir / "pdf_results.jsonl").read_text(encoding="utf-8") == ""


def test_diagnose_documents_command_rejects_invalid_inputs(tmp_path: Path) -> None:
    """存在しないsourceや未対応形式をエラーにする。"""
    source = tmp_path / "share"
    source.mkdir()
    runner = CliRunner()

    missing = runner.invoke(
        cli.app,
        ["diagnose-documents", "--source", str(tmp_path / "missing"), "--no-diagnose-ocr"],
    )
    unknown_format = runner.invoke(
        cli.app,
        [
            "diagnose-documents",
            "--source",
            str(source),
            "--formats",
            "docx",
            "--no-diagnose-ocr",
        ],
    )

    assert missing.exit_code == 2
    assert unknown_format.exit_code == 2
