"""PDFパーサーの単体テスト。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pypdf import PdfWriter

from signate_drive_rag.domain import SourceFile
from signate_drive_rag.extraction import ExtractionService
from signate_drive_rag.extraction.serializer import save_extraction_result
from signate_drive_rag.ingestion.parser_registry import ParserRegistry
from signate_drive_rag.ingestion.parsers.pdf_parser import (
    PdfDocumentExtraction,
    PdfPageExtraction,
    PdfParser,
    PdfParserError,
    PypdfTextExtractor,
    normalize_pdf_text,
)


def make_source_file(path: Path) -> SourceFile:
    """テスト用SourceFileを作成する。"""
    if not path.exists():
        path.write_bytes(b"%PDF")
    return SourceFile(
        path=path,
        relative_path=Path("日本語") / path.name,
        name=path.name,
        suffix=path.suffix.lower(),
        mime_type="application/pdf",
        size_bytes=path.stat().st_size,
        modified_at=datetime(2026, 7, 19, tzinfo=UTC),
    )


@dataclass(frozen=True, slots=True)
class FakeExtractor:
    """pypdf抽出を差し替える偽抽出器。"""

    extraction: PdfDocumentExtraction

    def extract(self, source_file: SourceFile) -> PdfDocumentExtraction:
        """固定のページ抽出結果を返す。"""
        return self.extraction


class BrokenExtractor:
    """読込不能PDFを模した抽出器。"""

    def extract(self, source_file: SourceFile) -> PdfDocumentExtraction:
        """PDF全体の読込失敗を発生させる。"""
        raise PdfParserError("pdf_unreadable: broken")


def extraction(*pages: PdfPageExtraction) -> PdfDocumentExtraction:
    """テスト用PDF抽出結果を作成する。"""
    return PdfDocumentExtraction(
        page_count=len(pages),
        pages=pages,
        pdf_encrypted=False,
        pdf_metadata_available=True,
    )


def test_pypdf_text_extractor_reads_pdf_page_count(tmp_path: Path) -> None:
    """pypdfでPDFを読み、ページ数を取得できる。"""
    pdf_path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with pdf_path.open("wb") as output_file:
        writer.write(output_file)

    extracted = PypdfTextExtractor().extract(make_source_file(pdf_path))

    assert extracted.page_count == 1
    assert extracted.pages[0].page_number == 1


def test_pdf_parser_creates_page_units_issues_and_metadata(tmp_path: Path) -> None:
    """ページ単位unit、OCR候補issue、文書metadataを生成できる。"""
    source_file = make_source_file(tmp_path / "資料.pdf")
    parser = PdfParser(
        FakeExtractor(
            extraction(
                PdfPageExtraction(1, "本文\r\n  1  \n\n\n終わり"),
                PdfPageExtraction(2, ""),
                PdfPageExtraction(3, "少量"),
            )
        ),
        min_text_characters_per_page=5,
        min_text_characters_per_document=50,
        image_dominant_page_ratio=0.8,
    )

    extracted = parser.parse(source_file)

    assert [unit.locator for unit in extracted.units] == ["page:1", "page:3"]
    assert extracted.units[0].unit_type == "pdf_page_text"
    assert extracted.units[0].text == "本文\n  1\n\n終わり"
    assert extracted.units[0].metadata["page_number"] == 1
    assert extracted.units[0].metadata["document_metadata"]["page_count"] == 3
    assert extracted.units[0].metadata["document_metadata"]["pages_with_text"] == 2
    assert extracted.units[0].metadata["document_metadata"]["pages_needing_ocr"] == 2
    assert {issue.issue_type for issue in extracted.issues} == {
        "pdf_page_needs_ocr",
        "low_text_content",
        "pdf_partially_needs_ocr",
    }


def test_pdf_parser_records_document_level_no_text_and_image_dominant_issues(
    tmp_path: Path,
) -> None:
    """全ページ空のPDFに本文なしと画像中心issueを付ける。"""
    source_file = make_source_file(tmp_path / "empty.pdf")
    parser = PdfParser(
        FakeExtractor(extraction(PdfPageExtraction(1, ""), PdfPageExtraction(2, ""))),
        image_dominant_page_ratio=0.8,
    )

    extracted = parser.parse(source_file)

    assert extracted.units == ()
    assert {issue.issue_type for issue in extracted.issues} >= {
        "document_has_no_text",
        "image_dominant_document",
    }


def test_pdf_parser_keeps_processing_after_single_page_failure(tmp_path: Path) -> None:
    """1ページの抽出失敗をissue化し、後続ページの抽出を継続する。"""
    source_file = make_source_file(tmp_path / "partial.pdf")
    parser = PdfParser(
        FakeExtractor(
            extraction(
                PdfPageExtraction(1, "", error_type="ValueError", error_message="本文は含めない"),
                PdfPageExtraction(2, "後続ページの十分な本文です"),
            )
        ),
        min_text_characters_per_page=5,
    )

    extracted = parser.parse(source_file)

    assert [unit.locator for unit in extracted.units] == ["page:2"]
    assert "pdf_page_extraction_failed" in {issue.issue_type for issue in extracted.issues}
    assert "本文は含めない" not in extracted.issues[0].message


def test_pdf_parser_failure_is_recorded_without_absolute_path_in_serialized_output(
    tmp_path: Path,
) -> None:
    """PDF全体の読込失敗は抽出失敗として記録し、成果物に絶対パスを保存しない。"""
    source_file = make_source_file(tmp_path / "broken.pdf")
    registry = ParserRegistry()
    registry.register(PdfParser(BrokenExtractor()))

    result = ExtractionService(registry).extract([source_file])
    save_extraction_result(result, tmp_path / "out")

    failure_text = (tmp_path / "out" / "failures.jsonl").read_text(encoding="utf-8")
    assert result.failures[0].error_type == "PdfParserError"
    assert "pdf_unreadable" in result.failures[0].error_message
    assert str(tmp_path) not in failure_text


def test_normalize_pdf_text_keeps_content_without_layout_repair() -> None:
    """PDFテキスト正規化は最小限に留める。"""
    assert normalize_pdf_text("A-\r\nB\x00  \n\n\nC") == "A-\nB\n\nC"


def test_pdf_parser_supports_pdf_suffix_case_insensitively(tmp_path: Path) -> None:
    """PDF拡張子を大文字小文字に依存せず判定する。"""
    source_file = make_source_file(tmp_path / "REPORT.PDF")

    assert PdfParser(FakeExtractor(extraction())).supports(source_file)


def test_pypdf_text_extractor_raises_for_unreadable_pdf(tmp_path: Path) -> None:
    """読込不能PDFは安全なパーサー例外にする。"""
    source_file = make_source_file(tmp_path / "broken.pdf")

    with pytest.raises(PdfParserError, match="pdf_unreadable"):
        PypdfTextExtractor().extract(source_file)
