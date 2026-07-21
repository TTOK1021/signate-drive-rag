"""PDF診断処理のテスト。"""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from pypdf import PdfWriter

from signate_drive_rag.docling_poc.models import ConversionOutput
from signate_drive_rag.document_diagnostics.models import PdfDiagnosticResult
from signate_drive_rag.document_diagnostics.pdf_diagnostic import (
    classify_pdf_diagnostic,
    diagnose_pdf_file,
)
from signate_drive_rag.domain import SourceFile
from signate_drive_rag.domain.extracted_document import JsonValue


class FakeDoclingAdapter:
    """PDF診断からDoclingを呼び出す経路だけを確認する偽アダプター。"""

    def __init__(self, status: str = "success") -> None:
        self.status = status
        self.calls: list[tuple[str, str, int]] = []

    def convert(
        self,
        source_path: Path,
        *,
        profile: str,
        timeout_seconds: int,
    ) -> ConversionOutput:
        """外部変換を行わず、指定されたstatusを返す。"""
        self.calls.append((source_path.name, profile, timeout_seconds))
        json_document: dict[str, JsonValue] = {}
        return ConversionOutput(
            status=self.status,
            markdown="",
            text="",
            json_document=json_document,
            document=None,
            warnings=(),
            errors=(),
        )


def make_source_file(path: Path, root: Path) -> SourceFile:
    """テスト用SourceFileを作成する。"""
    stat_result = path.stat()
    return SourceFile(
        path=path,
        relative_path=path.relative_to(root),
        name=path.name,
        suffix=path.suffix.lower(),
        mime_type=None,
        size_bytes=stat_result.st_size,
        modified_at=datetime.fromtimestamp(stat_result.st_mtime, tz=UTC),
    )


def write_blank_pdf(path: Path, *, encrypted_password: str | None = None) -> None:
    """最小限のPDFを作成する。"""
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    if encrypted_password is not None:
        writer.encrypt(encrypted_password)
    with path.open("wb") as output_file:
        writer.write(output_file)


def base_result(**overrides: object) -> PdfDiagnosticResult:
    """分類テスト用の標準結果を作成する。"""
    result = PdfDiagnosticResult(
        relative_path="a.pdf",
        size_bytes=10,
        sha256="sha",
        header_is_pdf=True,
        eof_marker_found=True,
        pypdf_readable=True,
        encrypted=False,
        decryption_attempted=False,
        decryption_succeeded=None,
        page_count=1,
        pages_with_text=0,
        sampled_text_characters=0,
        metadata_available=True,
        docling_attempted=False,
        docling_status=None,
        docling_error_type=None,
        docling_error_message=None,
        diagnosis="unknown",
        warnings=(),
        errors=(),
    )
    return replace(result, **overrides)


def test_diagnose_pdf_file_reads_basic_pdf_with_pypdf(tmp_path: Path) -> None:
    """pypdfで通常PDFのヘッダー、EOF、ページ数を診断できる。"""
    pdf_path = tmp_path / "資料.pdf"
    write_blank_pdf(pdf_path)

    result = diagnose_pdf_file(make_source_file(pdf_path, tmp_path), sample_pages=3)

    assert result.relative_path == "資料.pdf"
    assert result.header_is_pdf
    assert result.eof_marker_found
    assert result.pypdf_readable
    assert result.page_count == 1
    assert result.pages_with_text == 0
    assert result.sampled_text_characters == 0
    assert result.diagnosis == "readable_image_or_empty_text_pdf"


def test_diagnose_pdf_file_detects_not_pdf_and_header_only(tmp_path: Path) -> None:
    """PDF拡張子でも実体がPDFでない場合とヘッダーだけの場合を分類できる。"""
    not_pdf_path = tmp_path / "not_pdf.pdf"
    header_only_path = tmp_path / "header_only.pdf"
    not_pdf_path.write_text("not pdf", encoding="utf-8")
    header_only_path.write_bytes(b"%PDF-1.4\n")

    not_pdf = diagnose_pdf_file(make_source_file(not_pdf_path, tmp_path), sample_pages=1)
    header_only = diagnose_pdf_file(make_source_file(header_only_path, tmp_path), sample_pages=1)

    assert not_pdf.diagnosis == "not_pdf"
    assert header_only.diagnosis == "pdf_header_only"
    assert header_only.errors


def test_diagnose_pdf_file_attempts_empty_password_for_encrypted_pdf(tmp_path: Path) -> None:
    """暗号化PDFでは空パスワードだけを試行し、解除可否を記録する。"""
    pdf_path = tmp_path / "encrypted.pdf"
    write_blank_pdf(pdf_path, encrypted_password="secret")

    result = diagnose_pdf_file(make_source_file(pdf_path, tmp_path), sample_pages=1)

    assert result.encrypted is True
    assert result.decryption_attempted
    assert result.decryption_succeeded is False
    assert result.diagnosis == "encrypted_unreadable"


def test_diagnose_pdf_file_records_docling_smoke_result(tmp_path: Path) -> None:
    """try_docling相当の診断ではdefault_localだけを試行する。"""
    pdf_path = tmp_path / "a.pdf"
    write_blank_pdf(pdf_path)
    adapter = FakeDoclingAdapter(status="failed")

    result = diagnose_pdf_file(
        make_source_file(pdf_path, tmp_path),
        sample_pages=1,
        docling_adapter=adapter,
    )

    assert adapter.calls == [("a.pdf", "default_local", 180)]
    assert result.docling_attempted
    assert result.docling_status == "failed"
    assert result.diagnosis == "docling_backend_failure"


def test_classify_pdf_diagnostic_returns_expected_categories() -> None:
    """診断分類が決定的に選ばれることを確認する。"""
    assert classify_pdf_diagnostic(base_result(size_bytes=0)) == "empty_file"
    assert classify_pdf_diagnostic(base_result(header_is_pdf=False)) == "not_pdf"
    assert (
        classify_pdf_diagnostic(
            base_result(
                encrypted=True,
                decryption_succeeded=False,
                pypdf_readable=False,
            )
        )
        == "encrypted_unreadable"
    )
    assert (
        classify_pdf_diagnostic(base_result(eof_marker_found=False, pypdf_readable=False))
        == "pdf_header_only"
    )
    assert classify_pdf_diagnostic(base_result(pypdf_readable=False)) == "pypdf_unreadable"
    assert classify_pdf_diagnostic(base_result(sampled_text_characters=5)) == "readable_text_pdf"
