"""Docling文書を抽出パーサー向けの中間表現へ変換する処理。"""

import re
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Protocol, cast

from signate_drive_rag.docling_poc import (
    DoclingConversionAdapter,
)
from signate_drive_rag.domain import JsonValue

DEFAULT_DOCLING_TIMEOUT_SECONDS = 180


@dataclass(frozen=True, slots=True)
class NormalizedDoclingItem:
    """Docling項目をパーサー共通形式へ正規化したもの。"""

    index: int
    label: str
    text: str
    page_number: int | None
    level: int | None
    table_data: tuple[tuple[str, ...], ...] | None
    metadata: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class NormalizedDoclingDocument:
    """Docling文書を抽出処理で扱いやすい形へ正規化したもの。"""

    status: str
    items: tuple[NormalizedDoclingItem, ...]
    page_count: int | None
    picture_count: int
    errors: tuple[str, ...]


class DoclingDocumentAdapter(Protocol):
    """Docling文書を正規化して返すアダプター。"""

    def convert(self, source_path: Path) -> NormalizedDoclingDocument:
        """指定ファイルをDoclingで変換し、パーサー用の中間表現へ変換する。"""
        ...


class ProductionDoclingDocumentAdapter:
    """Docling PoCアダプターを本番抽出パーサー向けに薄く包む。"""

    def __init__(self, *, timeout_seconds: int = DEFAULT_DOCLING_TIMEOUT_SECONDS) -> None:
        """Doclingの初期化をファイルごとに繰り返さない。"""
        self._timeout_seconds = timeout_seconds
        self._conversion_adapter = DoclingConversionAdapter()

    def convert(self, source_path: Path) -> NormalizedDoclingDocument:
        """Docling default_localで変換し、Docling型をこの層へ閉じ込める。"""
        output = self._conversion_adapter.convert(
            source_path,
            profile="default_local",
            timeout_seconds=self._timeout_seconds,
        )
        return normalize_docling_document(
            output.document,
            status=output.status,
            errors=tuple(_sanitize_error(error, source_path) for error in output.errors),
        )


def docling_version() -> str:
    """抽出metadataへ記録するDoclingバージョンを返す。"""
    return metadata.version("docling")


def normalize_docling_document(
    document: object | None,
    *,
    status: str,
    errors: tuple[str, ...] = (),
) -> NormalizedDoclingDocument:
    """Docling公開APIで取得できる文書要素を決定的な中間表現へ変換する。"""
    if document is None:
        return NormalizedDoclingDocument(
            status=status,
            items=(),
            page_count=None,
            picture_count=0,
            errors=errors,
        )
    items = tuple(
        _normalize_item(item, item_index, document)
        for item_index, item in enumerate(_iter_document_items(document), start=1)
    )
    return NormalizedDoclingDocument(
        status=status,
        items=items,
        page_count=_page_count(document),
        picture_count=_collection_length(document, "pictures"),
        errors=errors,
    )


def _iter_document_items(document: object) -> tuple[object, ...]:
    iterate_items = getattr(document, "iterate_items", None)
    if callable(iterate_items):
        try:
            return tuple(item for item, _level in iterate_items(with_groups=True))
        except TypeError:
            return tuple(item for item, _level in iterate_items())
    items: list[object] = []
    for attribute_name in ("texts", "tables", "pictures"):
        collection = getattr(document, attribute_name, None)
        if isinstance(collection, list | tuple):
            items.extend(collection)
    return tuple(items)


def _normalize_item(item: object, item_index: int, document: object) -> NormalizedDoclingItem:
    label = _item_label(item)
    table_data = _table_data(item, document)
    text = _item_text(item, document, table_data)
    return NormalizedDoclingItem(
        index=item_index,
        label=label,
        text=text,
        page_number=_page_number(item),
        level=_heading_level(item),
        table_data=table_data,
        metadata={"item_label": label},
    )


