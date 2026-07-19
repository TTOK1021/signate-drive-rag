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

ISSUE_SEVERITY_BY_TYPE = {
    DOCUMENT_HAS_NO_TEXT: "warning",
    LOW_TEXT_CONTENT: "info",
    IMAGE_DOMINANT_DOCUMENT: "info",
    PDF_PAGE_NEEDS_OCR: "info",
    PDF_PARTIALLY_NEEDS_OCR: "info",
    PDF_PAGE_EXTRACTION_FAILED: "info",
    PDF_ENCRYPTED_UNREADABLE: "error",
    PDF_UNREADABLE: "error",
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
