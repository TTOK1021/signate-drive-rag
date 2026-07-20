"""XLSX行データを位置追跡可能な行ブロックへ分割する処理。"""

import hashlib
from dataclasses import dataclass
from typing import cast

from signate_drive_rag.domain import ExtractedUnit, JsonValue
from signate_drive_rag.ingestion.parsers.xlsx_adapter import (
    SheetInspection,
    SpreadsheetCell,
    SpreadsheetRow,
    XlsxParserOptions,
    XlsxTableInfo,
    column_letter,
    range_boundaries,
)
from signate_drive_rag.ingestion.parsers.xlsx_cell_formatter import (
    escape_table_value,
    format_formula_value,
    format_spreadsheet_value,
)


@dataclass(frozen=True, slots=True)
class XlsxBlockBuildResult:
    """シートから生成した行ブロックと集計情報。"""

    units: tuple[ExtractedUnit, ...]
    formula_without_cached_value_count: int
    large_cell_value_count: int


@dataclass(frozen=True, slots=True)
class _FormattedCell:
    row_number: int
    column_number: int
    coordinate: str
    text: str
    has_formula: bool
    has_missing_formula_cache: bool


def build_xlsx_row_block_units(
    *,
    rows: tuple[SpreadsheetRow, ...],
    sheet: SheetInspection,
    formulas: dict[str, str],
    options: XlsxParserOptions,
) -> XlsxBlockBuildResult:
    """空行で領域を分け、行・列・文字数の上限内でunitを生成する。"""
    units: list[ExtractedUnit] = []
    formula_without_cached_value_count = 0
    large_cell_value_count = 0
    current_region: list[list[_FormattedCell]] = []

    for row in rows:
        formatted_row = [_format_cell(cell, formulas) for cell in row.cells]
        formula_without_cached_value_count += sum(
            1 for cell in formatted_row if cell.has_missing_formula_cache
        )
        large_cell_value_count += sum(
            1 for cell in formatted_row if len(cell.text) > options.large_cell_value_characters
        )
        if _row_is_empty(formatted_row):
            units.extend(_region_units(current_region, sheet=sheet, options=options))
            current_region = []
            continue
        current_region.append(formatted_row)
    units.extend(_region_units(current_region, sheet=sheet, options=options))
    return XlsxBlockBuildResult(
        units=tuple(units),
        formula_without_cached_value_count=formula_without_cached_value_count,
        large_cell_value_count=large_cell_value_count,
    )


def _format_cell(cell: SpreadsheetCell, formulas: dict[str, str]) -> _FormattedCell:
    row_number = cell.row_number
    column_number = cell.column_number
    coordinate = cell.coordinate
    value = cell.value
    formula = formulas.get(coordinate)
    if formula is None:
        return _FormattedCell(
            row_number=row_number,
            column_number=column_number,
            coordinate=coordinate,
            text=format_spreadsheet_value(value),
            has_formula=False,
            has_missing_formula_cache=False,
        )
    return _FormattedCell(
        row_number=row_number,
        column_number=column_number,
        coordinate=coordinate,
        text=format_formula_value(value, formula),
        has_formula=True,
        has_missing_formula_cache=format_spreadsheet_value(value) == "",
    )


def _row_is_empty(row: list[_FormattedCell]) -> bool:
    return all(cell.text == "" for cell in row)


def _region_units(
    region_rows: list[list[_FormattedCell]],
    *,
    sheet: SheetInspection,
    options: XlsxParserOptions,
) -> list[ExtractedUnit]:
    if not region_rows:
        return []
    min_column, max_column = _trimmed_column_bounds(region_rows)
    if min_column is None or max_column is None:
        return []

    units: list[ExtractedUnit] = []
    header_row_number, header_inferred = _infer_header(region_rows, min_column, max_column)
    column_start = min_column
    while column_start <= max_column:
        column_end = min(max_column, column_start + options.max_columns_per_unit - 1)
        row_start_index = 0
        while row_start_index < len(region_rows):
            row_limit = _row_limit(column_end - column_start + 1, options)
            row_end_index = min(len(region_rows), row_start_index + row_limit)
            unit = _fit_text_unit(
                region_rows[row_start_index:row_end_index],
                sheet=sheet,
                start_column=column_start,
                end_column=column_end,
                header_row_number=header_row_number,
                header_inferred=header_inferred,
                options=options,
            )
            units.append(unit)
            row_count_value = unit.metadata["row_count"]
            row_start_index += (
                row_count_value
                if isinstance(row_count_value, int)
                else row_end_index - row_start_index
            )
        column_start = column_end + 1
    return units


