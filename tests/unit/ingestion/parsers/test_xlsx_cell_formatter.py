"""XLSXセル値正規化の単体テスト。"""

import math
from datetime import date, datetime, time
from decimal import Decimal

from signate_drive_rag.ingestion.parsers.xlsx_cell_formatter import (
    escape_table_value,
    format_formula_value,
    format_spreadsheet_value,
)


def test_format_spreadsheet_value_handles_common_excel_values() -> None:
    """文字列、日本語、数値、日付、真偽値、Noneを決定的に文字列化する。"""
    assert format_spreadsheet_value(" 日本語\r\n本文\x00 ") == "日本語\n本文"
    assert format_spreadsheet_value(42) == "42"
    assert format_spreadsheet_value(Decimal("1.2300")) == "1.23"
    assert format_spreadsheet_value(date(2025, 4, 9)) == "2025-04-09"
    assert format_spreadsheet_value(datetime(2025, 4, 9, 10, 30)) == "2025-04-09T10:30:00"
    assert format_spreadsheet_value(time(10, 30)) == "10:30:00"
    assert format_spreadsheet_value(True) == "true"
    assert format_spreadsheet_value(False) == "false"
    assert format_spreadsheet_value(None) == ""


def test_format_spreadsheet_value_handles_float_special_values_and_errors() -> None:
    """小数を丸めず、NaN・Infinity・Excelエラー表記を明確に扱う。"""
    assert format_spreadsheet_value(0.0000123) == "0.0000123"
    assert format_spreadsheet_value(math.nan) == "NaN"
    assert format_spreadsheet_value(math.inf) == "Infinity"
    assert format_spreadsheet_value(-math.inf) == "-Infinity"
    assert format_spreadsheet_value("#DIV/0!") == "#DIV/0!"


def test_format_formula_value_includes_cached_value_when_available() -> None:
    """数式と保存済み計算結果を併記できる。"""
    assert format_formula_value(42, "=SUM(A1:A3)") == "42 (formula: =SUM(A1:A3))"
    assert format_formula_value(None, "=SUM(A1:A3)") == "formula: =SUM(A1:A3)"


def test_escape_table_value_preserves_cell_position_delimiter() -> None:
    """区切り記号とセル内改行が表本文の構造を壊さない。"""
    assert escape_table_value("A|B\nC") == r"A\|B / C"
