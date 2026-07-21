"""PPTXパーサーの単体テスト。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from signate_drive_rag.domain import SourceFile
from signate_drive_rag.ingestion.parsers.docling_adapter import (
    NormalizedDoclingDocument,
    NormalizedDoclingItem,
)
from signate_drive_rag.ingestion.parsers.docx_parser import DoclingParserError
from signate_drive_rag.ingestion.parsers.pptx_parser import PptxParser


def make_source_file(path: Path) -> SourceFile:
    """テスト用SourceFileを作成する。"""
    path.write_bytes(b"pptx")
    return SourceFile(
        path=path,
        relative_path=Path("日本語") / path.name,
        name=path.name,
        suffix=path.suffix.lower(),
        mime_type=None,
        size_bytes=path.stat().st_size,
        modified_at=datetime(2026, 7, 19, tzinfo=UTC),
    )


@dataclass(frozen=True, slots=True)
class FakeAdapter:
    """Docling変換を差し替える偽アダプター。"""

    document: NormalizedDoclingDocument

    def convert(self, source_path: Path) -> NormalizedDoclingDocument:
        """固定の中間表現を返す。"""
        return self.document


def item(
    index: int,
    label: str,
    text: str,
    *,
    page_number: int | None,
    table_data: tuple[tuple[str, ...], ...] | None = None,
) -> NormalizedDoclingItem:
    """テスト用Docling項目を作成する。"""
    return NormalizedDoclingItem(
        index=index,
        label=label,
        text=text,
        page_number=page_number,
        level=None,
        table_data=table_data,
        metadata={},
    )


def document(
    items: tuple[NormalizedDoclingItem, ...],
    *,
    status: str = "success",
    picture_count: int = 0,
) -> NormalizedDoclingDocument:
    """テスト用Docling文書を作成する。"""
    return NormalizedDoclingDocument(
        status=status,
        items=items,
        page_count=2,
        picture_count=picture_count,
        errors=("failed",) if status == "failed" else (),
    )


def test_pptx_parser_creates_slide_units_and_preserves_slide_context(tmp_path: Path) -> None:
    """タイトル、本文、表、表行をスライド番号付きで抽出できる。"""
    source_file = make_source_file(tmp_path / "資料.pptx")
    parser = PptxParser(
        FakeAdapter(
            document(
                (
                    item(1, "title", "分析結果", page_number=1),
                    item(2, "text", "日本語本文", page_number=1),
                    item(3, "title", "次スライド", page_number=2),
                    item(
                        4,
                        "table",
                        "| A | B |\n| --- | --- |\n| あ | 1 |",
                        page_number=2,
                        table_data=(("A", "B"), ("あ", "1")),
                    ),
                    item(5, "text", "", page_number=2),
                )
            )
        )
    )

    extracted = parser.parse(source_file)

    assert [unit.unit_type for unit in extracted.units] == [
        "pptx_slide_title",
        "pptx_slide_text",
        "pptx_slide_title",
        "pptx_slide_table",
        "pptx_slide_table_row",
    ]
    assert extracted.units[0].locator == "slide:1/item:1"
    assert extracted.units[1].metadata["slide_title"] == "分析結果"
    assert extracted.units[3].locator == "slide:2/table:1"
    assert extracted.units[4].locator == "slide:2/table:1/row:2"
    assert extracted.units[4].metadata["slide_number"] == 2
    assert "日本語本文" in extracted.units[1].text


def test_pptx_parser_records_low_text_and_image_dominant_issues(tmp_path: Path) -> None:
    """少量本文かつ画像ありの資料にテキスト不足issueを付ける。"""
    source_file = make_source_file(tmp_path / "small.pptx")
    parser = PptxParser(
        FakeAdapter(document((item(1, "text", "短い", page_number=1),), picture_count=1))
    )

    extracted = parser.parse(source_file)

    assert {issue.issue_type for issue in extracted.issues} == {
        "low_text_content",
        "image_dominant_document",
    }


def test_pptx_parser_records_no_text_issue(tmp_path: Path) -> None:
    """本文0文字の資料にdocument_has_no_textを付ける。"""
    source_file = make_source_file(tmp_path / "empty.pptx")
    parser = PptxParser(FakeAdapter(document((item(1, "text", "", page_number=1),))))

    extracted = parser.parse(source_file)

    assert extracted.units == ()
    assert extracted.issues[0].issue_type == "document_has_no_text"


def test_pptx_parser_is_deterministic_and_raises_safe_error(tmp_path: Path) -> None:
    """同じ入力の決定性とDocling失敗の例外伝播を確認する。"""
    source_file = make_source_file(tmp_path / "same.pptx")
    parser = PptxParser(FakeAdapter(document((item(1, "text", "本文", page_number=1),))))

    assert parser.parse(source_file).units == parser.parse(source_file).units

    broken_parser = PptxParser(FakeAdapter(document((), status="failed")))
    with pytest.raises(DoclingParserError, match="failed"):
        broken_parser.parse(source_file)
