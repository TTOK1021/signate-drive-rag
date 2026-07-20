"""PDFをpypdfでページ単位に抽出するパーサー。"""

import re
from dataclasses import dataclass
from typing import Protocol

from pypdf import PdfReader

from signate_drive_rag.domain import ExtractedDocument, ExtractedUnit, ExtractionIssue, JsonValue
from signate_drive_rag.domain.source_file import SourceFile
from signate_drive_rag.ingestion.parsers.extraction_issue import (
    DOCUMENT_HAS_NO_TEXT,
    IMAGE_DOMINANT_DOCUMENT,
    LOW_TEXT_CONTENT,
    PDF_PAGE_EXTRACTION_FAILED,
    PDF_PAGE_NEEDS_OCR,
    PDF_PARTIALLY_NEEDS_OCR,
    extraction_issue,
)
from signate_drive_rag.ingestion.parsers.pdf_ocr import PdfPageOcrProcessor

MIN_TEXT_CHARACTERS_PER_PAGE = 20
MIN_TEXT_CHARACTERS_PER_DOCUMENT = 50
IMAGE_DOMINANT_PAGE_RATIO = 0.8


class PdfParserError(RuntimeError):
    """PDF文書全体を処理できない場合の例外。"""


@dataclass(frozen=True, slots=True)
class PdfPageExtraction:
    """1ページ分のpypdf抽出結果。"""

    page_number: int
    text: str
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class PdfDocumentExtraction:
    """1PDF全体のpypdf抽出結果。"""

    page_count: int
    pages: tuple[PdfPageExtraction, ...]
    pdf_encrypted: bool
    pdf_metadata_available: bool


class PdfTextExtractor(Protocol):
    """PDFからページ単位のテキストを抽出する処理。"""

    def extract(self, source_file: SourceFile) -> PdfDocumentExtraction:
        """PDFを読み込み、ページごとのテキストまたはページ失敗を返す。"""
        ...


class PypdfTextExtractor:
    """pypdf 6.14.2でPDFページテキストを抽出する。"""

    def extract(self, source_file: SourceFile) -> PdfDocumentExtraction:
        """PdfReaderをstrict=Falseで使い、空パスワード以外は試行しない。"""
        try:
            reader = PdfReader(source_file.path, strict=False)
        except Exception as error:
            raise PdfParserError(f"pdf_unreadable: {_safe_message(str(error))}") from error

        pdf_encrypted = bool(reader.is_encrypted)
        if pdf_encrypted and not bool(reader.decrypt("")):
            raise PdfParserError("pdf_encrypted_unreadable: empty password did not open PDF")

        try:
            page_count = len(reader.pages)
        except Exception as error:
            raise PdfParserError(f"pdf_unreadable: {_safe_message(str(error))}") from error

        pages: list[PdfPageExtraction] = []
        for page_index in range(page_count):
            page_number = page_index + 1
            try:
                text = reader.pages[page_index].extract_text() or ""
                pages.append(PdfPageExtraction(page_number=page_number, text=text))
            except Exception as error:
                pages.append(
                    PdfPageExtraction(
                        page_number=page_number,
                        text="",
                        error_type=type(error).__name__,
                        error_message=_safe_message(str(error)),
                    )
                )

        return PdfDocumentExtraction(
            page_count=page_count,
            pages=tuple(pages),
            pdf_encrypted=pdf_encrypted,
            pdf_metadata_available=reader.metadata is not None,
        )


