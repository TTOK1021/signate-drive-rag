from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from signate_drive_rag.ocr.device import resolve_ocr_gpu_flag
from signate_drive_rag.ocr.engine import EasyOcrEngine, OcrModelUnavailableError
from signate_drive_rag.ocr.image_loader import load_png_ocr_image
from signate_drive_rag.ocr.models import OcrOptions


@pytest.mark.ocr_real
def test_easyocr_model_recognizes_generated_english_image(tmp_path: Path) -> None:
    """実モデルがダウンロードなしで初期化され、画像から文字領域を返すことを確認する。"""
    model_dir = Path(os.environ.get("OCR_MODEL_DIR", "artifacts/models/easyocr"))
    if not (model_dir / "manifest.json").exists():
        pytest.skip("OCRモデルが準備されていないため実モデルスモークをスキップします。")

    image_path = tmp_path / "ocr_smoke.png"
    image = Image.new("RGB", (720, 220), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=64)
    draw.text((48, 70), "OCR TEST 123", fill="black", font=font)
    image.save(image_path)

    ocr_options = OcrOptions(model_dir=model_dir)
    ocr_image = load_png_ocr_image(
        image_path,
        max_image_pixels=ocr_options.max_image_pixels,
    )
    engine = EasyOcrEngine(
        languages=("ja", "en"),
        model_dir=model_dir,
        gpu=resolve_ocr_gpu_flag("auto"),
        download_enabled=False,
    )

    try:
        regions = engine.recognize(ocr_image)
    except OcrModelUnavailableError as error:
        pytest.skip(f"OCRモデルが不足しているため実モデルスモークをスキップします: {error}")

    assert regions
    assert any(region.text.strip() for region in regions)
