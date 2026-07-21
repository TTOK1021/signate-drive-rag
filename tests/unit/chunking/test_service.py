"""チャンク生成サービスの単体テスト。"""

import re

import pytest

from signate_drive_rag.chunking.models import ChunkSourceDocument, ChunkSourceUnit
from signate_drive_rag.chunking.service import ChunkingService, generate_chunk_id


def unit(
    text: str,
    *,
    unit_type: str = "text",
    locator: str | None = None,
    metadata: dict[str, object] | None = None,
) -> ChunkSourceUnit:
    """テスト用unitを作成する。"""
    return ChunkSourceUnit(
        unit_type=unit_type,
        text=text,
        locator=locator,
        metadata={} if metadata is None else metadata,  # type: ignore[arg-type]
    )


def document(
    relative_path: str,
    *,
    parser_name: str = "plain_text",
    units: tuple[ChunkSourceUnit, ...],
) -> ChunkSourceDocument:
    """テスト用documentを作成する。"""
    return ChunkSourceDocument(
        relative_path=relative_path,
        name=relative_path.rsplit("/", maxsplit=1)[-1],
        suffix="." + relative_path.rsplit(".", maxsplit=1)[-1],
        size_bytes=100,
        parser_name=parser_name,
        units=units,
    )


def test_chunking_service_chunks_plain_text_and_assigns_indexes() -> None:
    """PlainTextの小さいunitと大きいunitをチャンク化し連番を付ける。"""
    result = ChunkingService(max_chars=5, overlap_chars=1).chunk(
        [document("b.txt", units=(unit("abc\ndef"),))]
    )

    assert [chunk.chunk_index for chunk in result.chunks] == [0, 1]
    assert result.chunks[0].source_unit_indices == (0,)
    assert result.chunks[0].locator == "line:1-2"
    assert all(len(chunk.text) <= 5 for chunk in result.chunks)


def test_chunking_service_preserves_markdown_metadata_and_locator() -> None:
    """Markdownの見出しmetadataとlocatorを保持する。"""
    result = ChunkingService(max_chars=20, overlap_chars=0).chunk(
        [
            document(
                "a.md",
                parser_name="markdown",
                units=(
                    unit(
                        "# 見出し\n本文",
                        unit_type="markdown_section",
                        locator="line:1-2",
                        metadata={"heading_path": ["見出し"], "heading": "見出し"},
                    ),
                ),
            )
        ]
    )

    assert result.chunks[0].locator == "line:1-2"
    assert result.chunks[0].metadata["heading_path"] == ["見出し"]
    assert "# 見出し" in result.chunks[0].text


def test_chunking_service_chunks_json_values_independently_by_locator() -> None:
    """同じJSON値でもJSON Pointerが異なれば別チャンクにする。"""
    result = ChunkingService(max_chars=10, overlap_chars=0).chunk(
        [
            document(
                "a.json",
                parser_name="json",
                units=(
                    unit(
                        "same",
                        unit_type="json_value",
                        locator="/a",
                        metadata={"json_pointer": "/a"},
                    ),
                    unit(
                        "same",
                        unit_type="json_value",
                        locator="/b",
                        metadata={"json_pointer": "/b"},
                    ),
                    unit(
                        "long-value",
                        unit_type="json_value",
                        locator="",
                        metadata={"json_pointer": ""},
                    ),
                ),
            )
        ]
    )

    assert [chunk.locator for chunk in result.chunks[:2]] == ["/a", "/b"]
    assert result.chunks[0].chunk_id != result.chunks[1].chunk_id
    assert result.chunks[2].locator == ""


def test_chunking_service_chunks_notebook_cells_outputs_and_skips_empty() -> None:
    """Notebookセルと出力をチャンク化し、空セルはissueとしてスキップする。"""
    result = ChunkingService(max_chars=4, overlap_chars=0).chunk(
        [
            document(
                "a.ipynb",
                parser_name="notebook",
                units=(
                    unit(
                        "code",
                        unit_type="notebook_cell",
                        locator="cell:0",
                        metadata={"cell_index": 0},
                    ),
                    unit(
                        "output",
                        unit_type="notebook_output",
                        locator="cell:0/output:0",
                        metadata={"output_index": 0},
                    ),
                    unit("", unit_type="notebook_cell", locator="cell:1"),
                ),
            )
        ]
    )

    assert all(len(chunk.text) <= 4 for chunk in result.chunks)
    assert result.summary.issues_by_type["empty_source_unit_skipped"] == 1
    assert result.chunks[0].metadata["cell_index"] == 0
    assert result.chunks[-1].metadata["output_index"] == 0


