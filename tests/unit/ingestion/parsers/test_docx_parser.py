"""DOCXパーサーの単体テスト。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from signate_drive_rag.domain import SourceFile
from signate_drive_rag.ingestion.parsers.docling_adapter import (
    NormalizedDoclingDocument,
    NormalizedDoclingItem,
)
from signate_drive_rag.ingestion.parsers.docx_parser import DoclingParserError, DocxParser


def make_source_file(path: Path) -> SourceFile:
    """テスト用SourceFileを作成する。"""
    path.write_bytes(b"docx")
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
    level: int | None = None,
    table_data: tuple[tuple[str, ...], ...] | None = None,
) -> NormalizedDoclingItem:
    """テスト用Docling項目を作成する。"""
    return NormalizedDoclingItem(
        index=index,
        label=label,
        text=text,
        page_number=None,
        level=level,
        table_data=table_data,
        metadata={},
    )


def document(
    items: tuple[NormalizedDoclingItem, ...],
    status: str = "success",
    errors: tuple[str, ...] | None = None,
) -> NormalizedDoclingDocument:
    """テスト用Docling文書を作成する。"""
    return NormalizedDoclingDocument(
        status=status,
        items=items,
        page_count=None,
        picture_count=0,
        errors=(("failed",) if status == "failed" else ()) if errors is None else errors,
    )


def test_docx_parser_creates_structured_units_and_heading_path(tmp_path: Path) -> None:
    """見出し、段落、箇条書き、表、表行を文書順に抽出できる。"""
    source_file = make_source_file(tmp_path / "資料.docx")
    parser = DocxParser(
        FakeAdapter(
            document(
                (
                    item(1, "section_header", "契約条件", level=1),
                    item(2, "text", "日本語本文"),
                    item(3, "list_item", "第一条"),
                    item(4, "text", ""),
                    item(
                        5,
                        "table",
                        "| 項目 | 金額 |\n| --- | --- |\n| 契約金額 | 4200000 |",
                        table_data=(("項目", "金額"), ("契約金額", "4200000")),
                    ),
                )
            )
        )
    )

    extracted = parser.parse(source_file)

    assert extracted.source_file == source_file
    assert extracted.parser_name == "docling_docx"
    assert [unit.unit_type for unit in extracted.units] == [
        "docx_heading",
        "docx_paragraph",
        "docx_list_item",
        "docx_table",
        "docx_table_row",
    ]
    assert [unit.locator for unit in extracted.units] == [
        "item:1",
        "item:2",
        "item:3",
        "table:1",
        "table:1/row:2",
    ]
    assert extracted.units[1].metadata["heading_path"] == ["契約条件"]
    assert "日本語本文" in extracted.units[1].text
    assert "page_number" not in extracted.units[0].metadata
    assert extracted.units[3].metadata["row_count"] == 2
    assert extracted.units[4].metadata["values"] == ["契約金額", "4200000"]


def test_docx_parser_is_deterministic_for_same_input(tmp_path: Path) -> None:
    """同じ入力では同じunit順とlocatorを生成する。"""
    source_file = make_source_file(tmp_path / "same.docx")
    parser = DocxParser(FakeAdapter(document((item(1, "text", "本文"), item(2, "text", "続き")))))

    first = parser.parse(source_file)
    second = parser.parse(source_file)

    assert first.units == second.units


def test_docx_parser_raises_safe_error_for_docling_failure(tmp_path: Path) -> None:
    """Docling変換失敗はパーサー例外として呼び出し元へ伝播する。"""
    source_file = make_source_file(tmp_path / "broken.docx")
    parser = DocxParser(
        FakeAdapter(
            document(
                (),
                status="failed",
                errors=(f"File format not allowed: {source_file.path}",),
            )
        )
    )

    with pytest.raises(DoclingParserError, match="<source>") as error:
        parser.parse(source_file)
    assert str(tmp_path) not in str(error.value)
