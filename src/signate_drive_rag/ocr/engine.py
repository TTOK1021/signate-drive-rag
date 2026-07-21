"""EasyOCRをローカルOCRエンジンとして扱うアダプター。"""

from pathlib import Path
from typing import Any, Protocol, cast

from signate_drive_rag.ocr.device import is_torch_cuda_available
from signate_drive_rag.ocr.models import OcrImage, OcrTextRegion
from signate_drive_rag.ocr.ordering import order_ocr_regions


class OcrModelUnavailableError(RuntimeError):
    """OCRモデルがローカルで利用できない場合の例外。"""


class OcrEngineInitializationError(RuntimeError):
    """OCRエンジンの初期化に失敗した場合の例外。"""


class OcrProcessingError(RuntimeError):
    """OCR推論中に失敗した場合の例外。"""


class OcrEngine(Protocol):
    """画像から位置付きテキストを抽出するOCRエンジン。"""

    @property
    def engine_name(self) -> str:
        """OCRエンジンを識別する名前を返す。"""
        ...

    def recognize(self, image: OcrImage) -> tuple[OcrTextRegion, ...]:
        """画像からOCRテキスト領域を抽出する。"""
        ...


class EasyOcrEngine:
    """EasyOCR Readerを1実行内で再利用するOCRエンジン。"""

    def __init__(
        self,
        *,
        languages: tuple[str, ...],
        model_dir: Path,
        gpu: bool = False,
        download_enabled: bool = False,
    ) -> None:
        """通常抽出ではモデル不足時の外部通信を防ぐためdownload_enabledを明示する。"""
        self._languages = languages
        self._model_dir = model_dir
        self._gpu = gpu
        self._download_enabled = download_enabled
        self._reader: Any | None = None

    @property
    def engine_name(self) -> str:
        """OCRエンジンを識別する名前を返す。"""
        return "easyocr"

    def recognize(self, image: OcrImage) -> tuple[OcrTextRegion, ...]:
        """EasyOCR出力を共通の位置付き領域へ変換する。"""
        reader = self._get_reader()
        if self._gpu and not is_torch_cuda_available():
            raise OcrEngineInitializationError(
                "OCRでGPUが指定されましたが、CUDA対応Torchを利用できません。"
            )

        try:
            raw_results = reader.readtext(
                image.image_array,
                detail=1,
                paragraph=False,
            )
        except Exception as error:
            raise OcrProcessingError(_safe_message(str(error))) from error

        regions = tuple(
            _raw_result_to_region(raw_result, image.width, image.height, index)
            for index, raw_result in enumerate(raw_results)
        )
        return order_ocr_regions(regions)

    def _get_reader(self) -> Any:
        if self._reader is not None:
            return self._reader
        if not self._download_enabled and not self._model_dir.exists():
            raise OcrModelUnavailableError(
                f"OCRモデルディレクトリが存在しません: {self._model_dir}"
            )
        if self._gpu and not is_torch_cuda_available():
            raise OcrEngineInitializationError(
                "OCRでGPUが指定されましたが、CUDA対応Torchを利用できません。"
            )

        try:
            import easyocr  # type: ignore[import-untyped]

            self._reader = easyocr.Reader(
                list(self._languages),
                gpu=self._gpu,
                model_storage_directory=str(self._model_dir),
                download_enabled=self._download_enabled,
            )
        except OcrModelUnavailableError:
            raise
        except Exception as error:
            message = _safe_message(str(error))
            if "Missing" in message or "not found" in message or "No such file" in message:
                raise OcrModelUnavailableError(message) from error
            raise OcrEngineInitializationError(message) from error
        return self._reader


def _raw_result_to_region(
    raw_result: object,
    width: int,
    height: int,
    order: int,
) -> OcrTextRegion:
    box, text, confidence = cast(tuple[object, object, object], raw_result)
    polygon = tuple(
        (float(point[0]), float(point[1])) for point in cast(list[tuple[float, float]], box)
    )
    x_values = [point[0] for point in polygon]
    y_values = [point[1] for point in polygon]
    min_x = min(x_values, default=0.0)
    min_y = min(y_values, default=0.0)
    max_x = max(x_values, default=0.0)
    max_y = max(y_values, default=0.0)
    bbox_pixels = (min_x, min_y, max_x, max_y)
    bbox_normalized = (
        _normalize_coordinate(min_x, width),
        _normalize_coordinate(min_y, height),
        _normalize_coordinate(max_x, width),
        _normalize_coordinate(max_y, height),
    )
    return OcrTextRegion(
        text=str(text),
        confidence=float(cast(float, confidence)),
        bbox_pixels=bbox_pixels,
        bbox_normalized=bbox_normalized,
        polygon=polygon,
        order=order,
    )


def _normalize_coordinate(value: float, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, value / denominator))


def _safe_message(message: str) -> str:
    if len(message) > 500:
        return message[:500] + "..."
    return message
