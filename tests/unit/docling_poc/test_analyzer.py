"""Docling PoC構造分析のテスト。"""

from dataclasses import dataclass

from signate_drive_rag.docling_poc.analyzer import analyze_document_structure


@dataclass(frozen=True, slots=True)
class FakeLabel:
    """Doclingのラベル相当。"""

    value: str


@dataclass(frozen=True, slots=True)
class FakeItem:
    """Docling item相当。"""

    label: FakeLabel
    prov: tuple[str, ...] = ()


class FakeDocument:
    """DoclingDocument相当の最小実装。"""

    def __init__(self, items: tuple[FakeItem, ...], pages: dict[int, object]) -> None:
        self._items = items
        self.pages = pages
        self.tables = [item for item in items if item.label.value == "table"]
        self.pictures = [item for item in items if item.label.value == "picture"]

    def iterate_items(
        self,
        *,
        with_groups: bool,
        traverse_pictures: bool,
    ) -> tuple[tuple[FakeItem, int], ...]:
        """Doclingの公開API形状に合わせる。"""
        assert with_groups is True
        assert traverse_pictures is True
        return tuple((item, 0) for item in self._items)


def test_analyze_document_structure_counts_items_labels_and_provenance() -> None:
    """item数、ラベル別件数、表、画像、見出し、provenanceを集計できる。"""
    document = FakeDocument(
        (
            FakeItem(FakeLabel("section_header"), ("p1",)),
            FakeItem(FakeLabel("text"), ("p1",)),
            FakeItem(FakeLabel("list_item")),
            FakeItem(FakeLabel("table"), ("p2",)),
            FakeItem(FakeLabel("picture")),
        ),
        pages={1: object(), 2: object()},
    )

    summary = analyze_document_structure(document)

    assert summary.total_items == 5
    assert summary.page_count == 2
    assert summary.heading_count == 1
    assert summary.table_count == 1
    assert summary.picture_count == 1
    assert summary.list_item_count == 1
    assert summary.provenance_items == 3
    assert summary.provenance_coverage == 0.6
    assert list(summary.item_counts_by_label) == [
        "list_item",
        "picture",
        "section_header",
        "table",
        "text",
    ]


def test_analyze_document_structure_handles_missing_document() -> None:
    """取得不能な文書では安全に空の集計を返す。"""
    summary = analyze_document_structure(None)

    assert summary.page_count is None
    assert summary.total_items == 0
    assert summary.provenance_coverage == 0.0
    assert summary.item_counts_by_label == {}