def _item_label(item: object) -> str:
    label = getattr(item, "label", None)
    value = getattr(label, "value", label)
    if isinstance(value, str):
        return value.lower()
    return type(item).__name__.lower()


def _item_text(
    item: object,
    document: object,
    table_data: tuple[tuple[str, ...], ...] | None,
) -> str:
    if table_data is not None:
        return _table_to_markdown(table_data)
    for method_name in ("export_to_text", "export_to_markdown"):
        exported = _call_export_method(item, method_name, document)
        if exported is not None:
            return exported
    text = getattr(item, "text", None)
    return text if isinstance(text, str) else ""


def _call_export_method(item: object, method_name: str, document: object) -> str | None:
    method = getattr(item, method_name, None)
    if not callable(method):
        return None
    for kwargs in ({"doc": document}, {}):
        try:
            value = method(**kwargs)
        except TypeError:
            continue
        if isinstance(value, str):
            return value
    return None


def _table_data(item: object, document: object) -> tuple[tuple[str, ...], ...] | None:
    explicit_table_data = getattr(item, "table_data", None)
    if _is_table_data(explicit_table_data):
        rows = cast(
            tuple[tuple[str, ...], ...] | list[list[str] | tuple[str, ...]],
            explicit_table_data,
        )
        return tuple(tuple(cell for cell in row) for row in rows)
    markdown = _call_export_method(item, "export_to_markdown", document)
    if markdown:
        return _markdown_table_to_rows(markdown)
    return None


def _is_table_data(value: object) -> bool:
    return isinstance(value, tuple | list) and all(
        isinstance(row, tuple | list) and all(isinstance(cell, str) for cell in row)
        for row in value
    )


def _table_to_markdown(rows: tuple[tuple[str, ...], ...]) -> str:
    if not rows:
        return ""
    column_count = max((len(row) for row in rows), default=0)
    normalized_rows = [list(row) + [""] * (column_count - len(row)) for row in rows]
    header = normalized_rows[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _column in range(column_count)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in normalized_rows[1:])
    return "\n".join(lines)


def _markdown_table_to_rows(markdown: str) -> tuple[tuple[str, ...], ...] | None:
    lines = [line.strip() for line in markdown.splitlines() if line.strip().startswith("|")]
    rows: list[tuple[str, ...]] = []
    for line in lines:
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        if cells:
            rows.append(cells)
    return tuple(rows) if rows else None


def _page_number(item: object) -> int | None:
    provenance = getattr(item, "prov", None)
    if provenance is None:
        provenance = getattr(item, "provenance", None)
    if isinstance(provenance, list | tuple) and provenance:
        page_no = getattr(provenance[0], "page_no", None)
        if isinstance(page_no, int) and not isinstance(page_no, bool):
            return page_no
    page_no = getattr(item, "page_no", None)
    if isinstance(page_no, int) and not isinstance(page_no, bool):
        return page_no
    return None


def _heading_level(item: object) -> int | None:
    for attribute_name in ("level", "heading_level"):
        value = getattr(item, attribute_name, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _page_count(document: object) -> int | None:
    pages = getattr(document, "pages", None)
    if isinstance(pages, dict | list | tuple):
        return len(pages)
    return None


def _collection_length(document: object, attribute_name: str) -> int:
    value = getattr(document, attribute_name, None)
    if isinstance(value, dict | list | tuple):
        return len(value)
    return 0


def _sanitize_error(error: str, source_path: Path) -> str:
    message = _replace_source_path(error, source_path)
    if len(message) > 500:
        return message[:500] + "..."
    return message


def _replace_source_path(message: str, source_path: Path) -> str:
    """Doclingの表現揺れを吸収し、成果物へ絶対パスを残さない。"""
    source_path_text = str(source_path)
    return (
        message.replace(source_path_text, "<source>")
        .replace(source_path_text.replace("\\", "\\\\"), "<source>")
        .replace(source_path.as_posix(), "<source>")
    )
