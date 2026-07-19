"""文書診断シリアライザーのテスト。"""

import json
from pathlib import Path

import pytest

from signate_drive_rag.document_diagnostics.models import (
    DocumentDiagnosticManifest,
    DocumentDiagnosticReport,
    DocumentDiagnosticSummary,
    IgnoredFile,
    OcrEnvironmentDiagnostic,
    PdfDiagnosticResult,
)
from signate_drive_rag.document_diagnostics.serializer import (
    DocumentDiagnosticOutputError,
    save_document_diagnostic_report,
)


def make_report() -> DocumentDiagnosticReport:
    """保存テスト用の診断結果を作成する。"""
    pdf_results = (
        PdfDiagnosticResult(
            relative_path="案件/資料/a.pdf",
            size_bytes=123,
            sha256="abc",
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
            docling_attempted=True,
            docling_status="success",
            docling_error_type=None,
            docling_error_message=None,
            diagnosis="readable_image_or_empty_text_pdf",
            warnings=(),
            errors=(),
        ),
    )
    return DocumentDiagnosticReport(
        manifest=DocumentDiagnosticManifest(
            formats=("pdf",),
            sample_pages=3,
            try_docling=True,
            diagnose_ocr=True,
            remote_services_enabled=False,
            dependencies={"pypdf": "6.14.2", "docling": "2.113.0"},
        ),
        pdf_results=pdf_results,
        ocr_environment=OcrEnvironmentDiagnostic(
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
        ),
        ignored_files=(
            IgnoredFile(
                relative_path="案件/資料/~$一時.docx",
                suffix=".docx",
                size_bytes=10,
                reason="office_temporary_file",
            ),
        ),
        summary=DocumentDiagnosticSummary(
            candidate_files=1,
            diagnosed_files=1,
            ignored_files=1,
            ignored_by_reason={"office_temporary_file": 1},
            header_is_pdf=1,
            header_is_not_pdf=0,
            pypdf_readable=1,
            pypdf_unreadable=0,
            encrypted=0,
            encrypted_unreadable=0,
            readable_text_pdf=0,
            readable_image_or_empty_text_pdf=1,
            docling_attempted=1,
            docling_success=1,
            docling_partial_success=0,
            docling_failed=0,
            diagnosis_counts={"readable_image_or_empty_text_pdf": 1},
            ocr_usable=True,
            ocr_diagnosis="usable",
        ),
    )


def test_save_document_diagnostic_report_writes_expected_files_and_json(
    tmp_path: Path,
) -> None:
    """診断成果物をJSON/JSONL/Markdownとして保存できる。"""
    output_dir = tmp_path / "diagnostics"

    save_document_diagnostic_report(make_report(), output_dir, overwrite=False)

    for file_name in [
        "manifest.json",
        "pdf_results.jsonl",
        "ocr_environment.json",
        "ignored.jsonl",
        "summary.json",
        "report.md",
    ]:
        assert (output_dir / file_name).exists()

    pdf_lines = (output_dir / "pdf_results.jsonl").read_text(encoding="utf-8").splitlines()
    ignored_lines = (output_dir / "ignored.jsonl").read_text(encoding="utf-8").splitlines()
    pdf_record = json.loads(pdf_lines[0])
    ignored_record = json.loads(ignored_lines[0])
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    ocr_environment = json.loads((output_dir / "ocr_environment.json").read_text(encoding="utf-8"))

    assert pdf_record["relative_path"] == "案件/資料/a.pdf"
    assert ignored_record["relative_path"] == "案件/資料/~$一時.docx"
    assert str(tmp_path) not in json.dumps(pdf_record, ensure_ascii=False)
    assert summary["candidate_files"] == 1
    assert ocr_environment["diagnosis"] == "usable"
    assert "# 文書入力・環境診断レポート" in (output_dir / "report.md").read_text(encoding="utf-8")
    assert not (tmp_path / "diagnostics.tmp").exists()


def test_save_document_diagnostic_report_creates_empty_jsonl_files(
    tmp_path: Path,
) -> None:
    """PDF結果や除外ファイルが0件でも空のJSONLファイルを生成する。"""
    report = make_report()
    empty_report = DocumentDiagnosticReport(
        manifest=report.manifest,
        pdf_results=(),
        ocr_environment=None,
        ignored_files=(),
        summary=DocumentDiagnosticSummary(
            candidate_files=0,
            diagnosed_files=0,
            ignored_files=0,
            ignored_by_reason={},
            header_is_pdf=0,
            header_is_not_pdf=0,
            pypdf_readable=0,
            pypdf_unreadable=0,
            encrypted=0,
            encrypted_unreadable=0,
            readable_text_pdf=0,
            readable_image_or_empty_text_pdf=0,
            docling_attempted=0,
            docling_success=0,
            docling_partial_success=0,
            docling_failed=0,
            diagnosis_counts={},
            ocr_usable=None,
            ocr_diagnosis=None,
        ),
    )

    save_document_diagnostic_report(empty_report, tmp_path / "diagnostics", overwrite=False)

    assert (tmp_path / "diagnostics" / "pdf_results.jsonl").read_text(encoding="utf-8") == ""
    assert (tmp_path / "diagnostics" / "ignored.jsonl").read_text(encoding="utf-8") == ""
    assert json.loads((tmp_path / "diagnostics" / "ocr_environment.json").read_text()) is None


def test_save_document_diagnostic_report_overwrite_controls_existing_output(
    tmp_path: Path,
) -> None:
    """overwriteなしでは既存成果物を守り、指定時は置換できる。"""
    output_dir = tmp_path / "diagnostics"
    output_dir.mkdir()
    marker = output_dir / "marker.txt"
    marker.write_text("old", encoding="utf-8")

    with pytest.raises(DocumentDiagnosticOutputError):
        save_document_diagnostic_report(make_report(), output_dir, overwrite=False)

    assert marker.read_text(encoding="utf-8") == "old"
    save_document_diagnostic_report(make_report(), output_dir, overwrite=True)

    assert not marker.exists()
    assert (output_dir / "manifest.json").exists()


def test_save_document_diagnostic_report_is_stable_across_repeated_saves(
    tmp_path: Path,
) -> None:
    """同じ入力を2回保存してもJSONLの出力順が変わらない。"""
    output_dir = tmp_path / "diagnostics"
    report = make_report()

    save_document_diagnostic_report(report, output_dir, overwrite=False)
    first = (output_dir / "pdf_results.jsonl").read_text(encoding="utf-8")
    save_document_diagnostic_report(report, output_dir, overwrite=True)
    second = (output_dir / "pdf_results.jsonl").read_text(encoding="utf-8")

    assert first == second
