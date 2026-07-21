"""文書診断サービスのテスト。"""

from pathlib import Path

from pypdf import PdfWriter

from signate_drive_rag.docling_poc.models import ConversionOutput
from signate_drive_rag.document_diagnostics.models import OcrEnvironmentDiagnostic
from signate_drive_rag.document_diagnostics.service import (
    DocumentDiagnosticInputError,
    DocumentDiagnosticService,
    parse_diagnostic_formats,
)
from signate_drive_rag.domain.extracted_document import JsonValue


class FakeDoclingAdapter:
    """サービスからDoclingを呼ぶ経路を確認する偽アダプター。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def convert(
        self,
        source_path: Path,
        *,
        profile: str,
        timeout_seconds: int,
    ) -> ConversionOutput:
        """ファイル名に応じて成功または失敗を返す。"""
        self.calls.append(source_path.name)
        json_document: dict[str, JsonValue] = {}
        if source_path.name == "failed.pdf":
            return ConversionOutput(
                status="failed",
                markdown="",
                text="",
                json_document=json_document,
                document=None,
                warnings=(),
                errors=("BackendError: failed",),
            )
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


def usable_ocr_environment() -> OcrEnvironmentDiagnostic:
    """利用可能なOCR環境診断結果を返す。"""
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


def test_document_diagnostic_service_diagnoses_pdfs_and_summarizes_counts(
    tmp_path: Path,
) -> None:
    """PDF診断結果、Office一時ファイル除外、集計値が一致することを確認する。"""
    nested_dir = tmp_path / "案件" / "資料"
    nested_dir.mkdir(parents=True)
    write_blank_pdf(nested_dir / "b.pdf")
    write_blank_pdf(nested_dir / "a.pdf")
    (nested_dir / "failed.pdf").write_bytes(b"%PDF-1.4\n")
    (nested_dir / "~$一時.docx").write_text("lock", encoding="utf-8")
    (nested_dir / "memo.txt").write_text("memo", encoding="utf-8")
    adapter = FakeDoclingAdapter()
    ocr_calls = 0

    def diagnose_ocr() -> OcrEnvironmentDiagnostic:
        nonlocal ocr_calls
        ocr_calls += 1
        return usable_ocr_environment()

    report = DocumentDiagnosticService(
        docling_adapter_factory=lambda: adapter,
        ocr_diagnostic_func=diagnose_ocr,
    ).diagnose(
        tmp_path,
        formats=("pdf",),
        sample_pages=1,
        try_docling=True,
        diagnose_ocr=True,
    )

    assert [result.relative_path for result in report.pdf_results] == [
        "案件/資料/a.pdf",
        "案件/資料/b.pdf",
        "案件/資料/failed.pdf",
    ]
    assert adapter.calls == ["a.pdf", "b.pdf", "failed.pdf"]
    assert ocr_calls == 1
    assert report.summary.candidate_files == 3
    assert report.summary.diagnosed_files == 3
    assert report.summary.ignored_files == 1
    assert report.summary.docling_attempted == 3
    assert report.summary.docling_success == 2
    assert report.summary.docling_failed == 1
    assert report.summary.ocr_usable is True
    assert report.summary.ignored_by_reason == {"office_temporary_file": 1}
    assert report.ignored_files[0].relative_path == "案件/資料/~$一時.docx"


def test_document_diagnostic_service_handles_empty_input_without_external_calls(
    tmp_path: Path,
) -> None:
    """空ディレクトリではPDFなしの診断結果を返す。"""
    report = DocumentDiagnosticService(
        docling_adapter_factory=lambda: FakeDoclingAdapter(),
        ocr_diagnostic_func=usable_ocr_environment,
    ).diagnose(
        tmp_path,
        formats=("pdf",),
        sample_pages=3,
        try_docling=False,
        diagnose_ocr=False,
    )

    assert report.pdf_results == ()
    assert report.ignored_files == ()
    assert report.summary.candidate_files == 0
    assert report.summary.ocr_usable is None
    assert report.manifest.dependencies["pypdf"]


def test_parse_diagnostic_formats_accepts_pdf_and_rejects_unknown() -> None:
    """診断対象形式はPDFだけを受け付ける。"""
    assert parse_diagnostic_formats(".pdf,pdf") == ("pdf",)

    try:
        parse_diagnostic_formats("docx")
    except DocumentDiagnosticInputError as error:
        assert "docx" in str(error)
    else:
        raise AssertionError("DocumentDiagnosticInputError was not raised")


def test_document_diagnostic_service_validates_sample_pages(tmp_path: Path) -> None:
    """sample_pagesは1以上である必要がある。"""
    try:
        DocumentDiagnosticService().diagnose(
            tmp_path,
            formats=("pdf",),
            sample_pages=0,
            try_docling=False,
            diagnose_ocr=False,
        )
    except DocumentDiagnosticInputError:
        pass
    else:
        raise AssertionError("DocumentDiagnosticInputError was not raised")