class PdfParser:
    """PDFをpypdfでページ単位の抽出結果へ変換する。"""

    SUPPORTED_SUFFIXES = frozenset({".pdf"})

    def __init__(
        self,
        extractor: PdfTextExtractor | None = None,
        ocr_processor: PdfPageOcrProcessor | None = None,
        *,
        min_text_characters_per_page: int = MIN_TEXT_CHARACTERS_PER_PAGE,
        min_text_characters_per_document: int = MIN_TEXT_CHARACTERS_PER_DOCUMENT,
        image_dominant_page_ratio: float = IMAGE_DOMINANT_PAGE_RATIO,
    ) -> None:
        """しきい値はパーサー設定として保持し、CLI引数には公開しない。"""
        self._extractor = extractor if extractor is not None else PypdfTextExtractor()
        self._ocr_processor = ocr_processor
        self._min_text_characters_per_page = min_text_characters_per_page
        self._min_text_characters_per_document = min_text_characters_per_document
        self._image_dominant_page_ratio = image_dominant_page_ratio

    @property
    def name(self) -> str:
        """パーサーを識別する名前を返す。"""
        return "pypdf"

    def supports(self, source_file: SourceFile) -> bool:
        """対象ファイルを処理できるか判定する。"""
        return source_file.suffix.lower() in self.SUPPORTED_SUFFIXES

    def parse(self, source_file: SourceFile) -> ExtractedDocument:
        """PDFをページ単位に抽出し、OCR候補issueを記録する。"""
        extraction = self._extractor.extract(source_file)
        units, issues, ocr_target_pages = _units_and_issues(
            extraction,
            min_text_characters_per_page=self._min_text_characters_per_page,
            min_text_characters_per_document=self._min_text_characters_per_document,
            image_dominant_page_ratio=self._image_dominant_page_ratio,
        )
        if self._ocr_processor is not None:
            ocr_units: list[ExtractedUnit] = []
            ocr_issues: list[ExtractionIssue] = []
            for page_number in ocr_target_pages:
                unit, page_issues = self._ocr_processor.recognize_page(
                    source_file,
                    page_number=page_number,
                    page_count=extraction.page_count,
                )
                if unit is not None:
                    ocr_units.append(unit)
                ocr_issues.extend(page_issues)
            units = tuple(sorted([*units, *ocr_units], key=_unit_sort_key))
            issues = tuple([*issues, *ocr_issues])
        return ExtractedDocument(
            source_file=source_file,
            parser_name=self.name,
            units=units,
            issues=issues,
        )


def _units_and_issues(
    extraction: PdfDocumentExtraction,
    *,
    min_text_characters_per_page: int,
    min_text_characters_per_document: int,
    image_dominant_page_ratio: float,
) -> tuple[tuple[ExtractedUnit, ...], tuple[ExtractionIssue, ...], tuple[int, ...]]:
    issues: list[ExtractionIssue] = []
    prepared_pages: list[tuple[PdfPageExtraction, str, int, bool]] = []

    for page in extraction.pages:
        normalized_text = normalize_pdf_text(page.text)
        text_characters = _non_whitespace_characters(normalized_text)
        needs_ocr = text_characters < min_text_characters_per_page
        prepared_pages.append((page, normalized_text, text_characters, needs_ocr))
        if page.error_type is not None:
            issues.append(_page_extraction_failed_issue(page, extraction.page_count))
        if needs_ocr:
            issues.append(
                _page_needs_ocr_issue(page, text_characters, min_text_characters_per_page)
            )

    pages_with_text = sum(
        1 for _page, _text, text_characters, _needs_ocr in prepared_pages if text_characters > 0
    )
    pages_needing_ocr = sum(
        1 for _page, _text, _text_characters, needs_ocr in prepared_pages if needs_ocr
    )
    total_text_characters = sum(
        text_characters for _page, _text, text_characters, _needs_ocr in prepared_pages
    )
    document_metadata = _document_metadata(
        extraction,
        pages_with_text=pages_with_text,
        pages_needing_ocr=pages_needing_ocr,
        text_characters=total_text_characters,
        min_text_characters_per_page=min_text_characters_per_page,
        min_text_characters_per_document=min_text_characters_per_document,
        image_dominant_page_ratio=image_dominant_page_ratio,
    )

    units: list[ExtractedUnit] = []
    for page, normalized_text, text_characters, needs_ocr in prepared_pages:
        if text_characters == 0:
            continue
        units.append(
            _page_unit(
                page,
                normalized_text,
                extraction=extraction,
                text_characters=text_characters,
                needs_ocr=needs_ocr,
                document_metadata=document_metadata,
            )
        )

    issues.extend(
        _document_issues(
            extraction,
            total_text_characters=total_text_characters,
            pages_needing_ocr=pages_needing_ocr,
            min_text_characters_per_document=min_text_characters_per_document,
            image_dominant_page_ratio=image_dominant_page_ratio,
        )
    )
    ocr_target_pages = tuple(
        page.page_number
        for page, _normalized_text, _text_characters, needs_ocr in prepared_pages
        if needs_ocr
    )
    return tuple(units), tuple(issues), ocr_target_pages


def _unit_sort_key(unit: ExtractedUnit) -> tuple[int, str]:
    page_number = unit.metadata.get("page_number")
    normalized_page = page_number if isinstance(page_number, int) else 0
    return normalized_page, unit.locator or ""


