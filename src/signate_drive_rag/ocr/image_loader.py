"""OCR対象画像を安全にメモリ上へ読み込む処理。"""

from pathlib import Path
from warnings import catch_warnings, simplefilter

import numpy as np
from PIL import Image, UnidentifiedImageError

from signate_drive_rag.ocr.models import OcrImage


class OcrImageLoadError(RuntimeError):
    """OCR対象画像を安全に読み込めない場合の例外。"""

    def __init__(self, issue_type: str, message: str) -> None:
        """issue_typeを成果物へ引き継げるように保持する。"""
        super().__init__(message)
        self.issue_type = issue_type


def load_png_ocr_image(path: Path, *, max_image_pixels: int) -> OcrImage:
    """PNGをRGB配列へ変換し、原本ファイルは変更しない。"""
    try:
        with catch_warnings():
            simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format != "PNG":
                    raise OcrImageLoadError("image_unreadable", "PNGとして読み込めません。")
                width, height = image.size
                _validate_dimensions(width, height, max_image_pixels=max_image_pixels)
                try:
                    converted = image.convert("RGB")
                except Exception as error:
                    raise OcrImageLoadError(
                        "image_mode_conversion_failed",
                        f"RGB変換に失敗しました: {_safe_message(str(error))}",
                    ) from error
                image_array = np.asarray(converted)
    except OcrImageLoadError:
        raise
    except (UnidentifiedImageError, OSError) as error:
        raise OcrImageLoadError(
            "image_unreadable",
            f"画像を読み込めません: {_safe_message(str(error))}",
        ) from error

    return OcrImage(
        image_array=image_array,
        width=width,
        height=height,
        source_kind="png",
        page_number=None,
        image_index=1,
        image_mode="RGB",
    )


def _validate_dimensions(width: int, height: int, *, max_image_pixels: int) -> None:
    if width <= 0 or height <= 0:
        raise OcrImageLoadError(
            "image_invalid_dimensions",
            f"画像サイズが不正です: width={width}, height={height}",
        )
    pixels = width * height
    if pixels > max_image_pixels:
        raise OcrImageLoadError(
            "image_pixel_limit_exceeded",
            f"画像ピクセル数が上限を超えています: pixels={pixels}, max={max_image_pixels}",
        )


def _safe_message(message: str) -> str:
    if len(message) > 500:
        return message[:500] + "..."
    return message
