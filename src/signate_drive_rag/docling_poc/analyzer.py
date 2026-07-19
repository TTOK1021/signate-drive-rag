"""DoclingDocumentからPoC用の構造情報を集計する処理。"""

from collections import Counter
from collections.abc import Iterable

from signate_drive_rag.docling_poc.models import DocumentStructureSummary
from signate_drive_rag.domain.extracted_document import JsonValue


def analyze_document_structure(
    document: object | None,
) -> DocumentStructureSummary:
    """公開APIで取得できる範囲の構造情報を集計する。"""
    if document is None:
        return DocumentStructureSummary(
            page_count=None,
            total_items=0,
            text_item_count=0,
            paragraph_count=0,
            list_item_count=0,
            table_count=0,
            picture_count=0,
            heading_count=0,
            provenance_items=0,
            provenance_coverage=0.0,
            item_counts_by_label={},
        )

    items = tuple(_iter_document_items(document))
    label_counts = Counter(_item_label(item) for item in items)
    label_counts.pop("", None)
    total_items = len(items)
    provenance_items = sum(1 for item in items if _has_provenance(item))
    coverage = provenance_items / total_items if total_items > 0 else 0.0

    return DocumentStructureSummary(
        page_count=_page_count(document),
        total_items=total_items,
        text_item_count=_count_labels(
            label_counts, ("text", "paragraph", "section_header", "title")
        ),
        paragraph_count=_count_labels(label_counts, ("text", "paragraph")),
        list_item_count=_count_labels(label_counts, ("list_item",)),
        table_count=max(
            _count_labels(label_counts, ("table",)), _collection_length(document, "tables")
        ),
        picture_count=max(
            _count_labels(label_counts, ("picture", "image")),
            _collection_length(document, "pictures"),
        ),
        heading_count=_count_labels(label_counts, ("section_header", "title", "heading")),
        provenance_items=provenance_items,
        provenance_coverage=coverage,
        item_counts_by_label=dict(sorted(label_counts.items())),
    )


def json_byte_length(json_document: dict[str, JsonValue]) -> int:
    """JSON表現のUTF-8バイト数を計算する。"""
    import json

    return len(json.dumps(json_document, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _iter_document_items(document: object) -> Iterable[object]:
    iterate_items = getattr(document, "iterate_items", None)
    if callable(iterate_items):
        try:
            for item, _level in iterate_items(with_groups=True, traverse_pictures=True):
                yield item
            return
        except TypeError:
            for item, _level in iterate_items():
                yield item
            return

    for attribute_name in ("texts", "tables", "pictures"):
        collection = getattr(document, attribute_name, None)
        if isinstance(collection, list | tuple):
            yield from collection


def _item_label(item: object) -> str:
    label = getattr(item, "label", None)
    value = getattr(label, "value", label)
    if isinstance(value, str):
        return value
    return type(item).__name__


def _has_provenance(item: object) -> bool:
    provenance = getattr(item, "prov", None)
    if provenance is None:
        provenance = getattr(item, "provenance", None)
    if isinstance(provenance, list | tuple):
        return len(provenance) > 0
    return provenance is not None


def _page_count(document: object) -> int | None:
    pages = getattr(document, "pages", None)
    if isinstance(pages, dict | list | tuple):
        return len(pages)
    return None


def _collection_length(document: object, attribute_name: str) -> int:
    value = getattr(document, attribute_name, None)
    if isinstance(value, list | tuple | dict):
        return len(value)
    return 0


def _count_labels(label_counts: Counter[str], labels: tuple[str, ...]) -> int:
    normalized_labels = {label.lower() for label in labels}
    total = 0
    for label, count in label_counts.items():
        if label.lower() in normalized_labels:
            total += count
    return total
