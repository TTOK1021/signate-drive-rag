"""PNG画像全体をローカルOCRで抽出するパーサー。"""

from typing import ClassVar

from signate_drive_rag.domain import ExtractedDocument, ExtractionIssue
from signate_drive_rag.domain.source_file import SourceFile
from signate_drive_rag.ingestion.parsers.extraction_issue import (
    IMAGE_INVALID_DIMENSIONS,
    IMAGE_MODE_CONVERSION_FAILED,
    IMAGE_PIXEL_LIMIT_EXCEEDED,
    IMAGE_UNREADABLE,
    OCR_ENGINE_INITIALIZATION_FAILED,
    OCR_MODEL_UNAVAILABLE,
    OCR_PROCESSING_FAILED,
    extraction_issue,
)
from signate_drive_rag.ocr.engine import (
    OcrEngine,
    OcrEngineInitializationError,
    OcrModelUnavailableError,
    OcrProcessingError,
)
from signate_drive_rag.ocr.image_loader import OcrImageLoadError, load_png_ocr_image
from signate_drive_rag.ocr.models import OcrOptions
from signate_drive_rag.ocr.unit_builder import build_ocr_unit_result


class PngOcrParser:
    """PNG画像を1画像1unitとしてOCR抽出する。"""

    SUPPORTED_SUFFIXES: ClassVar[frozenset[str]] = frozenset({".png"})

    def __init__(self, *, ocr_engine: OcrEngine, options: OcrOptions) -> None:
        """OCRエンジンを外から受け取り、通常テストでは偽実装へ差し替える。"""
        self._ocr_engine = ocr_engine
        self._options = options

    @property
    def name(self) -> str:
        """パーサーを識別する名前を返す。"""
        return "easyocr_png"

    def supports(self, source_file: SourceFile) -> bool:
        """PNGだけを処理対象にする。"""
        return source_file.suffix.lower() in self.SUPPORTED_SUFFIXES

    def parse(self, source_file: SourceFile) -> ExtractedDocument:
        """画像全体をOCRし、認識できない場合もissueとして記録する。"""
        try:
            image = load_png_ocr_image(
                source_file.path,
                max_image_pixels=self._options.max_image_pixels,
            )
            regions = self._ocr_engine.recognize(image)
        except OcrImageLoadError as error:
            return _issue_document(
                source_file,
                self.name,
                _image_issue(error.issue_type, str(error)),
            )
        except OcrModelUnavailableError as error:
            return _issue_document(
                source_file,
                self.name,
                _ocr_issue(OCR_MODEL_UNAVAILABLE, str(error)),
            )
        except OcrEngineInitializationError as error:
            return _issue_document(
                source_file,
                self.name,
                _ocr_issue(OCR_ENGINE_INITIALIZATION_FAILED, str(error)),
            )
        except OcrProcessingError as error:
            return _issue_document(
                source_file,
                self.name,
                _ocr_issue(OCR_PROCESSING_FAILED, str(error)),
            )

        unit_result = build_ocr_unit_result(
            image=image,
            regions=regions,
            options=self._options,
            unit_type="image_ocr_text",
            locator="image:1",
            metadata={
                "ocr_engine": self._ocr_engine.engine_name,
                "image_index": 1,
            },
        )
        units = () if unit_result.unit is None else (unit_result.unit,)
        return ExtractedDocument(
            source_file=source_file,
            parser_name=self.name,
            units=units,
            issues=unit_result.issues,
        )


def _issue_document(
    source_file: SourceFile,
    parser_name: str,
    issue: ExtractionIssue,
) -> ExtractedDocument:
    return ExtractedDocument(
        source_file=source_file,
        parser_name=parser_name,
        units=(),
        issues=(issue,),
    )


def _image_issue(issue_type: str, message: str) -> ExtractionIssue:
    known_issue_type = issue_type
    if known_issue_type not in {
        IMAGE_UNREADABLE,
        IMAGE_INVALID_DIMENSIONS,
        IMAGE_PIXEL_LIMIT_EXCEEDED,
        IMAGE_MODE_CONVERSION_FAILED,
    }:
        known_issue_type = IMAGE_UNREADABLE
    return extraction_issue(
        known_issue_type,
        message=message,
        locator="image:1",
    )


def _ocr_issue(issue_type: str, message: str) -> ExtractionIssue:
    return extraction_issue(
        issue_type,
        message=message,
        locator="image:1",
    )
