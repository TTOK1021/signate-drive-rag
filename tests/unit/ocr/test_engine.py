"""OCRエンジン初期化のテスト。"""

from signate_drive_rag.ocr.engine import EasyOcrEngine, OcrEngineInitializationError
from signate_drive_rag.ocr.models import OcrImage


def test_easyocr_engine_fails_fast_when_gpu_requested_without_cuda(
    tmp_path,
    monkeypatch,
) -> None:
    """GPU明示時にCUDA対応Torchが無い場合は、Reader初期化前に明確な例外にする。"""
    monkeypatch.setattr("signate_drive_rag.ocr.engine.is_torch_cuda_available", lambda: False)
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    engine = EasyOcrEngine(
        languages=("ja", "en"),
        model_dir=model_dir,
        gpu=True,
        download_enabled=False,
    )

    try:
        engine.recognize(
            OcrImage(
                image_array=object(),
                width=1,
                height=1,
                source_kind="image",
                page_number=None,
                image_index=1,
                image_mode="RGB",
            )
        )
    except OcrEngineInitializationError as error:
        assert "CUDA対応Torch" in str(error)
    else:
        raise AssertionError("OcrEngineInitializationErrorが発生するべきです。")
