"""PDF入力ファイルの基本診断。"""

from pathlib import Path
from typing import Protocol

from pypdf import PdfReader

from signate_drive_rag.docling_poc.models import DocumentConversionAdapter
from signate_drive_rag.document_diagnostics.models import PdfDiagnosticResult
from signate_drive_rag.retrieval import calculate_file_sha256


class PdfDiagnosticInput(Protocol):
    """PDF診断に必要なSourceFile互換の入力。"""

    @property
    def path(self) -> Path:
        """診断対象ファイルの絶対パスを返す。"""
        ...

    @property
    def relative_path(self) -> Path:
        """入力ルートからの相対パスを返す。"""
        ...

    @property
    def size_bytes(self) -> int:
        """診断対象ファイルのサイズを返す。"""
        ...


def diagnose_pdf_file(
    source_file: PdfDiagnosticInput,
    *,
    sample_pages: int,
    docling_adapter: DocumentConversionAdapter | None = None,
) -> PdfDiagnosticResult:
    """1つのPDFファイルをpypdfと必要に応じてDoclingで診断する。"""
    warnings: list[str] = []
    errors: list[str] = []
    header_is_pdf = _header_is_pdf(source_file.path)
    eof_marker_found = _eof_marker_found(source_file.path)
    if source_file.size_bytes == 0:
        warnings.append("empty file")
    if not eof_marker_found:
        warnings.append("EOF marker was not found near the end of the file")

    pypdf_readable = False
    encrypted: bool | None = None
    decryption_attempted = False
    decryption_succeeded: bool | None = None
    page_count: int | None = None
    pages_with_text = 0
    sampled_text_characters = 0
    metadata_available = False

    if source_file.size_bytes > 0 and header_is_pdf:
        try:
            reader = PdfReader(source_file.path, strict=False)
            encrypted = bool(reader.is_encrypted)
            if encrypted:
                decryption_attempted = True
                decryption_succeeded = bool(reader.decrypt(""))
                if not decryption_succeeded:
                    raise ValueError("encrypted PDF cannot be opened with an empty password")
            page_count = len(reader.pages)
            metadata_available = reader.metadata is not None
            pypdf_readable = True
            pages_with_text, sampled_text_characters = _sample_text(reader, sample_pages)
        except Exception as error:
            errors.append(_safe_error(error))

    docling_attempted = docling_adapter is not None
    docling_status: str | None = None
    docling_error_type: str | None = None
    docling_error_message: str | None = None
    if docling_adapter is not None:
        try:
            output = docling_adapter.convert(
                source_file.path,
                profile="default_local",
                timeout_seconds=180,
            )
            docling_status = output.status
            if output.errors:
                docling_error_type, docling_error_message = _split_error(output.errors[0])
        except Exception as error:
            docling_status = "failed"
            docling_error_type = type(error).__name__
            docling_error_message = _safe_message(str(error))

    result_without_diagnosis = PdfDiagnosticResult(
        relative_path=source_file.relative_path.as_posix(),
        size_bytes=source_file.size_bytes,
        sha256=calculate_file_sha256(source_file.path) if source_file.path.is_file() else "",
        header_is_pdf=header_is_pdf,
        eof_marker_found=eof_marker_found,
        pypdf_readable=pypdf_readable,
        encrypted=encrypted,
        decryption_attempted=decryption_attempted,
        decryption_succeeded=decryption_succeeded,
        page_count=page_count,
        pages_with_text=pages_with_text,
        sampled_text_characters=sampled_text_characters,
        metadata_available=metadata_available,
        docling_attempted=docling_attempted,
        docling_status=docling_status,
        docling_error_type=docling_error_type,
        docling_error_message=docling_error_message,
        diagnosis="unknown",
        warnings=tuple(warnings),
        errors=tuple(errors),
    )
    return _replace_diagnosis(
        result_without_diagnosis,
        classify_pdf_diagnostic(result_without_diagnosis),
    )


def classify_pdf_diagnostic(result: PdfDiagnosticResult) -> str:
    """PDF診断結果を決定的な分類へ変換する。"""
    if result.size_bytes == 0:
        return "empty_file"
    if not result.header_is_pdf:
        return "not_pdf"
    if result.encrypted is True and result.decryption_succeeded is False:
        return "encrypted_unreadable"
    if result.header_is_pdf and not result.eof_marker_found and not result.pypdf_readable:
        return "pdf_header_only"
    if not result.pypdf_readable:
        return "pypdf_unreadable"
    if result.docling_status in {"success", "partial_success"}:
        return "docling_success"
    if result.docling_status == "failed":
        return "docling_backend_failure"
    if result.sampled_text_characters > 0:
        return "readable_text_pdf"
    if result.pypdf_readable:
        return "readable_image_or_empty_text_pdf"
    return "unknown"


def _header_is_pdf(path: Path) -> bool:
    with path.open("rb") as file:
        return b"%PDF-" in file.read(1024)


def _eof_marker_found(path: Path) -> bool:
    with path.open("rb") as file:
        file.seek(0, 2)
        size = file.tell()
        file.seek(max(0, size - 4096))
        return b"%%EOF" in file.read()


def _sample_text(reader: PdfReader, sample_pages: int) -> tuple[int, int]:
    pages_with_text = 0
    sampled_text_characters = 0
    for page_index in range(min(sample_pages, len(reader.pages))):
        page = reader.pages[page_index]
        text = (page.extract_text() or "").strip()
        if text:
            pages_with_text += 1
            sampled_text_characters += len(text)
    return pages_with_text, sampled_text_characters


def _replace_diagnosis(result: PdfDiagnosticResult, diagnosis: str) -> PdfDiagnosticResult:
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
        diagnosis=diagnosis,
        warnings=result.warnings,
        errors=result.errors,
    )


def _safe_error(error: Exception) -> str:
    return f"{type(error).__name__}: {_safe_message(str(error))}"


def _split_error(value: str) -> tuple[str, str]:
    if ":" in value:
        error_type, message = value.split(":", maxsplit=1)
        return error_type, _safe_message(message.strip())
    return "DoclingError", _safe_message(value)


def _safe_message(message: str) -> str:
    if len(message) > 500:
        return message[:500] + "..."
    return message
