"""PPTXをDoclingで抽出するパーサー。"""

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
from signate_drive_rag.ingestion.parsers.docx_parser import (
    DoclingParserError,
    _non_whitespace_characters,
    _row_text,
    _safe_message,
)
from signate_drive_rag.ingestion.parsers.extraction_issue import (
    DOCUMENT_HAS_NO_TEXT,
    IMAGE_DOMINANT_DOCUMENT,
    LOW_TEXT_CONTENT,
    extraction_issue,
)

MIN_TEXT_CHARACTERS_PER_DOCUMENT = 20
TITLE_LABELS = frozenset({"section_header", "title", "heading"})
TEXT_LABELS = frozenset({"text", "paragraph", "list_item"})
TABLE_LABELS = frozenset({"table"})


class PptxParser:
    """PPTXをDoclingでスライド単位のテキストへ変換する。"""

    SUPPORTED_SUFFIXES = frozenset({".pptx"})

    def __init__(self, adapter: DoclingDocumentAdapter | None = None) -> None:
        """Docling依存をテストで差し替えられるようにする。"""
        self._adapter = adapter

    @property
    def name(self) -> str:
        """パーサーを識別する名前を返す。"""
        return "docling_pptx"

    def supports(self, source_file: SourceFile) -> bool:
        """対象ファイルを処理できるか判定する。"""
        return source_file.suffix.lower() in self.SUPPORTED_SUFFIXES

    def parse(self, source_file: SourceFile) -> ExtractedDocument:
        """PPTXをDocling項目順に抽出する。"""
        try:
            document = self._adapter_or_default().convert(source_file.path)
        except Exception as error:
            raise DoclingParserError(
                _safe_message(str(error).replace(str(source_file.path), "<source>"))
            ) from error
        _raise_for_docling_failure(document, source_file.path)
        units = _pptx_units(document)
        issues = _document_issues(document, units)
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


def _pptx_units(document: NormalizedDoclingDocument) -> tuple[ExtractedUnit, ...]:
    units: list[ExtractedUnit] = []
    title_by_slide: dict[int, str] = {}
    table_count_by_slide: dict[int, int] = {}

    for item in document.items:
        slide_number = item.page_number
        label = item.label.lower()
        if item.table_data is not None or label in TABLE_LABELS:
            table_index = table_count_by_slide.get(slide_number or 0, 0) + 1
            table_count_by_slide[slide_number or 0] = table_index
            units.extend(_table_units(item, slide_number, table_index, title_by_slide, document))
            continue

        unit_type = "pptx_slide_title" if label in TITLE_LABELS else "pptx_slide_text"
        unit = _text_unit(
            item,
            unit_type=unit_type,
            slide_number=slide_number,
            slide_title=title_by_slide.get(slide_number or 0),
            document=document,
        )
        if unit is None:
            continue
        units.append(unit)
        if unit_type == "pptx_slide_title" and slide_number is not None:
            title_by_slide[slide_number] = unit.text

    return tuple(units)


def _text_unit(
    item: NormalizedDoclingItem,
    *,
    unit_type: str,
    slide_number: int | None,
    slide_title: str | None,
    document: NormalizedDoclingDocument,
) -> ExtractedUnit | None:
    text = item.text.strip()
    if text == "":
        return None
    metadata: dict[str, JsonValue] = {
        "slide_number": slide_number,
        "item_index": item.index,
        "slide_title": text if unit_type == "pptx_slide_title" else slide_title,
        "item_label": item.label,
        "document_metadata": _document_metadata(document),
    }
    return ExtractedUnit(
        unit_type=unit_type,
        text=text,
        locator=_item_locator(slide_number, item.index),
        metadata=metadata,
    )


