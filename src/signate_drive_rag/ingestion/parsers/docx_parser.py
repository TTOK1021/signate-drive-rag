"""DOCXをDoclingで抽出するパーサー。"""

from collections.abc import Iterable
from importlib import metadata
from pathlib import Path

from signate_drive_rag.domain import ExtractedDocument, ExtractedUnit, ExtractionIssue, JsonValue
from signate_drive_rag.domain.source_file import SourceFile
from signate_drive_rag.ingestion.parsers.docling_adapter import (
    DoclingDocumentAdapter,
    NormalizedDoclingDocument,
    NormalizedDoclingItem,
    ProductionDoclingDocumentAdapter,
)
from signate_drive_rag.ingestion.parsers.extraction_issue import (
    DOCUMENT_HAS_NO_TEXT,
    extraction_issue,
)

HEADING_LABELS = frozenset({"section_header", "title", "heading"})
PARAGRAPH_LABELS = frozenset({"text", "paragraph"})
LIST_LABELS = frozenset({"list_item"})
TABLE_LABELS = frozenset({"table"})


class DoclingParserError(RuntimeError):
    """Docling変換が安全に完了しなかった場合の例外。"""


class DocxParser:
    """DOCXをDoclingで文書構造付きテキストへ変換する。"""

    SUPPORTED_SUFFIXES = frozenset({".docx"})

    def __init__(self, adapter: DoclingDocumentAdapter | None = None) -> None:
        """Docling依存をテストで差し替えられるようにする。"""
        self._adapter = adapter

    @property
    def name(self) -> str:
        """パーサーを識別する名前を返す。"""
        return "docling_docx"

    def supports(self, source_file: SourceFile) -> bool:
        """対象ファイルを処理できるか判定する。"""
        return source_file.suffix.lower() in self.SUPPORTED_SUFFIXES

    def parse(self, source_file: SourceFile) -> ExtractedDocument:
        """DOCXをDocling項目順に抽出する。"""
        try:
            document = self._adapter_or_default().convert(source_file.path)
        except Exception as error:
            raise DoclingParserError(
                _safe_message(str(error).replace(str(source_file.path), "<source>"))
            ) from error
        _raise_for_docling_failure(document, source_file.path)
        units = _docx_units(document)
        issues = _document_issues(units)
        return ExtractedDocument(
            source_file=source_file,
            parser_name=self.name,
            units=units,
            issues=issues,
        )

    def _adapter_or_default(self) -> DoclingDocumentAdapter:
        """Registry作成だけでDocling初期化が走らないよう遅延生成する。"""
        if self._adapter is None:
            self._adapter = ProductionDoclingDocumentAdapter()
        return self._adapter


def _docx_units(document: NormalizedDoclingDocument) -> tuple[ExtractedUnit, ...]:
    units: list[ExtractedUnit] = []
    heading_stack: list[tuple[int, str]] = []
    table_index = 0

    for item in document.items:
        label = item.label.lower()
        if label in HEADING_LABELS:
            heading_path = _update_heading_path(heading_stack, item)
            unit = _text_unit(
                item,
                unit_type="docx_heading",
                heading_path=heading_path,
                extra_metadata={
                    "heading_level": item.level,
                    "heading_text": item.text.strip(),
                },
                document=document,
            )
            if unit is not None:
                units.append(unit)
            continue

        heading_path = tuple(heading for _level, heading in heading_stack)
        if item.table_data is not None or label in TABLE_LABELS:
            table_index += 1
            units.extend(_table_units(item, table_index, heading_path, document, "docx"))
            continue
        unit_type = "docx_list_item" if label in LIST_LABELS else "docx_paragraph"
        unit = _text_unit(
            item,
            unit_type=unit_type,
            heading_path=heading_path,
            extra_metadata=_list_metadata(item) if unit_type == "docx_list_item" else {},
            document=document,
        )
        if unit is not None:
            units.append(unit)

    return tuple(units)


def _update_heading_path(
    heading_stack: list[tuple[int, str]],
    item: NormalizedDoclingItem,
) -> tuple[str, ...]:
    heading_text = item.text.strip()
    if item.level is not None:
        heading_stack[:] = [
            (level, heading) for level, heading in heading_stack if level < item.level
        ]
        if heading_text:
            heading_stack.append((item.level, heading_text))
    return tuple(heading for _level, heading in heading_stack)


