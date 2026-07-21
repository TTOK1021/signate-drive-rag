"""PNG OCRパーサーの単体テスト。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from signate_drive_rag.domain import SourceFile
from signate_drive_rag.ingestion.parsers.png_ocr_parser import PngOcrParser
from signate_drive_rag.ocr.models import OcrImage, OcrOptions, OcrTextRegion


def make_source_file(path: Path) -> SourceFile:
    """テスト用SourceFileを作成する。"""
    return SourceFile(
        path=path,
        relative_path=Path("画像") / path.name,
        name=path.name,
        suffix=path.suffix.lower(),
        mime_type="image/png",
        size_bytes=path.stat().st_size,
        modified_at=datetime(2026, 7, 20, tzinfo=UTC),
    )


def write_png(path: Path, *, size: tuple[int, int] = (20, 10)) -> None:
    """小さなテスト用PNGを作成する。"""
    Image.new("RGB", size, color="white").save(path, format="PNG")


def region(text: str, confidence: float = 0.9) -> OcrTextRegion:
    """テスト用OCR領域を作成する。"""
    return OcrTextRegion(
        text=text,
        confidence=confidence,
        bbox_pixels=(1.0, 2.0, 10.0, 8.0),
        bbox_normalized=(0.05, 0.2, 0.5, 0.8),
        polygon=((1.0, 2.0), (10.0, 2.0), (10.0, 8.0), (1.0, 8.0)),
        order=0,
    )


@dataclass(slots=True)
class FakeOcrEngine:
    """実OCRを行わないテスト用エンジン。"""

    regions: tuple[OcrTextRegion, ...]
    seen_image: OcrImage | None = None

    @property
    def engine_name(self) -> str:
        """エンジン名を返す。"""
        return "fake_ocr"

    def recognize(self, image: OcrImage) -> tuple[OcrTextRegion, ...]:
        """固定OCR結果を返す。"""
        self.seen_image = image
        return self.regions


def test_png_ocr_parser_extracts_image_ocr_text_unit(tmp_path: Path) -> None:
    """PNGを読み込み、image_ocr_text unitとOCR metadataを生成する。"""
    png_path = tmp_path / "日本語.png"
    write_png(png_path)
    engine = FakeOcrEngine((region("契約金額 100"),))

    document = PngOcrParser(
        ocr_engine=engine,
        options=OcrOptions(model_dir=tmp_path / "models"),
    ).parse(make_source_file(png_path))

    assert document.parser_name == "easyocr_png"
    assert document.units[0].unit_type == "image_ocr_text"
    assert document.units[0].locator == "image:1"
    assert "契約金額 100" in document.units[0].text
    assert document.units[0].metadata["image_width"] == 20
    assert document.units[0].metadata["ocr_engine"] == "fake_ocr"
    assert engine.seen_image is not None
    assert engine.seen_image.image_mode == "RGB"


def test_png_ocr_parser_records_no_text_issue_without_unit(tmp_path: Path) -> None:
    """OCRで本文が得られない場合はunitを作らずissueを記録する。"""
    png_path = tmp_path / "empty.png"
    write_png(png_path)

    document = PngOcrParser(
        ocr_engine=FakeOcrEngine(()),
        options=OcrOptions(model_dir=tmp_path / "models"),
    ).parse(make_source_file(png_path))

    assert document.units == ()
    assert [issue.issue_type for issue in document.issues] == ["ocr_no_text"]


def test_png_ocr_parser_records_image_load_issue_for_broken_png(tmp_path: Path) -> None:
    """壊れたPNGは例外を外へ漏らさず、image_unreadable issueとして記録する。"""
    png_path = tmp_path / "broken.png"
    png_path.write_bytes(b"not png")

    document = PngOcrParser(
        ocr_engine=FakeOcrEngine(()),
        options=OcrOptions(model_dir=tmp_path / "models"),
    ).parse(make_source_file(png_path))

    assert document.units == ()
    assert document.issues[0].issue_type == "image_unreadable"


def test_png_ocr_parser_records_pixel_limit_issue(tmp_path: Path) -> None:
    """画像ピクセル数が上限を超える場合はOCRせずissueを記録する。"""
    png_path = tmp_path / "large.png"
    write_png(png_path, size=(4, 4))

    document = PngOcrParser(
        ocr_engine=FakeOcrEngine((region("unused"),)),
        options=OcrOptions(model_dir=tmp_path / "models", max_image_pixels=1),
    ).parse(make_source_file(png_path))

    assert document.units == ()
    assert document.issues[0].issue_type == "image_pixel_limit_exceeded"
