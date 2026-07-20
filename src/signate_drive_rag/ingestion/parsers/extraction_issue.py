"""抽出時issueを作成する共通処理。"""

from signate_drive_rag.domain import ExtractionIssue, JsonValue

DOCUMENT_HAS_NO_TEXT = "document_has_no_text"
LOW_TEXT_CONTENT = "low_text_content"
IMAGE_DOMINANT_DOCUMENT = "image_dominant_document"
PDF_PAGE_NEEDS_OCR = "pdf_page_needs_ocr"
PDF_PARTIALLY_NEEDS_OCR = "pdf_partially_needs_ocr"
PDF_PAGE_EXTRACTION_FAILED = "pdf_page_extraction_failed"
PDF_ENCRYPTED_UNREADABLE = "pdf_encrypted_unreadable"
PDF_UNREADABLE = "pdf_unreadable"
XLSX_NOT_OOXML = "xlsx_not_ooxml"
XLSX_ZIP_UNREADABLE = "xlsx_zip_unreadable"
XLSX_UNCOMPRESSED_SIZE_LIMIT_EXCEEDED = "xlsx_uncompressed_size_limit_exceeded"
XLSX_COMPRESSION_RATIO_LIMIT_EXCEEDED = "xlsx_compression_ratio_limit_exceeded"
XLSX_UNREADABLE = "xlsx_unreadable"
XLSX_SHEET_HAS_NO_CELLS = "xlsx_sheet_has_no_cells"
XLSX_HIDDEN_SHEET = "xlsx_hidden_sheet"
XLSX_METADATA_LIMITED = "xlsx_metadata_limited"
XLSX_FORMULA_CACHED_VALUE_MISSING = "xlsx_formula_cached_value_missing"
XLSX_LARGE_SHEET = "xlsx_large_sheet"
XLSX_VERY_WIDE_SHEET = "xlsx_very_wide_sheet"
XLSX_LARGE_CELL_VALUE = "xlsx_large_cell_value"

ISSUE_SEVERITY_BY_TYPE = {
    DOCUMENT_HAS_NO_TEXT: "warning",
    LOW_TEXT_CONTENT: "info",
    IMAGE_DOMINANT_DOCUMENT: "info",
    PDF_PAGE_NEEDS_OCR: "info",
    PDF_PARTIALLY_NEEDS_OCR: "info",
    PDF_PAGE_EXTRACTION_FAILED: "info",
    PDF_ENCRYPTED_UNREADABLE: "error",
    PDF_UNREADABLE: "error",
    XLSX_NOT_OOXML: "error",
    XLSX_ZIP_UNREADABLE: "error",
    XLSX_UNCOMPRESSED_SIZE_LIMIT_EXCEEDED: "error",
    XLSX_COMPRESSION_RATIO_LIMIT_EXCEEDED: "error",
    XLSX_UNREADABLE: "error",
    XLSX_SHEET_HAS_NO_CELLS: "info",
    XLSX_HIDDEN_SHEET: "info",
    XLSX_METADATA_LIMITED: "info",
    XLSX_FORMULA_CACHED_VALUE_MISSING: "info",
    XLSX_LARGE_SHEET: "info",
    XLSX_VERY_WIDE_SHEET: "info",
    XLSX_LARGE_CELL_VALUE: "info",
}


def extraction_issue(
    issue_type: str,
    *,
    message: str,
    locator: str | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> ExtractionIssue:
    """issue_typeからseverityを一元的に決めて抽出issueを作る。"""
    return ExtractionIssue(
        issue_type=issue_type,
        severity=ISSUE_SEVERITY_BY_TYPE[issue_type],
        message=message,
        locator=locator,
        metadata={} if metadata is None else metadata,
    )
