"""XLSX行ブロック分割の単体テスト。"""

from signate_drive_rag.ingestion.parsers.xlsx_adapter import (
    SheetInspection,
    SpreadsheetCell,
    SpreadsheetRow,
    XlsxParserOptions,
)
from signate_drive_rag.ingestion.parsers.xlsx_region_builder import build_xlsx_row_block_units


def row(row_number: int, values: list[object]) -> SpreadsheetRow:
    """テスト用行を作成する。"""
    return SpreadsheetRow(
        sheet_name="集計",
        row_number=row_number,
        cells=tuple(
            SpreadsheetCell(
                row_number=row_number,
                column_number=index,
                coordinate=f"{chr(64 + index)}{row_number}",
                value=value,
            )
            for index, value in enumerate(values, start=1)
        ),
    )


def sheet() -> SheetInspection:
    """テスト用シート診断を作成する。"""
    return SheetInspection(
        sheet_name="集計",
        sheet_index=1,
        sheet_state="visible",
        declared_dimension="A1:Z30",
        actual_dimension="A1:Z30",
        min_row=1,
        max_row=30,
        min_column=1,
        max_column=26,
        non_empty_cell_count=1,
        formula_cell_count=0,
        merged_ranges=("A1:B1",),
        tables=(),
        hidden_rows=(2,),
        hidden_columns=(3,),
    )


def test_build_xlsx_row_block_units_splits_rows_columns_and_empty_regions() -> None:
    """空行で領域を分け、25行・20列上限で分割できる。"""
    rows = tuple(
        [row(1, ["H1", "H2", "", "H4"])]
        + [row(index, [f"R{index}C{column}" for column in range(1, 27)]) for index in range(2, 28)]
        + [row(28, ["", "", "", ""])]
        + [row(29, ["A", "", "C", ""])]
    )

    result = build_xlsx_row_block_units(
        rows=rows,
        sheet=sheet(),
        formulas={},
        options=XlsxParserOptions(),
    )

    assert len(result.units) >= 4
    assert all(unit.metadata["row_count"] <= 25 for unit in result.units)
    assert all(unit.metadata["column_count"] <= 20 for unit in result.units)
    assert result.units[0].metadata["header_inferred"] is True
    assert result.units[-1].metadata["start_column"] == 1
    assert result.units[-1].metadata["end_column"] == 3
    assert "行28" not in result.units[-1].text
    assert result.units[0].locator.startswith("sheet:集計/range:")


def test_build_xlsx_row_block_units_reduces_rows_when_text_is_large() -> None:
    """文字数上限を超える場合は行数を減らして再分割する。"""
    rows = tuple(row(index, ["見出し", "x" * 100]) for index in range(1, 6))

    result = build_xlsx_row_block_units(
        rows=rows,
        sheet=sheet(),
        formulas={},
        options=XlsxParserOptions(max_characters_per_unit=180),
    )

    assert len(result.units) > 1
    assert all(unit.metadata["row_count"] < 5 for unit in result.units)


def test_build_xlsx_row_block_units_keeps_long_single_cell_without_truncation() -> None:
    """1セルだけが長い場合も切り捨てず、長大セル件数を集計する。"""
    result = build_xlsx_row_block_units(
        rows=(row(1, ["x" * 50]),),
        sheet=sheet(),
        formulas={},
        options=XlsxParserOptions(max_characters_per_unit=20, large_cell_value_characters=10),
    )

    assert "x" * 50 in result.units[0].text
    assert result.large_cell_value_count == 1


def test_build_xlsx_row_block_units_includes_formula_and_missing_cache_count() -> None:
    """数式とキャッシュ欠落件数を行ブロックへ反映できる。"""
    result = build_xlsx_row_block_units(
        rows=(row(1, [None]), row(2, [10])),
        sheet=sheet(),
        formulas={"A1": "=SUM(A2:A3)"},
        options=XlsxParserOptions(),
    )

    assert "formula: =SUM(A2:A3)" in result.units[0].text
    assert result.formula_without_cached_value_count == 1