def normalize_pdf_text(text: str) -> str:
    """pypdf抽出テキストに対して最小限の正規化だけを行う。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", normalized).strip()


def _page_unit(
    page: PdfPageExtraction,
    text: str,
    *,
    extraction: PdfDocumentExtraction,
    text_characters: int,
    needs_ocr: bool,
    document_metadata: dict[str, JsonValue],
) -> ExtractedUnit:
    return ExtractedUnit(
        unit_type="pdf_page_text",
        text=text,
        locator=f"page:{page.page_number}",
        metadata={
            "page_number": page.page_number,
            "page_count": extraction.page_count,
            "extraction_method": "pypdf",
            "text_characters": text_characters,
            "needs_ocr": needs_ocr,
            "pdf_encrypted": extraction.pdf_encrypted,
            "pdf_metadata_available": extraction.pdf_metadata_available,
            "document_metadata": document_metadata,
        },
    )


def _page_needs_ocr_issue(
    page: PdfPageExtraction,
    text_characters: int,
    threshold: int,
) -> ExtractionIssue:
    return extraction_issue(
        PDF_PAGE_NEEDS_OCR,
        message="ページの抽出文字数がOCR候補しきい値未満です。",
        locator=f"page:{page.page_number}",
        metadata={
            "page_number": page.page_number,
            "text_characters": text_characters,
            "threshold": threshold,
        },
    )


def _page_extraction_failed_issue(
    page: PdfPageExtraction,
    page_count: int,
) -> ExtractionIssue:
    metadata: dict[str, JsonValue] = {
        "page_number": page.page_number,
        "page_count": page_count,
        "error_type": page.error_type,
    }
    return extraction_issue(
        PDF_PAGE_EXTRACTION_FAILED,
        message=f"ページ単位のテキスト抽出に失敗しました: {page.error_type}",
        locator=f"page:{page.page_number}",
        metadata=metadata,
    )


def _document_issues(
    extraction: PdfDocumentExtraction,
    *,
    total_text_characters: int,
    pages_needing_ocr: int,
    min_text_characters_per_document: int,
    image_dominant_page_ratio: float,
) -> tuple[ExtractionIssue, ...]:
    issues: list[ExtractionIssue] = []
    metadata_value: dict[str, JsonValue] = {
        "page_count": extraction.page_count,
        "pages_needing_ocr": pages_needing_ocr,
        "text_characters": total_text_characters,
        "threshold": min_text_characters_per_document,
        "image_dominant_page_ratio": image_dominant_page_ratio,
    }
    if total_text_characters == 0:
        issues.append(
            extraction_issue(
                DOCUMENT_HAS_NO_TEXT,
                message="PDFから非空白本文を抽出できませんでした。",
                metadata=metadata_value,
            )
        )
    elif total_text_characters < min_text_characters_per_document:
        issues.append(
            extraction_issue(
                LOW_TEXT_CONTENT,
                message="PDF全体の抽出文字数がしきい値未満です。",
                metadata=metadata_value,
            )
        )
    if (
        extraction.page_count > 0
        and pages_needing_ocr / extraction.page_count >= image_dominant_page_ratio
    ):
        issues.append(
            extraction_issue(
                IMAGE_DOMINANT_DOCUMENT,
                message="OCR候補ページの比率が高いPDFです。",
                metadata=metadata_value,
            )
        )
    if 0 < pages_needing_ocr < extraction.page_count:
        issues.append(
            extraction_issue(
                PDF_PARTIALLY_NEEDS_OCR,
                message="一部ページがOCR候補です。",
                metadata=metadata_value,
            )
        )
    return tuple(issues)


def _document_metadata(
    extraction: PdfDocumentExtraction,
    *,
    pages_with_text: int,
    pages_needing_ocr: int,
    text_characters: int,
    min_text_characters_per_page: int,
    min_text_characters_per_document: int,
    image_dominant_page_ratio: float,
) -> dict[str, JsonValue]:
    return {
        "page_count": extraction.page_count,
        "pages_with_text": pages_with_text,
        "pages_needing_ocr": pages_needing_ocr,
        "text_characters": text_characters,
        "pdf_encrypted": extraction.pdf_encrypted,
        "pdf_metadata_available": extraction.pdf_metadata_available,
        "extraction_method": "pypdf",
        "min_text_characters_per_page": min_text_characters_per_page,
        "min_text_characters_per_document": min_text_characters_per_document,
        "image_dominant_page_ratio": image_dominant_page_ratio,
    }


def _non_whitespace_characters(text: str) -> int:
    return sum(1 for character in text if not character.isspace())


def _safe_message(message: str) -> str:
    if len(message) > 500:
        return message[:500] + "..."
    return message