def test_chunking_service_groups_table_rows_and_reduces_repeated_headers() -> None:
    """CSV・TSV行をまとめ、ヘッダーを1回だけ記載する。"""
    result = ChunkingService(max_chars=100, overlap_chars=0, table_max_rows=2).chunk(
        [
            document(
                "table.csv",
                parser_name="delimited_text",
                units=(
                    unit(
                        "A | B",
                        unit_type="table_header",
                        locator="row:1",
                        metadata={"headers": ["A", "B"], "delimiter": ","},
                    ),
                    unit(
                        "A=あ | B=",
                        unit_type="table_row",
                        locator="row:2",
                        metadata={"values": ["あ", ""], "logical_row_number": 2},
                    ),
                    unit(
                        "A=い | B=2",
                        unit_type="table_row",
                        locator="row:3",
                        metadata={"values": ["い", "2"], "logical_row_number": 3},
                    ),
                    unit(
                        "A=う | B=3",
                        unit_type="table_row",
                        locator="row:4",
                        metadata={"values": ["う", "3"], "logical_row_number": 4},
                    ),
                ),
            )
        ]
    )

    assert len(result.chunks) == 2
    assert result.chunks[0].text.count("列: A | B") == 1
    assert "行2: あ | " in result.chunks[0].text
    assert result.chunks[0].locator == "row:2-3"
    assert result.chunks[0].source_unit_indices == (0, 1, 2)
    assert result.chunks[0].metadata["row_count"] == 2


def test_chunking_service_chunks_office_text_table_and_pdf_page_units() -> None:
    """Office本文・表、PDFページを既存チャンク形式へ接続できる。"""
    result = ChunkingService(max_chars=20, overlap_chars=0, table_max_rows=10).chunk(
        [
            document(
                "office.docx",
                parser_name="docling_docx",
                units=(
                    unit(
                        "見出し配下の本文",
                        unit_type="docx_paragraph",
                        locator="item:2",
                        metadata={"heading_path": ["見出し"]},
                    ),
                    unit(
                        "| A | B |\n| --- | --- |\n| あ | 1 |",
                        unit_type="docx_table",
                        locator="table:1",
                        metadata={"headers": ["A", "B"]},
                    ),
                    unit(
                        "行2: あ | 1",
                        unit_type="docx_table_row",
                        locator="table:1/row:2",
                        metadata={"values": ["あ", "1"], "logical_row_number": 2},
                    ),
                ),
            ),
            document(
                "slides.pptx",
                parser_name="docling_pptx",
                units=(
                    unit(
                        "スライド1本文",
                        unit_type="pptx_slide_text",
                        locator="slide:1/item:1",
                        metadata={"slide_number": 1},
                    ),
                    unit(
                        "スライド2本文",
                        unit_type="pptx_slide_text",
                        locator="slide:2/item:2",
                        metadata={"slide_number": 2},
                    ),
                    unit(
                        "| A |\n| --- |\n| B |",
                        unit_type="pptx_slide_table",
                        locator="slide:2/table:1",
                        metadata={"headers": ["A"], "slide_number": 2},
                    ),
                    unit(
                        "行2: B",
                        unit_type="pptx_slide_table_row",
                        locator="slide:2/table:1/row:2",
                        metadata={"values": ["B"], "logical_row_number": 2},
                    ),
                ),
            ),
            document(
                "paper.pdf",
                parser_name="pypdf",
                units=(
                    unit("ページ1本文", unit_type="pdf_page_text", locator="page:1"),
                    unit("ページ2本文" * 5, unit_type="pdf_page_text", locator="page:2"),
                ),
            ),
            document(
                "book.xlsx",
                parser_name="openpyxl_xlsx",
                units=(
                    unit(
                        "Excelワークブック",
                        unit_type="xlsx_workbook_summary",
                        locator="workbook",
                    ),
                    unit(
                        "シート名: 集計",
                        unit_type="xlsx_sheet_summary",
                        locator="sheet:集計",
                    ),
                    unit(
                        "シート: 集計\n範囲: A1:B2\n列: A | B\n行1: A | B\n行2: 1 | 2",
                        unit_type="xlsx_table_rows",
                        locator="sheet:集計/range:A1:B2",
                        metadata={"sheet_name": "集計", "range": "A1:B2"},
                    ),
                ),
            ),
        ]
    )

    by_path = {(chunk.relative_path, chunk.locator): chunk for chunk in result.chunks}
    assert by_path[("office.docx", "item:2")].metadata["heading_path"] == ["見出し"]
    assert by_path[("office.docx", "table:1/row:2-2")].unit_type == "table_rows"
    assert by_path[("slides.pptx", "slide:2/table:1/row:2-2")].unit_type == "table_rows"
    assert by_path[("paper.pdf", "page:1")].metadata["source_locator"] == "page:1"
    assert by_path[("book.xlsx", "sheet:集計/range:A1:B2")].metadata["sheet_name"] == "集計"
    assert by_path[("book.xlsx", "sheet:集計/range:A1:B2")].metadata["range"] == "A1:B2"
    assert all(
        chunk.locator in {"slide:1/item:1", "slide:2/item:2"}
        for chunk in result.chunks
        if chunk.relative_path == "slides.pptx" and chunk.unit_type == "pptx_slide_text"
    )