def _row_limit(column_count: int, options: XlsxParserOptions) -> int:
    return max(1, min(options.max_rows_per_unit, options.max_cells_per_unit // column_count))


def _fit_text_unit(
    rows: list[list[_FormattedCell]],
    *,
    sheet: SheetInspection,
    start_column: int,
    end_column: int,
    header_row_number: int | None,
    header_inferred: bool,
    options: XlsxParserOptions,
) -> ExtractedUnit:
    current_rows = rows
    while len(current_rows) > 1:
        candidate = _row_block_unit(
            current_rows,
            sheet=sheet,
            start_column=start_column,
            end_column=end_column,
            header_row_number=header_row_number,
            header_inferred=header_inferred,
        )
        if len(candidate.text) <= options.max_characters_per_unit:
            return candidate
        current_rows = current_rows[: max(1, len(current_rows) // 2)]
    return _row_block_unit(
        current_rows,
        sheet=sheet,
        start_column=start_column,
        end_column=end_column,
        header_row_number=header_row_number,
        header_inferred=header_inferred,
    )


def _row_block_unit(
    rows: list[list[_FormattedCell]],
    *,
    sheet: SheetInspection,
    start_column: int,
    end_column: int,
    header_row_number: int | None,
    header_inferred: bool,
) -> ExtractedUnit:
    start_row = rows[0][0].row_number
    end_row = rows[-1][0].row_number
    start_cell = f"{column_letter(start_column)}{start_row}"
    end_cell = f"{column_letter(end_column)}{end_row}"
    range_text = f"{start_cell}:{end_cell}"
    lines = [
        f"シート: {sheet.sheet_name}",
        f"範囲: {range_text}",
        "列: "
        + " | ".join(column_letter(column) for column in range(start_column, end_column + 1)),
    ]
    for row in rows:
        values = _row_values(row, start_column, end_column)
        lines.append(f"行{row[0].row_number}: {' | '.join(values)}")
    merged_ranges = _intersecting_ranges(sheet.merged_ranges, range_text)
    if merged_ranges:
        lines.append(f"結合セル: {', '.join(merged_ranges)}")
    text = "\n".join(lines)
    hidden_columns = tuple(
        column for column in sheet.hidden_columns if start_column <= column <= end_column
    )
    hidden_rows = tuple(row for row in sheet.hidden_rows if start_row <= row <= end_row)
    table = _matching_table(sheet.tables, range_text)
    metadata: dict[str, JsonValue] = {
        "sheet_name": sheet.sheet_name,
        "sheet_index": sheet.sheet_index,
        "sheet_state": sheet.sheet_state,
        "start_row": start_row,
        "end_row": end_row,
        "start_column": start_column,
        "end_column": end_column,
        "start_cell": start_cell,
        "end_cell": end_cell,
        "range": range_text,
        "row_count": len(rows),
        "column_count": end_column - start_column + 1,
        "non_empty_cell_count": sum(
            1 for row in rows for value in _row_values(row, start_column, end_column) if value != ""
        ),
        "header_row_number": header_row_number,
        "header_inferred": header_inferred,
        "table_name": None if table is None else table.table_name,
        "table_range": None if table is None else table.range,
        "formula_cell_count": sum(
            1
            for row in rows
            for cell in row
            if cell.has_formula and start_column <= cell.column_number <= end_column
        ),
        "merged_ranges": list(merged_ranges),
        "contains_hidden_rows": len(hidden_rows) > 0,
        "contains_hidden_columns": len(hidden_columns) > 0,
        "hidden_row_count": len(hidden_rows),
        "hidden_column_count": len(hidden_columns),
        "headers": _json_list(
            [column_letter(column) for column in range(start_column, end_column + 1)]
        ),
        "values": _json_list(_row_values(rows[0], start_column, end_column)),
        "logical_row_number": start_row,
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    if table is not None:
        metadata["header_row_number"] = table.header_row
        metadata["table_display_name"] = table.display_name
    return ExtractedUnit(
        unit_type="xlsx_table_rows",
        text=text,
        locator=f"sheet:{sheet.sheet_name}/range:{range_text}",
        metadata=metadata,
    )


def _trimmed_column_bounds(rows: list[list[_FormattedCell]]) -> tuple[int | None, int | None]:
    non_empty_columns = [cell.column_number for row in rows for cell in row if cell.text != ""]
    if not non_empty_columns:
        return None, None
    return min(non_empty_columns), max(non_empty_columns)


def _row_values(row: list[_FormattedCell], start_column: int, end_column: int) -> list[str]:
    text_by_column = {cell.column_number: cell.text for cell in row}
    return [
        escape_table_value(text_by_column.get(column_number, ""))
        for column_number in range(start_column, end_column + 1)
    ]


def _infer_header(
    region_rows: list[list[_FormattedCell]],
    min_column: int,
    max_column: int,
) -> tuple[int | None, bool]:
    if len(region_rows) < 2:
        return None, False
    first_values = [value for value in _row_values(region_rows[0], min_column, max_column) if value]
    if len(first_values) < 2:
        return None, False
    string_like = sum(
        1 for value in first_values if any(character.isalpha() for character in value)
    )
    unique_ratio = len(set(first_values)) / len(first_values)
    if string_like / len(first_values) >= 0.5 and unique_ratio >= 0.8:
        return region_rows[0][0].row_number, True
    return None, False


def _intersecting_ranges(ranges: tuple[str, ...], target_range: str) -> tuple[str, ...]:
    target = range_boundaries(target_range)
    if target is None:
        return ()
    return tuple(
        range_text
        for range_text in ranges
        if _ranges_intersect(target, range_boundaries(range_text))
    )


def _matching_table(tables: tuple[XlsxTableInfo, ...], target_range: str) -> XlsxTableInfo | None:
    target = range_boundaries(target_range)
    if target is None:
        return None
    for table in tables:
        if _ranges_intersect(target, range_boundaries(table.range)):
            return table
    return None


def _ranges_intersect(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int] | None,
) -> bool:
    if second is None:
        return False
    first_min_col, first_min_row, first_max_col, first_max_row = first
    second_min_col, second_min_row, second_max_col, second_max_row = second
    return not (
        first_max_col < second_min_col
        or second_max_col < first_min_col
        or first_max_row < second_min_row
        or second_max_row < first_min_row
    )


def _json_list(values: list[str]) -> list[JsonValue]:
    return cast(list[JsonValue], list(values))
