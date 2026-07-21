"""文書入力とローカル処理環境を一括診断するサービス。"""

import logging
from collections import Counter
from collections.abc import Callable, Sequence
from importlib import metadata
from pathlib import Path

from signate_drive_rag.docling_poc.models import DocumentConversionAdapter
from signate_drive_rag.document_diagnostics.models import (
    DocumentDiagnosticManifest,
    DocumentDiagnosticReport,
    DocumentDiagnosticSummary,
    OcrEnvironmentDiagnostic,
    PdfDiagnosticResult,
)
from signate_drive_rag.document_diagnostics.ocr_diagnostic import diagnose_tesseract_environment
from signate_drive_rag.document_diagnostics.pdf_diagnostic import (
    classify_pdf_diagnostic,
    diagnose_pdf_file,
)
from signate_drive_rag.domain import SourceFile
from signate_drive_rag.ingestion import discover_files_with_ignored

LOGGER = logging.getLogger(__name__)
SUPPORTED_DOCUMENT_DIAGNOSTIC_FORMATS = frozenset({"pdf"})


class DocumentDiagnosticInputError(ValueError):
    """文書診断の入力値が不正な場合の例外。"""


class DocumentDiagnosticService:
    """文書入力とローカル処理環境をまとめて診断する。"""

    def __init__(
        self,
        *,
        docling_adapter_factory: Callable[[], DocumentConversionAdapter] | None = None,
        ocr_diagnostic_func: Callable[
            [], OcrEnvironmentDiagnostic
        ] = diagnose_tesseract_environment,
    ) -> None:
        """外部ツールの有無をテストで差し替えられるようにする。"""
        self._docling_adapter_factory = docling_adapter_factory
        self._ocr_diagnostic_func = ocr_diagnostic_func

    def diagnose(
        self,
        source_root: Path,
        *,
        formats: tuple[str, ...],
        sample_pages: int,
        try_docling: bool,
        diagnose_ocr: bool,
    ) -> DocumentDiagnosticReport:
        """指定ルート配下の対象形式について入力品質と処理環境を診断する。"""
        _validate_options(formats=formats, sample_pages=sample_pages)
        discovery_result = discover_files_with_ignored(source_root)
        normalized_formats = tuple(
            sorted({_normalize_format(format_name) for format_name in formats})
        )
        pdf_files = _filter_pdf_files(discovery_result.source_files, normalized_formats)
        ocr_environment = self._ocr_diagnostic_func() if diagnose_ocr else None
        docling_adapter = (
            self._docling_adapter_factory()
            if try_docling and self._docling_adapter_factory is not None
            else None
        )

        pdf_results = tuple(
            sorted(
                (
                    self._diagnose_pdf(
                        source_file,
                        sample_pages=sample_pages,
                        docling_adapter=docling_adapter,
                    )
                    for source_file in pdf_files
                ),
                key=lambda result: result.relative_path,
            )
        )
        manifest = DocumentDiagnosticManifest(
            formats=normalized_formats,
            sample_pages=sample_pages,
            try_docling=try_docling,
            diagnose_ocr=diagnose_ocr,
            remote_services_enabled=False,
            dependencies=_dependency_versions(try_docling=try_docling),
        )
        summary = _build_summary(
            pdf_results,
            ignored_files=len(discovery_result.ignored_files),
            ignored_by_reason=discovery_result.ignored_by_reason,
            ocr_environment=ocr_environment,
        )
        return DocumentDiagnosticReport(
            manifest=manifest,
            pdf_results=pdf_results,
            ocr_environment=ocr_environment,
            ignored_files=discovery_result.ignored_files,
            summary=summary,
        )

    def _diagnose_pdf(
        self,
        source_file: SourceFile,
        *,
        sample_pages: int,
        docling_adapter: DocumentConversionAdapter | None,
    ) -> PdfDiagnosticResult:
        LOGGER.info(
            "pdf_diagnostic_started",
            extra={"relative_path": source_file.relative_path.as_posix()},
        )
        try:
            result = diagnose_pdf_file(
                source_file,
                sample_pages=sample_pages,
                docling_adapter=docling_adapter,
            )
        except Exception as error:
            # 個別PDFの破損や読み取り失敗で全体診断を止めると、形式別の傾向を見失うため継続する。
            result = _unexpected_pdf_failure(source_file, error)
        LOGGER.info(
            "pdf_diagnostic_finished",
            extra={"relative_path": result.relative_path, "diagnosis": result.diagnosis},
        )
        return result


def parse_diagnostic_formats(value: str) -> tuple[str, ...]:
    """CLIのカンマ区切り形式指定を正規化する。"""
    formats = tuple(
        _normalize_format(format_name) for format_name in value.split(",") if format_name.strip()
    )
    if not formats:
        raise DocumentDiagnosticInputError("formatsを1件以上指定してください。")
    _validate_formats(formats)
    return tuple(sorted(set(formats)))


def _validate_options(*, formats: Sequence[str], sample_pages: int) -> None:
    _validate_formats(formats)
    if sample_pages <= 0:
        raise DocumentDiagnosticInputError("sample_pagesは1以上で指定してください。")