def _text_unit(
    item: NormalizedDoclingItem,
    *,
    unit_type: str,
    heading_path: tuple[str, ...],
    extra_metadata: dict[str, JsonValue],
    document: NormalizedDoclingDocument,
) -> ExtractedUnit | None:
    text = item.text.strip()
    if text == "":
        return None
    metadata: dict[str, JsonValue] = {
        "item_index": item.index,
        "heading_path": list(heading_path),
        "item_label": item.label,
        "document_metadata": _document_metadata(document),
    }
    metadata.update(extra_metadata)
    return ExtractedUnit(
        unit_type=unit_type,
        text=text,
        locator=f"item:{item.index}",
        metadata=metadata,
    )


def _table_units(
    item: NormalizedDoclingItem,
    table_index: int,
    heading_path: tuple[str, ...],
    document: NormalizedDoclingDocument,
    prefix: str,
) -> list[ExtractedUnit]:
    rows = item.table_data or ()
    table_text = item.text.strip()
    if table_text == "":
        return []
    row_count = len(rows)
    column_count = max((len(row) for row in rows), default=0)
    headers = list(rows[0]) if rows else []
    metadata: dict[str, JsonValue] = {
        "item_index": item.index,
        "table_index": table_index,
        "row_count": row_count,
        "column_count": column_count,
        "heading_path": list(heading_path),
        "headers": list(headers),
        "document_metadata": _document_metadata(document),
    }
    units = [
        ExtractedUnit(
            unit_type=f"{prefix}_table",
            text=table_text,
            locator=f"table:{table_index}",
            metadata=metadata,
        )
    ]
    for row_index, row in enumerate(rows[1:] if headers else rows, start=2 if headers else 1):
        row_text = _row_text(headers, row, row_index)
        if row_text == "":
            continue
        units.append(
            ExtractedUnit(
                unit_type=f"{prefix}_table_row",
                text=row_text,
                locator=f"table:{table_index}/row:{row_index}",
                metadata={
                    **metadata,
                    "row_index": row_index,
                    "logical_row_number": row_index,
                    "values": list(row),
                },
            )
        )
    return units


def _row_text(headers: list[str], row: tuple[str, ...], row_index: int) -> str:
    values = [cell.strip() for cell in row]
    if all(value == "" for value in values):
        return ""
    lines = []
    if headers:
        lines.append(f"列: {' | '.join(headers)}")
    lines.append(f"行{row_index}: {' | '.join(values)}")
    return "\n".join(lines)


def _list_metadata(item: NormalizedDoclingItem) -> dict[str, JsonValue]:
    metadata: dict[str, JsonValue] = {}
    for key in ("list_level", "list_marker"):
        value = item.metadata.get(key)
        if isinstance(value, str | int):
            metadata[key] = value
    return metadata


def _document_issues(units: tuple[ExtractedUnit, ...]) -> tuple[ExtractionIssue, ...]:
    text_characters = _non_whitespace_characters(unit.text for unit in units)
    if text_characters != 0:
        return ()
    return (
        extraction_issue(
            DOCUMENT_HAS_NO_TEXT,
            message="Doclingで非空白本文を抽出できませんでした。",
            metadata={"text_characters": text_characters},
        ),
    )


def _document_metadata(document: NormalizedDoclingDocument) -> dict[str, JsonValue]:
    item_count = len(document.items)
    return {
        "docling_version": metadata.version("docling"),
        "item_count": item_count,
        "heading_count": sum(1 for item in document.items if item.label in HEADING_LABELS),
        "paragraph_count": sum(1 for item in document.items if item.label in PARAGRAPH_LABELS),
        "list_item_count": sum(1 for item in document.items if item.label in LIST_LABELS),
        "table_count": sum(1 for item in document.items if item.table_data is not None),
        "text_characters": _non_whitespace_characters(item.text for item in document.items),
    }


def _non_whitespace_characters(values: Iterable[str]) -> int:
    return sum(1 for text in values for character in text if not character.isspace())


def _raise_for_docling_failure(document: NormalizedDoclingDocument, source_path: Path) -> None:
    if document.status in {"success", "partial_success"}:
        return
    message = document.errors[0] if document.errors else "Docling conversion failed"
    raise DoclingParserError(_safe_message(_sanitize_source_path(message, source_path)))


def _safe_message(message: str) -> str:
    if len(message) > 500:
        return message[:500] + "..."
    return message


def _sanitize_source_path(message: str, source_path: Path) -> str:
    """Docling由来の失敗メッセージへ原本の絶対パスを残さない。"""
    source_path_text = str(source_path)
    return (
        message.replace(source_path_text, "<source>")
        .replace(source_path_text.replace("\\", "\\\\"), "<source>")
        .replace(source_path.as_posix(), "<source>")
    )
