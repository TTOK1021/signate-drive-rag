"""docling-pocコマンドの統合テスト。"""

from pathlib import Path

from typer.testing import CliRunner

from signate_drive_rag import cli
from signate_drive_rag.docling_poc import service as docling_poc_service
from signate_drive_rag.docling_poc.models import ConversionOutput
from signate_drive_rag.document_diagnostics.models import OcrEnvironmentDiagnostic
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
        """外部通信もモデル取得も行わない偽変換を返す。"""
        json_document: dict[str, JsonValue] = {"name": source_path.name}
        return ConversionOutput(
            status="success",
            markdown=f"# {source_path.name}",
            text=f"text {source_path.name}",
            json_document=json_document,
            document=None,
            warnings=(),
            errors=(),
        )


def create_files(root: Path) -> None:
    """テスト用の小さな入力ファイルを作成する。"""
    root.mkdir()
    for name in ["a.docx", "b.pdf", "c.png", "d.txt"]:
        (root / name).write_text("dummy", encoding="utf-8")


def make_ocr_environment() -> OcrEnvironmentDiagnostic:
    """CLI統合テスト用に利用可能なOCR環境を返す。"""
    return OcrEnvironmentDiagnostic(
        engine="tesseract",
        executable_found=True,
        executable_path="tesseract",
        version="tesseract 5.3.0",
        available_languages=("eng", "jpn"),
        required_languages=("eng", "jpn"),
        missing_languages=(),
        usable=True,
        diagnosis="usable",
        warnings=(),
        errors=(),
    )


def test_docling_poc_command_writes_outputs_and_prints_summary(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """docling-pocコマンドで成果物とサマリーを生成できる。"""
    source = tmp_path / "share"
    output_dir = tmp_path / "out"
    create_files(source)
    monkeypatch.setattr(cli, "create_docling_conversion_adapter", lambda: FakeAdapter())
    monkeypatch.setattr(
        docling_poc_service,
        "diagnose_tesseract_environment",
        make_ocr_environment,
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "docling-poc",
            "--source",
            str(source),
            "--output-dir",
            str(output_dir),
            "--formats",
            "docx,pdf,png",
            "--samples-per-format",
            "1",
            "--profiles",
            "default_local,japanese_ocr",
            "--timeout-seconds",
            "10",
            "--preview-chars",
            "30",
        ],
    )

    assert result.exit_code == 0
    assert "Docling形式別PoCを完了しました" in result.stdout
    assert "変換実行数: 5" in result.stdout
    for file_name in [
        "manifest.json",
        "selection.jsonl",
        "results.jsonl",
        "errors.jsonl",
        "summary.json",
        "review.csv",
        "report.md",
    ]:
        assert (output_dir / file_name).exists()


def test_docling_poc_command_rejects_invalid_inputs(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """存在しないsource、未知形式、未知profile、不正な数値をエラーにする。"""
    source = tmp_path / "share"
    create_files(source)
    monkeypatch.setattr(cli, "create_docling_conversion_adapter", lambda: FakeAdapter())
    runner = CliRunner()

    missing = runner.invoke(cli.app, ["docling-poc", "--source", str(tmp_path / "missing")])
    unknown_format = runner.invoke(
        cli.app,
        ["docling-poc", "--source", str(source), "--formats", "gif"],
    )
    unknown_profile = runner.invoke(
        cli.app,
        ["docling-poc", "--source", str(source), "--profiles", "unknown"],
    )
    invalid_number = runner.invoke(
        cli.app,
        ["docling-poc", "--source", str(source), "--samples-per-format", "0"],
    )

    assert missing.exit_code == 2
    assert unknown_format.exit_code == 2
    assert unknown_profile.exit_code == 2
    assert invalid_number.exit_code == 2


def test_docling_poc_command_overwrite_controls_existing_output(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """既存出力はoverwriteなしで保護し、overwriteで置換できる。"""
    source = tmp_path / "share"
    output_dir = tmp_path / "out"
    create_files(source)
    output_dir.mkdir()
    (output_dir / "old.txt").write_text("old", encoding="utf-8")
    monkeypatch.setattr(cli, "create_docling_conversion_adapter", lambda: FakeAdapter())
    runner = CliRunner()

    blocked = runner.invoke(
        cli.app, ["docling-poc", "--source", str(source), "--output-dir", str(output_dir)]
    )
    overwritten = runner.invoke(
        cli.app,
        [
            "docling-poc",
            "--source",
            str(source),
            "--output-dir",
            str(output_dir),
            "--overwrite",
            "--formats",
            "pdf",
            "--samples-per-format",
            "1",
            "--profiles",
            "default_local",
        ],
    )

    assert blocked.exit_code == 2
    assert overwritten.exit_code == 0
    assert not (output_dir / "old.txt").exists()
    assert (output_dir / "manifest.json").exists()
