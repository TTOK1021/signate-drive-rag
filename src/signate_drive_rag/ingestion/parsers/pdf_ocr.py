"""PDFページ単位のOCRを既存PDF抽出へ追加する処理。"""

from signate_drive_rag.domain import ExtractedUnit, ExtractionIssue, SourceFile
from signate_drive_rag.ingestion.parsers.extraction_issue import (
    OCR_ENGINE_INITIALIZATION_FAILED,
    OCR_MODEL_UNAVAILABLE,
    OCR_PROCESSING_FAILED,
    PDF_PAGE_OCR_APPLIED,
    PDF_PAGE_OCR_FAILED,
    PDF_PAGE_OCR_LOW_CONFIDENCE,
    PDF_PAGE_OCR_NO_TEXT,
    extraction_issue,
)
from signate_drive_rag.ocr.engine import (
    OcrEngine,
    OcrEngineInitializationError,
    OcrModelUnavailableError,
    OcrProcessingError,
)
from signate_drive_rag.ocr.models import OcrOptions
from signate_drive_rag.ocr.pdf_renderer import PdfPageRenderer, PdfPageRenderError
from signate_drive_rag.ocr.unit_builder import build_ocr_unit_result


class PdfPageOcrProcessor:
    """OCR候補PDFページだけを画像化してOCR unitへ変換する。"""

    def __init__(
        self,
        *,
        ocr_engine: OcrEngine,
        renderer: PdfPageRenderer,
        options: OcrOptions,
    ) -> None:
        """OCRエンジンとPDFレンダラーを差し替え可能にする。"""
        self._ocr_engine = ocr_engine
        self._renderer = renderer
        self._options = options

    def recognize_page(
        self,
        source_file: SourceFile,
        *,
        page_number: int,
        page_count: int,
    ) -> tuple[ExtractedUnit | None, tuple[ExtractionIssue, ...]]:
        """1ページのOCRに失敗してもPDF文書全体は失敗させない。"""
        locator = f"page:{page_number}/ocr"
        try:
            image = self._renderer.render_page(
                source_file.path,
                page_number=page_number,
                dpi=self._options.pdf_render_dpi,
                max_image_pixels=self._options.max_image_pixels,
            )
            regions = self._ocr_engine.recognize(image)
        except OcrModelUnavailableError as error:
            return None, (_pdf_ocr_failed_issue(OCR_MODEL_UNAVAILABLE, locator, str(error)),)
        except OcrEngineInitializationError as error:
            return None, (
                _pdf_ocr_failed_issue(OCR_ENGINE_INITIALIZATION_FAILED, locator, str(error)),
            )
        except (OcrProcessingError, PdfPageRenderError) as error:
            return None, (_pdf_ocr_failed_issue(OCR_PROCESSING_FAILED, locator, str(error)),)

        unit_result = build_ocr_unit_result(
            image=image,
            regions=regions,
            options=self._options,
            unit_type="pdf_page_ocr",
            locator=locator,
            metadata={
                "page_number": page_number,
                "page_count": page_count,
                "render_dpi": self._options.pdf_render_dpi,
                "render_width": image.width,
                "render_height": image.height,
                "ocr_engine": self._ocr_engine.engine_name,
                "pdf_renderer": self._renderer.renderer_name,
                "extraction_method": "pypdfium2+easyocr",
            },
        )
        issues: list[ExtractionIssue] = []
        if unit_result.unit is None:
            issues.append(
                extraction_issue(
                    PDF_PAGE_OCR_NO_TEXT,
                    message="PDFページOCRで検索に使える文字列を抽出できませんでした。",
                    locator=locator,
                    metadata={
                        "page_number": page_number,
                        "recognized_region_count": unit_result.recognized_region_count,
                        "included_region_count": unit_result.included_region_count,
                    },
                )
            )
            return None, tuple([*issues, *unit_result.issues])

        issues.append(
            extraction_issue(
                PDF_PAGE_OCR_APPLIED,
                message="OCR候補PDFページへOCRを適用しました。",
                locator=locator,
                metadata={
                    "page_number": page_number,
                    "ocr_text_characters": unit_result.ocr_text_characters,
                    "mean_confidence": unit_result.mean_confidence,
                },
            )
        )
        if unit_result.mean_confidence is not None and (
            unit_result.mean_confidence < self._options.low_confidence_threshold
        ):
            issues.append(
                extraction_issue(
                    PDF_PAGE_OCR_LOW_CONFIDENCE,
                    message="PDFページOCRの平均信頼度がしきい値未満です。",
                    locator=locator,
                    metadata={
                        "page_number": page_number,
                        "mean_confidence": unit_result.mean_confidence,
                        "threshold": self._options.low_confidence_threshold,
                    },
                )
            )
        return unit_result.unit, tuple([*issues, *unit_result.issues])


def _pdf_ocr_failed_issue(
    cause_issue_type: str,
    locator: str,
    message: str,
) -> ExtractionIssue:
    return extraction_issue(
        PDF_PAGE_OCR_FAILED,
        message=f"PDFページOCRに失敗しました: {message}",
        locator=locator,
        metadata={
            "cause_issue_type": cause_issue_type,
        },
    )
