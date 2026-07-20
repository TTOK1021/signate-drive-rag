"""PDFページをOCR用画像へ変換する処理。"""

from pathlib import Path
from typing import Any, Protocol

import numpy as np

from signate_drive_rag.ocr.models import OcrImage


class PdfPageRenderError(RuntimeError):
    """PDFページの画像化に失敗した場合の例外。"""


class PdfPageRenderer(Protocol):
    """PDFページをOCR用の画像へ変換するレンダラー。"""

    @property
    def renderer_name(self) -> str:
        """レンダラーを識別する名前を返す。"""
        ...

    def render_page(
        self,
        source_path: Path,
        *,
        page_number: int,
        dpi: int,
        max_image_pixels: int,
    ) -> OcrImage:
        """指定ページをOCR画像へ変換する。"""
        ...


class Pypdfium2PageRenderer:
    """pypdfium2でPDFページをメモリ上のRGB画像へレンダリングする。"""

    @property
    def renderer_name(self) -> str:
        """レンダラーを識別する名前を返す。"""
        return "pypdfium2"

    def render_page(
        self,
        source_path: Path,
        *,
        page_number: int,
        dpi: int,
        max_image_pixels: int,
    ) -> OcrImage:
        """PDFページ画像は永続化せず、OCRへ渡す配列だけを作る。"""
        pdf_document: Any | None = None
        page: Any | None = None
        bitmap: Any | None = None
        try:
            import pypdfium2 as pdfium  # type: ignore[import-untyped]

            pdf_document = pdfium.PdfDocument(str(source_path))
            page = pdf_document[page_number - 1]
            bitmap = page.render(scale=dpi / 72)
            pil_image = bitmap.to_pil().convert("RGB")
            width, height = pil_image.size
            if width <= 0 or height <= 0:
                raise PdfPageRenderError(
                    f"PDFページ画像サイズが不正です: page={page_number}, "
                    f"width={width}, height={height}"
                )
            pixels = width * height
            if pixels > max_image_pixels:
                raise PdfPageRenderError(
                    f"PDFページ画像ピクセル数が上限を超えています: page={page_number}, "
                    f"pixels={pixels}, max={max_image_pixels}"
                )
            return OcrImage(
                image_array=np.asarray(pil_image),
                width=width,
                height=height,
                source_kind="pdf_page",
                page_number=page_number,
                image_index=None,
                image_mode="RGB",
            )
        except PdfPageRenderError:
            raise
        except Exception as error:
            raise PdfPageRenderError(_safe_message(str(error))) from error
        finally:
            for resource in (bitmap, page, pdf_document):
                close = getattr(resource, "close", None)
                if close is not None:
                    close()


def _safe_message(message: str) -> str:
    if len(message) > 500:
        return message[:500] + "..."
    return message
