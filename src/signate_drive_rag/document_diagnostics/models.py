"""文書入力とローカル変換環境の診断モデル。"""

from dataclasses import dataclass

from signate_drive_rag.domain.extracted_document import JsonValue

OFFICE_TEMPORARY_FILE_REASON = "office_temporary_file"


@dataclass(frozen=True, slots=True)
class IgnoredFile:
    """探索時に診断・抽出対象から除外したファイル。"""

    relative_path: str
    suffix: str
    size_bytes: int
    reason: str


@dataclass(frozen=True, slots=True)
class PdfDiagnosticResult:
    """PDF入力とローカルPDF環境の診断結果。"""

    relative_path: str
    size_bytes: int
    sha256: str
    header_is_pdf: bool
    eof_marker_found: bool
    pypdf_readable: bool
    encrypted: bool | None
    decryption_attempted: bool
    decryption_succeeded: bool | None
    page_count: int | None
    pages_with_text: int
    sampled_text_characters: int
    metadata_available: bool
    docling_attempted: bool
    docling_status: str | None
    docling_error_type: str | None
    docling_error_message: str | None
    diagnosis: str
    warnings: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OcrEnvironmentDiagnostic:
    """ローカルOCRエンジンの利用可否を表す。"""

    engine: str
    executable_found: bool
    executable_path: str | None
    version: str | None
    available_languages: tuple[str, ...]
    required_languages: tuple[str, ...]
    missing_languages: tuple[str, ...]
    usable: bool
    diagnosis: str
    warnings: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DocumentDiagnosticManifest:
    """文書診断の実行条件。"""

    formats: tuple[str, ...]
    sample_pages: int
    try_docling: bool
    diagnose_ocr: bool
    remote_services_enabled: bool
    dependencies: dict[str, str]


@dataclass(frozen=True, slots=True)
class DocumentDiagnosticSummary:
    """文書診断の集計情報。"""

    candidate_files: int
    diagnosed_files: int
    ignored_files: int
    ignored_by_reason: dict[str, int]
    header_is_pdf: int
    header_is_not_pdf: int
    pypdf_readable: int
    pypdf_unreadable: int
    encrypted: int
    encrypted_unreadable: int
    readable_text_pdf: int
    readable_image_or_empty_text_pdf: int
    docling_attempted: int
    docling_success: int
    docling_partial_success: int
    docling_failed: int
    diagnosis_counts: dict[str, int]
    ocr_usable: bool | None
    ocr_diagnosis: str | None


@dataclass(frozen=True, slots=True)
class DocumentDiagnosticReport:
    """文書診断の成果物全体。"""

    manifest: DocumentDiagnosticManifest
    pdf_results: tuple[PdfDiagnosticResult, ...]
    ocr_environment: OcrEnvironmentDiagnostic | None
    ignored_files: tuple[IgnoredFile, ...]
    summary: DocumentDiagnosticSummary


def ocr_environment_to_json(
    diagnostic: OcrEnvironmentDiagnostic | None,
) -> dict[str, JsonValue] | None:
    """OCR診断結果をJSON互換辞書へ変換する。"""
    if diagnostic is None:
        return None
    return {
        "engine": diagnostic.engine,
        "executable_found": diagnostic.executable_found,
        "executable_path": diagnostic.executable_path,
        "version": diagnostic.version,
        "available_languages": list(diagnostic.available_languages),
        "required_languages": list(diagnostic.required_languages),
        "missing_languages": list(diagnostic.missing_languages),
        "usable": diagnostic.usable,
        "diagnosis": diagnostic.diagnosis,
        "warnings": list(diagnostic.warnings),
        "errors": list(diagnostic.errors),
    }
