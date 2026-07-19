"""Docling項目正規化の単体テスト。"""

from typing import ClassVar

from signate_drive_rag.ingestion.parsers.docling_adapter import normalize_docling_document


class FakeLabel:
    """Doclingのlabel enum相当を模した値。"""

    value = "section_header"


class FakeProvenance:
    """Doclingのページ由来情報を模した値。"""

    page_no = 3


class FakeTextItem:
    """Doclingの本文項目を模した値。"""

    label = FakeLabel()
    text = "見出し"
    prov: ClassVar = [FakeProvenance()]
    level = 2


class FakeTableItem:
    """Doclingの表項目を模した値。"""

    label = "table"

    def export_to_markdown(self) -> str:
        """Markdown表として公開API風に返す。"""
        return "| A | B |\n| --- | --- |\n| あ | 1 |"


class FakeDocument:
    """Docling文書を模した値。"""

    pages: ClassVar = {1: object(), 2: object(), 3: object()}
    pictures: ClassVar = [object()]

    def iterate_items(self, with_groups: bool = False) -> tuple[tuple[object, int], ...]:
        """文書順の項目を返す。"""
        return ((FakeTextItem(), 0), (FakeTableItem(), 0))


def test_normalize_docling_document_extracts_label_page_level_and_table_rows() -> None:
    """Docling項目からラベル、ページ番号、見出しレベル、表行を正規化できる。"""
    document = normalize_docling_document(FakeDocument(), status="success")

    assert document.status == "success"
    assert document.page_count == 3
    assert document.picture_count == 1
    assert document.items[0].index == 1
    assert document.items[0].label == "section_header"
    assert document.items[0].page_number == 3
    assert document.items[0].level == 2
    assert document.items[1].table_data == (("A", "B"), ("あ", "1"))
    assert "| A | B |" in document.items[1].text


def test_normalize_docling_document_handles_missing_document() -> None:
    """Docling文書がない変換結果も空の中間表現として扱える。"""
    document = normalize_docling_document(None, status="failed", errors=("broken",))

    assert document.items == ()
    assert document.page_count is None
    assert document.errors == ("broken",)