def _validate_formats(formats: Sequence[str]) -> None:
    unknown_formats = set(_normalize_format(format_name) for format_name in formats) - (
        SUPPORTED_DOCUMENT_DIAGNOSTIC_FORMATS
    )
    if unknown_formats:
        raise DocumentDiagnosticInputError(
            f"未対応の診断形式です: {', '.join(sorted(unknown_formats))}"
        )


def _normalize_format(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.startswith("."):
        normalized = normalized[1:]
    if not normalized:
        raise DocumentDiagnosticInputError("空の形式は指定できません。")
    return normalized


def _filter_pdf_files(
    source_files: Sequence[SourceFile],
    formats: tuple[str, ...],
) -> tuple[SourceFile, ...]:
    if "pdf" not in formats:
        return ()
    return tuple(
        sorted(
            (source_file for source_file in source_files if source_file.suffix.lower() == ".pdf"),
            key=lambda source_file: source_file.relative_path.as_posix(),
        )
    )


def _build_summary(
    pdf_results: Sequence[PdfDiagnosticResult],
    *,
    ignored_files: int,
    ignored_by_reason: dict[str, int],
    ocr_environment: OcrEnvironmentDiagnostic | None,
) -> DocumentDiagnosticSummary:
    diagnosis_counter = Counter(result.diagnosis for result in pdf_results)
    return DocumentDiagnosticSummary(
        candidate_files=len(pdf_results),
        diagnosed_files=len(pdf_results),
        ignored_files=ignored_files,
        ignored_by_reason=dict(sorted(ignored_by_reason.items())),
        header_is_pdf=sum(1 for result in pdf_results if result.header_is_pdf),
        header_is_not_pdf=sum(1 for result in pdf_results if not result.header_is_pdf),
        pypdf_readable=sum(1 for result in pdf_results if result.pypdf_readable),
        pypdf_unreadable=sum(1 for result in pdf_results if not result.pypdf_readable),
        encrypted=sum(1 for result in pdf_results if result.encrypted is True),
        encrypted_unreadable=diagnosis_counter["encrypted_unreadable"],
        readable_text_pdf=diagnosis_counter["readable_text_pdf"],
        readable_image_or_empty_text_pdf=diagnosis_counter["readable_image_or_empty_text_pdf"],
        docling_attempted=sum(1 for result in pdf_results if result.docling_attempted),
        docling_success=sum(1 for result in pdf_results if result.docling_status == "success"),
        docling_partial_success=sum(
            1 for result in pdf_results if result.docling_status == "partial_success"
        ),
        docling_failed=sum(1 for result in pdf_results if result.docling_status == "failed"),
        diagnosis_counts=dict(sorted(diagnosis_counter.items())),
        ocr_usable=None if ocr_environment is None else ocr_environment.usable,
        ocr_diagnosis=None if ocr_environment is None else ocr_environment.diagnosis,
    )


def _dependency_versions(*, try_docling: bool) -> dict[str, str]:
    dependency_names = ["pypdf"]
    if try_docling:
        dependency_names.append("docling")
    return {
        dependency_name: _dependency_version(dependency_name)
        for dependency_name in sorted(dependency_names)
    }


def _dependency_version(dependency_name: str) -> str:
    try:
        return metadata.version(dependency_name)
    except metadata.PackageNotFoundError:
        return "not_installed"


def _unexpected_pdf_failure(source_file: SourceFile, error: Exception) -> PdfDiagnosticResult:
    message = str(error)
    if len(message) > 500:
        message = message[:500] + "..."
    result = PdfDiagnosticResult(
        relative_path=source_file.relative_path.as_posix(),
        size_bytes=source_file.size_bytes,
        sha256="",
        header_is_pdf=False,
        eof_marker_found=False,
        pypdf_readable=False,
        encrypted=None,
        decryption_attempted=False,
        decryption_succeeded=None,
        page_count=None,
        pages_with_text=0,
        sampled_text_characters=0,
        metadata_available=False,
        docling_attempted=False,
        docling_status=None,
        docling_error_type=None,
        docling_error_message=None,
        diagnosis="unknown",
        warnings=(),
        errors=(f"{type(error).__name__}: {message}",),
    )
    return PdfDiagnosticResult(
        relative_path=result.relative_path,
        size_bytes=result.size_bytes,
        sha256=result.sha256,
        header_is_pdf=result.header_is_pdf,
        eof_marker_found=result.eof_marker_found,
        pypdf_readable=result.pypdf_readable,
        encrypted=result.encrypted,
        decryption_attempted=result.decryption_attempted,
        decryption_succeeded=result.decryption_succeeded,
        page_count=result.page_count,
        pages_with_text=result.pages_with_text,
        sampled_text_characters=result.sampled_text_characters,
        metadata_available=result.metadata_available,
        docling_attempted=result.docling_attempted,
        docling_status=result.docling_status,
        docling_error_type=result.docling_error_type,
        docling_error_message=result.docling_error_message,
        diagnosis=classify_pdf_diagnostic(result),
        warnings=result.warnings,
        errors=result.errors,
    )
