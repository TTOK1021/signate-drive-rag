"""XLSXセル値を検索向けテキストへ正規化する処理。"""

import math
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation


def format_spreadsheet_value(value: object) -> str:
    """Excelセル値を検索可能な決定的文字列へ変換する。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _normalize_text(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _format_float(value)
    if isinstance(value, Decimal):
        return _format_decimal(value)
    return _normalize_text(str(value))


def format_formula_value(cached_value: object, formula: str) -> str:
    """数式と保存済み計算結果を同じセル表現へまとめる。"""
    normalized_formula = _normalize_text(formula)
    formatted_value = format_spreadsheet_value(cached_value)
    if formatted_value == "":
        return f"formula: {normalized_formula}"
    return f"{formatted_value} (formula: {normalized_formula})"


def escape_table_value(value: str) -> str:
    """表本文で列境界を壊さないようセル文字列を短く安全化する。"""
    return value.replace("|", r"\|").replace("\n", " / ")


def _normalize_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    return normalized.strip()


def _format_float(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    try:
        return _format_decimal(Decimal(str(value)))
    except InvalidOperation:
        return str(value)


def _format_decimal(value: Decimal) -> str:
    if value.is_nan():
        return "NaN"
    if value == Decimal("Infinity"):
        return "Infinity"
    if value == Decimal("-Infinity"):
        return "-Infinity"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text == "-0":
        return "0"
    return text
