"""ChunkValidationServiceのテスト。"""

import math

from signate_drive_rag.chunk_validation import ChunkValidationService
from signate_drive_rag.chunking.models import (
    ChunkSourceDocument,
    ChunkSourceUnit,
    RetrievalChunk,
)


def test_chunk_validation_accepts_valid_text_table_and_ocr_chunks() -> None:
    """本文・表・OCRの正常なチャンクをエラーなしで受け入れることを確認する。"""
    documents = (
        _source_document(
            relative_path="資料/report.pdf",
            parser_name="pdf",
            units=(
                _source_unit("pdf_page_text", "本文", "page:1"),
                _source_unit("pdf_page_ocr", "画像文字", "page:2"),
            ),
        ),
        _source_document(
            relative_path="表/sheet.xlsx",
            parser_name="xlsx",
            units=(
                _source_unit("xlsx_workbook_summary", "ブック", "workbook"),
                _source_unit("xlsx_sheet_summary", "シート", "sheet:Sheet1"),
                _source_unit("xlsx_table_rows", "A=1", "sheet:Sheet1 range:A1:B2"),
            ),
        ),
    )
    chunks = (
        _chunk(
            chunk_id="c1",
            relative_path="資料/report.pdf",
            parser_name="pdf",
            unit_type="pdf_page_text",
            text="本文",
            locator="page:1",
            source_unit_indices=(0,),
        ),
        _chunk(
            chunk_id="c2",
            relative_path="表/sheet.xlsx",
            parser_name="xlsx",
            unit_type="xlsx_table_rows",
            text="A=1",
            locator="sheet:Sheet1 range:A1:B2",
            source_unit_indices=(2,),
        ),
        _chunk(
            chunk_id="c4",
            relative_path="表/sheet.xlsx",
            parser_name="xlsx",
            unit_type="xlsx_workbook_summary",
            text="ブック",
            locator="workbook",
            source_unit_indices=(0,),
        ),
        _chunk(
            chunk_id="c5",
            relative_path="表/sheet.xlsx",
            parser_name="xlsx",
            unit_type="xlsx_sheet_summary",
            text="シート",
            locator="sheet:Sheet1",
            source_unit_indices=(1,),
        ),
        _chunk(
            chunk_id="c3",
            relative_path="資料/report.pdf",
            parser_name="pdf",
            unit_type="pdf_page_ocr",
            text="画像文字",
            locator="page:2",
            source_unit_indices=(1,),
        ),
    )

    result = ChunkValidationService(max_chars=20).validate(
        chunks=chunks,
        source_documents=documents,
    )

    assert result.summary.errors == 0
    assert result.summary.warnings == 0
    assert result.summary.text_chunks == 3
    assert result.summary.table_chunks == 1
    assert result.summary.ocr_chunks == 1


def test_chunk_validation_reports_quality_gate_related_errors() -> None:
    """品質ゲートで止めるべき重複ID・空本文・参照不正を検出する。"""
    documents = (
        _source_document(
            relative_path="docs/a.pdf",
            parser_name="pdf",
            units=(_source_unit("pdf_page_text", "alpha", "page:1"),),
        ),
    )
    chunks = (
        _chunk(chunk_id="same", relative_path="docs/a.pdf", text="alpha"),
        _chunk(chunk_id="same", relative_path="docs/a.pdf", text="alpha"),
        _chunk(chunk_id="empty", relative_path="docs/a.pdf", text=" "),
        _chunk(chunk_id="missing-doc", relative_path="docs/missing.txt", text="x"),
        _chunk(
            chunk_id="missing-unit",
            relative_path="docs/a.pdf",
            text="x",
            source_unit_indices=(2,),
        ),
    )

    result = ChunkValidationService(max_chars=20).validate(
        chunks=chunks,
        source_documents=documents,
    )
    issue_types = {error.issue_type for error in result.errors}

    assert result.summary.duplicate_chunk_ids == 1
    assert result.summary.duplicate_chunk_contents == 1
    assert result.summary.empty_text_chunks == 1
    assert result.summary.invalid_document_references == 1
    assert result.summary.invalid_unit_references == 1
    assert "duplicate_chunk_id" in issue_types
    assert "duplicate_chunk_content" in issue_types


def test_chunk_validation_reports_text_locator_metadata_and_size_errors() -> None:
    """本文内容・locator・metadata・文字数の異常を分類して検出する。"""
    documents = (
        _source_document(
            relative_path="docs/a.pdf",
            parser_name="pdf",
            units=(_source_unit("pdf_page_text", "alpha", "page:1"),),
        ),
    )
    chunks = (
        _chunk(chunk_id="nul", relative_path="docs/a.pdf", text="a\x00b"),
        _chunk(chunk_id="abs", relative_path="C:/Users/name/file.txt", text="alpha"),
        _chunk(
            chunk_id="metadata-path",
            relative_path="docs/a.pdf",
            text="alpha",
            metadata={"source_path": "C:/Users/name/file.txt"},
        ),
        _chunk(
            chunk_id="json-pointer",
            relative_path="docs/a.pdf",
            text="alpha",
            metadata={"json_pointer": "/metrics/auc"},
        ),
        _chunk(
            chunk_id="locator",
            relative_path="docs/a.pdf",
            unit_type="pdf_page_text",
            text="alpha",
            locator="1",
        ),
        _chunk(
            chunk_id="metadata",
            relative_path="docs/a.pdf",
            text="alpha",
            metadata={"bad": math.inf},  # type: ignore[dict-item]
        ),
        _chunk(
            chunk_id="big",
            relative_path="docs/a.pdf",
            text="123456789012345678901234567890",
        ),
    )

    result = ChunkValidationService(max_chars=25).validate(
        chunks=chunks,
        source_documents=documents,
    )
    counts = {error.issue_type: 0 for error in result.errors}
    for error in result.errors:
        counts[error.issue_type] += 1

    assert counts["nul_text_chunk"] == 1
    assert counts["absolute_path_detected"] == 2
    assert counts["invalid_locator"] == 1
    assert counts["json_metadata_error"] == 1
    assert counts["oversized_chunk"] == 1


def _source_unit(
    unit_type: str = "text",
    text: str = "本文",
    locator: str | None = None,
) -> ChunkSourceUnit:
    return ChunkSourceUnit(
        unit_type=unit_type,
        text=text,
        locator=locator,
        metadata={},
    )


def _source_document(
    *,
    relative_path: str,
    parser_name: str,
    units: tuple[ChunkSourceUnit, ...],
) -> ChunkSourceDocument:
    return ChunkSourceDocument(
        relative_path=relative_path,
        name=relative_path.rsplit("/", maxsplit=1)[-1],
        suffix="." + relative_path.rsplit(".", maxsplit=1)[-1],
        size_bytes=10,
        parser_name=parser_name,
        units=units,
    )


def _chunk(
    *,
    chunk_id: str,
    relative_path: str,
    text: str,
    parser_name: str = "plain_text",
    unit_type: str = "text",
    locator: str | None = None,
    source_unit_indices: tuple[int, ...] = (0,),
    metadata: dict[str, object] | None = None,
) -> RetrievalChunk:
    return RetrievalChunk(
        chunk_id=chunk_id,
        relative_path=relative_path,
        parser_name=parser_name,
        unit_type=unit_type,
        text=text,
        locator=locator,
        source_unit_indices=source_unit_indices,
        chunk_index=0,
        metadata={} if metadata is None else metadata,  # type: ignore[arg-type]
    )