def test_chunking_service_handles_header_only_and_large_table_row() -> None:
    """ヘッダーだけの表と巨大な1行を処理できる。"""
    header_only = document(
        "header.csv",
        parser_name="delimited_text",
        units=(
            unit(
                "A | B", unit_type="table_header", locator="row:1", metadata={"headers": ["A", "B"]}
            ),
        ),
    )
    large_row = document(
        "large.csv",
        parser_name="delimited_text",
        units=(
            unit("A", unit_type="table_header", locator="row:1", metadata={"headers": ["A"]}),
            unit(
                "A=abcdef",
                unit_type="table_row",
                locator="row:2",
                metadata={"values": ["abcdef"], "logical_row_number": 2},
            ),
        ),
    )

    result = ChunkingService(max_chars=8, overlap_chars=0).chunk([header_only, large_row])

    assert any(chunk.relative_path == "header.csv" for chunk in result.chunks)
    assert all(len(chunk.text) <= 8 for chunk in result.chunks)
    assert any(
        chunk.metadata.get("split_count")
        for chunk in result.chunks
        if chunk.relative_path == "large.csv"
    )


def test_chunking_service_falls_back_for_missing_table_metadata_and_unknown_unit() -> None:
    """表metadata不足と未知unit_typeをissueへ記録し、本文は失わない。"""
    result = ChunkingService(max_chars=20, overlap_chars=0).chunk(
        [
            document(
                "bad.csv",
                parser_name="delimited_text",
                units=(unit("A | B", unit_type="table_header", locator="row:1"),),
            ),
            document(
                "unknown.bin", parser_name="custom", units=(unit("body", unit_type="custom_unit"),)
            ),
        ]
    )

    assert result.summary.issues_by_type["table_metadata_missing"] >= 1
    assert result.summary.issues_by_type["fallback_chunking_used"] == 1
    assert any(chunk.text == "body" for chunk in result.chunks)


def test_chunking_service_handles_empty_document_and_empty_unit() -> None:
    """空文書と空unitをissueへ記録し、空チャンクは作らない。"""
    result = ChunkingService().chunk(
        [
            document("empty.md", parser_name="markdown", units=()),
            document("empty-unit.txt", units=(unit(""),)),
        ]
    )

    assert result.chunks == ()
    assert result.summary.issues_by_type["source_document_has_no_units"] == 1
    assert result.summary.issues_by_type["empty_source_unit_skipped"] == 1


def test_chunking_service_builds_summary_and_deterministic_order() -> None:
    """summaryを集計し、relative_path順で出力する。"""
    documents = [
        document("b.txt", units=(unit("bbb"),)),
        document(
            "a.md",
            parser_name="markdown",
            units=(unit("aa", unit_type="markdown_section", locator="line:1-1"),),
        ),
    ]

    first = ChunkingService(max_chars=10, overlap_chars=0).chunk(documents)
    second = ChunkingService(max_chars=10, overlap_chars=0).chunk(documents)

    assert [chunk.relative_path for chunk in first.chunks] == ["a.md", "b.txt"]
    assert [chunk.chunk_id for chunk in first.chunks] == [chunk.chunk_id for chunk in second.chunks]
    assert first.summary.source_documents == 2
    assert first.summary.generated_chunks == len(first.chunks)
    assert first.summary.maximum_chunk_characters == 3
    assert first.summary.by_parser["plain_text"]["generated_chunks"] == 1
    assert first.summary.by_unit_type["text"]["source_units"] == 1


def test_generate_chunk_id_is_deterministic_and_sensitive_to_source_fields() -> None:
    """chunk_idは決定的で、本文やlocatorやrelative_pathの差を反映する。"""
    base = {
        "relative_path": "a.txt",
        "parser_name": "plain_text",
        "unit_type": "text",
        "locator": None,
        "source_unit_indices": (0,),
        "chunk_index": 0,
        "text": "abc",
    }

    chunk_id = generate_chunk_id(**base)

    assert chunk_id == generate_chunk_id(**base)
    assert re.fullmatch(r"[0-9a-f]{64}", chunk_id)
    assert chunk_id != generate_chunk_id(**{**base, "text": "abcd"})
    assert chunk_id != generate_chunk_id(**{**base, "locator": "line:1-1"})
    assert chunk_id != generate_chunk_id(**{**base, "relative_path": "b.txt"})


def test_chunking_service_rejects_invalid_options() -> None:
    """不正なチャンク生成設定では例外になる。"""
    with pytest.raises(ValueError):
        ChunkingService(max_chars=0)
    with pytest.raises(ValueError):
        ChunkingService(max_chars=10, overlap_chars=10)
    with pytest.raises(ValueError):
        ChunkingService(table_max_rows=0)
