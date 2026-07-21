"""ローカルOCR処理の共通基盤。"""

from signate_drive_rag.ocr.device import is_torch_cuda_available, resolve_ocr_gpu_flag
from signate_drive_rag.ocr.engine import (
    EasyOcrEngine,
    OcrEngine,
    OcrEngineInitializationError,
    OcrModelUnavailableError,
    OcrProcessingError,
)
from signate_drive_rag.ocr.image_loader import OcrImageLoadError, load_png_ocr_image
from signate_drive_rag.ocr.models import OcrImage, OcrOptions, OcrTextRegion
from signate_drive_rag.ocr.pdf_renderer import (
    PdfPageRenderer,
    PdfPageRenderError,
    Pypdfium2PageRenderer,
)
from signate_drive_rag.ocr.prepare import prepare_easyocr_models
from signate_drive_rag.ocr.unit_builder import build_ocr_unit_result

__all__ = [
    "EasyOcrEngine",
    "OcrEngine",
    "OcrEngineInitializationError",
    "OcrImage",
    "OcrImageLoadError",
    "OcrModelUnavailableError",
    "OcrOptions",
    "OcrProcessingError",
    "OcrTextRegion",
    "PdfPageRenderError",
    "PdfPageRenderer",
    "Pypdfium2PageRenderer",
    "build_ocr_unit_result",
    "is_torch_cuda_available",
    "load_png_ocr_image",
    "prepare_easyocr_models",
    "resolve_ocr_gpu_flag",
]