def _table_units(
    item: NormalizedDoclingItem,
    slide_number: int | None,
    table_index: int,
    title_by_slide: dict[int, str],
    document: NormalizedDoclingDocument,
) -> list[ExtractedUnit]:
    rows = item.table_data or ()
    table_text = item.text.strip()
    if table_text == "":
        return []
    row_count = len(rows)
    column_count = max((len(row) for row in rows), default=0)
    headers = list(rows[0]) if rows else []
    locator_prefix = _table_locator(slide_number, table_index)
    metadata: dict[str, JsonValue] = {
        "slide_number": slide_number,
        "table_index": table_index,
        "row_count": row_count,
        "column_count": column_count,
        "headers": list(headers),
        "slide_title": title_by_slide.get(slide_number or 0),
        "document_metadata": _document_metadata(document),
    }
    units = [
        ExtractedUnit(
            unit_type="pptx_slide_table",
            text=table_text,
            locator=locator_prefix,
            metadata=metadata,
        )
    ]
    for row_index, row in enumerate(rows[1:] if headers else rows, start=2 if headers else 1):
        row_text = _row_text(headers, row, row_index)
        if row_text == "":
            continue
        units.append(
            ExtractedUnit(
                unit_type="pptx_slide_table_row",
                text=row_text,
                locator=f"{locator_prefix}/row:{row_index}",
                metadata={
                    **metadata,
                    "row_index": row_index,
                    "logical_row_number": row_index,
                    "values": list(row),
                },
            )
        )
    return units


def _item_locator(slide_number: int | None, item_index: int) -> str:
    if slide_number is None:
        return f"item:{item_index}"
    return f"slide:{slide_number}/item:{item_index}"


def _table_locator(slide_number: int | None, table_index: int) -> str:
    if slide_number is None:
        return f"table:{table_index}"
    return f"slide:{slide_number}/table:{table_index}"


def _document_issues(
    document: NormalizedDoclingDocument,
    units: tuple[ExtractedUnit, ...],
) -> tuple[ExtractionIssue, ...]:
    text_characters = _non_whitespace_characters(unit.text for unit in units)
    issues: list[ExtractionIssue] = []
    metadata_value: dict[str, JsonValue] = {
        "text_characters": text_characters,
        "threshold": MIN_TEXT_CHARACTERS_PER_DOCUMENT,
        "picture_count": document.picture_count,
    }
    if text_characters == 0:
        issues.append(
            extraction_issue(
                DOCUMENT_HAS_NO_TEXT,
                message="Doclingで非空白本文を抽出できませんでした。",
                metadata=metadata_value,
            )
        )
    elif text_characters < MIN_TEXT_CHARACTERS_PER_DOCUMENT:
        issues.append(
            extraction_issue(
                LOW_TEXT_CONTENT,
                message="抽出文字数がしきい値未満です。",
                metadata=metadata_value,
            )
        )
    if document.picture_count > 0 and text_characters < MIN_TEXT_CHARACTERS_PER_DOCUMENT:
        issues.append(
            extraction_issue(
                IMAGE_DOMINANT_DOCUMENT,
                message="画像を含み、抽出本文が不足しています。",
                metadata=metadata_value,
            )
        )
    return tuple(issues)


def _document_metadata(document: NormalizedDoclingDocument) -> dict[str, JsonValue]:
    return {
        "docling_version": metadata.version("docling"),
        "slide_count": document.page_count,
        "item_count": len(document.items),
        "title_count": sum(1 for item in document.items if item.label in TITLE_LABELS),
        "text_item_count": sum(1 for item in document.items if item.label in TEXT_LABELS),
        "table_count": sum(1 for item in document.items if item.table_data is not None),
        "picture_count": document.picture_count,
        "text_characters": _non_whitespace_characters(item.text for item in document.items),
    }


def _raise_for_docling_failure(document: NormalizedDoclingDocument, source_path: Path) -> None:
    if document.status in {"success", "partial_success"}:
        return
    message = document.errors[0] if document.errors else "Docling conversion failed"
    raise DoclingParserError(_safe_message(_sanitize_source_path(message, source_path)))


def _sanitize_source_path(message: str, source_path: Path) -> str:
    """Docling由来の失敗メッセージへ原本の絶対パスを残さない。"""
    source_path_text = str(source_path)
    return (
        message.replace(source_path_text, "<source>")
        .replace(source_path_text.replace("\\", "\\\\"), "<source>")
        .replace(source_path.as_posix(), "<source>")
    )
