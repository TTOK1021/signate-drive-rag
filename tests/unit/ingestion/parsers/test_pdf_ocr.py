"""PDFページOCR連携の単体テスト。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from signate_drive_rag.domain import SourceFile
from signate_drive_rag.ingestion.parsers.pdf_ocr import PdfPageOcrProcessor
from signate_drive_rag.ingestion.parsers.pdf_parser import (
    PdfDocumentExtraction,
    PdfPageExtraction,
    PdfParser,
)
from signate_drive_rag.ocr import OcrImage, OcrOptions, OcrTextRegion, PdfPageRenderError


def make_source_file(path: Path) -> SourceFile:
    """テスト用SourceFileを作成する。"""
    path.write_bytes(b"%PDF")
    return SourceFile(
        path=path,
        relative_path=Path("文書") / path.name,
        name=path.name,
        suffix=".pdf",
        mime_type="application/pdf",
        size_bytes=path.stat().st_size,
        modified_at=datetime(2026, 7, 20, tzinfo=UTC),
    )


def ocr_image(page_number: int) -> OcrImage:
    """テスト用PDFページ画像を作成する。"""
    return OcrImage(
        image_array=object(),
        width=100,
        height=100,
        source_kind="pdf_page",
        page_number=page_number,
        image_index=None,
        image_mode="RGB",
    )


def region(text: str, confidence: float = 0.9) -> OcrTextRegion:
    """テスト用OCR領域を作成する。"""
    return OcrTextRegion(
        text=text,
        confidence=confidence,
        bbox_pixels=(0.0, 0.0, 10.0, 10.0),
        bbox_normalized=(0.0, 0.0, 0.1, 0.1),
        polygon=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        order=0,
    )


@dataclass(slots=True)
class FakeExtractor:
    """固定のpypdf抽出結果を返す。"""

    extraction: PdfDocumentExtraction

    def extract(self, source_file: SourceFile) -> PdfDocumentExtraction:
        """固定PDF抽出結果を返す。"""
        return self.extraction


@dataclass(slots=True)
class FakeRenderer:
    """PDFページ画像化を差し替える。"""

    fail: bool = False

    @property
    def renderer_name(self) -> str:
        """レンダラー名を返す。"""
        return "fake_pdf_renderer"

    def render_page(
        self,
        source_path: Path,
        *,
        page_number: int,
        dpi: int,
        max_image_pixels: int,
    ) -> OcrImage:
        """固定画像を返す。"""
        if self.fail:
            raise PdfPageRenderError("render failed")
        return ocr_image(page_number)


@dataclass(slots=True)
class FakeEngine:
    """固定OCR結果を返す。"""

    regions: tuple[OcrTextRegion, ...]

    @property
    def engine_name(self) -> str:
        """エンジン名を返す。"""
        return "fake_ocr"

    def recognize(self, image: OcrImage) -> tuple[OcrTextRegion, ...]:
        """固定OCR結果を返す。"""
        return self.regions


def test_pdf_parser_adds_ocr_unit_only_for_pages_needing_ocr(tmp_path: Path) -> None:
    """通常テキストページは保持し、OCR候補ページだけpdf_page_ocrを追加する。"""
    source_file = make_source_file(tmp_path / "sample.pdf")
    extraction = PdfDocumentExtraction(
        page_count=2,
        pages=(
            PdfPageExtraction(1, "十分なテキストがあります"),
            PdfPageExtraction(2, ""),
        ),
        pdf_encrypted=False,
        pdf_metadata_available=True,
    )
    ocr_processor = PdfPageOcrProcessor(
        ocr_engine=FakeEngine((region("OCR 日本語"),)),
        renderer=FakeRenderer(),
        options=OcrOptions(model_dir=tmp_path / "models"),
    )

    document = PdfParser(
        FakeExtractor(extraction),
        ocr_processor=ocr_processor,
        min_text_characters_per_page=5,
    ).parse(source_file)

    assert [unit.unit_type for unit in document.units] == ["pdf_page_text", "pdf_page_ocr"]
    assert [unit.locator for unit in document.units] == ["page:1", "page:2/ocr"]
    assert document.units[1].metadata["page_number"] == 2
    assert document.units[1].metadata["render_dpi"] == 200
    assert "pdf_page_ocr_applied" in {issue.issue_type for issue in document.issues}


def test_pdf_ocr_failure_is_recorded_without_failing_pdf_document(tmp_path: Path) -> None:
    """PDFページOCRに失敗してもpypdf抽出済み本文は保持する。"""
    source_file = make_source_file(tmp_path / "sample.pdf")
    extraction = PdfDocumentExtraction(
        page_count=2,
        pages=(
            PdfPageExtraction(1, "十分なテキストがあります"),
            PdfPageExtraction(2, ""),
        ),
        pdf_encrypted=False,
        pdf_metadata_available=True,
    )
    ocr_processor = PdfPageOcrProcessor(
        ocr_engine=FakeEngine((region("unused"),)),
        renderer=FakeRenderer(fail=True),
        options=OcrOptions(model_dir=tmp_path / "models"),
    )

    document = PdfParser(
        FakeExtractor(extraction),
        ocr_processor=ocr_processor,
        min_text_characters_per_page=5,
    ).parse(source_file)

    assert [unit.unit_type for unit in document.units] == ["pdf_page_text"]
    assert "pdf_page_ocr_failed" in {issue.issue_type for issue in document.issues}
