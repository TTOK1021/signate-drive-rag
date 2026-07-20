"""OCRで扱う画像と認識領域の共通モデル。"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class OcrTextRegion:
    """OCRで認識された1つのテキスト領域。"""

    text: str
    confidence: float
    bbox_pixels: tuple[float, float, float, float]
    bbox_normalized: tuple[float, float, float, float]
    polygon: tuple[tuple[float, float], ...]
    order: int


@dataclass(frozen=True, slots=True)
class OcrImage:
    """OCR対象画像と原本上の位置を表す。"""

    image_array: object
    width: int
    height: int
    source_kind: str
    page_number: int | None
    image_index: int | None
    image_mode: str


@dataclass(frozen=True, slots=True)
class OcrOptions:
    """OCR処理の再現性に関わる設定。"""

    languages: tuple[str, ...] = ("ja", "en")
    gpu: bool = False
    model_dir: Path = Path("artifacts") / "models" / "easyocr"
    pdf_render_dpi: int = 200
    min_region_confidence: float = 0.20
    low_confidence_threshold: float = 0.50
    min_text_characters_per_image: int = 2
    max_image_pixels: int = 40_000_000
    enable_pdf_ocr: bool = True
    enable_png_ocr: bool = True
    ocr_only_pdf_pages_needing_ocr: bool = True
    max_regions_in_metadata: int = 500

    @property
    def language_list(self) -> list[str]:
        """EasyOCRへ渡すため、設定値を可変リストへ閉じ込めて返す。"""
        return list(self.languages)
