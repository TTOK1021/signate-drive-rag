"""抽出済みdocuments.jsonlを監査用モデルへ読み込む処理。"""

import json
from pathlib import Path
from typing import Any, cast

from signate_drive_rag.audit.models import AuditDocument, AuditUnit
from signate_drive_rag.domain.extracted_document import JsonValue


class AuditInputError(ValueError):
    """監査入力JSONLが不正な場合の例外。"""


def load_audit_documents(documents_path: Path) -> tuple[AuditDocument, ...]:
    """documents.jsonlを読み込み、監査用文書へ変換する。"""
    if not documents_path.exists():
        raise AuditInputError(f"入力ファイルが存在しません: {documents_path}")
    if not documents_path.is_file():
        raise AuditInputError(f"入力パスがファイルではありません: {documents_path}")

    documents: list[AuditDocument] = []
    with documents_path.open("r", encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            if line.strip() == "":
                raise AuditInputError(
                    f"{documents_path}:{line_number}: 空行または空白行は使用できません。"
                )
            documents.append(_parse_document_line(line, documents_path, line_number))

    return tuple(documents)


def _parse_document_line(line: str, documents_path: Path, line_number: int) -> AuditDocument:
    """JSONLの1行を監査用文書へ変換する。"""
    try:
        record = json.loads(line)
    except json.JSONDecodeError as error:
        raise AuditInputError(
            f"{documents_path}:{line_number}: JSONとして不正です: {error.msg}"
        ) from error

    record_mapping = _require_mapping(record, documents_path, line_number, "<root>")
    source = _require_mapping(
        _required(record_mapping, "source", documents_path, line_number),
        documents_path,
        line_number,
        "source",
    )
    parser_name = _require_str(record_mapping, "parser_name", documents_path, line_number)
    units_value = _required(record_mapping, "units", documents_path, line_number)
    if not isinstance(units_value, list):
        raise _field_error(documents_path, line_number, "units", "配列である必要があります。")

    _validate_optional_mime_type(source, documents_path, line_number)
    _require_str(source, "modified_at", documents_path, line_number)

    units = tuple(
        _parse_unit(unit_value, documents_path, line_number, unit_index)
        for unit_index, unit_value in enumerate(units_value)
    )
    return AuditDocument(
        relative_path=_require_str(source, "relative_path", documents_path, line_number),
        name=_require_str(source, "name", documents_path, line_number),
        suffix=_require_str(source, "suffix", documents_path, line_number),
        size_bytes=_require_int(source, "size_bytes", documents_path, line_number),
        parser_name=parser_name,
        units=units,
    )


def _parse_unit(
    unit_value: Any,
    documents_path: Path,
    line_number: int,
    unit_index: int,
) -> AuditUnit:
    """unitオブジェクトを監査用抽出単位へ変換する。"""
    field_prefix = f"units[{unit_index}]"
    unit = _require_mapping(unit_value, documents_path, line_number, field_prefix)
    locator = _required(unit, "locator", documents_path, line_number)
    if locator is not None and not isinstance(locator, str):
        raise _field_error(
            documents_path,
            line_number,
            f"{field_prefix}.locator",
            "文字列またはnullである必要があります。",
        )
    metadata = _require_mapping(
        _required(unit, "metadata", documents_path, line_number),
        documents_path,
        line_number,
        f"{field_prefix}.metadata",
    )
    return AuditUnit(
        unit_type=_require_str(unit, "unit_type", documents_path, line_number),
        text=_require_str(unit, "text", documents_path, line_number),
        locator=locator,
        metadata=cast(dict[str, JsonValue], metadata),
    )


def _required(
    mapping: dict[str, Any],
    field_name: str,
    documents_path: Path,
    line_number: int,
) -> Any:
    """必須フィールドの存在を確認して値を返す。"""
    if field_name not in mapping:
        raise _field_error(documents_path, line_number, field_name, "必須フィールドがありません。")
    return mapping[field_name]


def _require_str(
    mapping: dict[str, Any],
    field_name: str,
    documents_path: Path,
    line_number: int,
) -> str:
    """必須文字列フィールドを取得する。"""
    value = _required(mapping, field_name, documents_path, line_number)
    if not isinstance(value, str):
        raise _field_error(documents_path, line_number, field_name, "文字列である必要があります。")
    return value


def _require_int(
    mapping: dict[str, Any],
    field_name: str,
    documents_path: Path,
    line_number: int,
) -> int:
    """必須整数フィールドを取得する。"""
    value = _required(mapping, field_name, documents_path, line_number)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _field_error(documents_path, line_number, field_name, "整数である必要があります。")
    return value


def _require_mapping(
    value: Any,
    documents_path: Path,
    line_number: int,
    field_name: str,
) -> dict[str, Any]:
    """JSONオブジェクトを辞書として取得する。"""
    if not isinstance(value, dict):
        raise _field_error(
            documents_path,
            line_number,
            field_name,
            "オブジェクトである必要があります。",
        )
    return value


def _validate_optional_mime_type(
    source: dict[str, Any],
    documents_path: Path,
    line_number: int,
) -> None:
    """既存documents.jsonlのsource.mime_type形式を検証する。"""
    mime_type = _required(source, "mime_type", documents_path, line_number)
    if mime_type is not None and not isinstance(mime_type, str):
        raise _field_error(
            documents_path,
            line_number,
            "mime_type",
            "文字列またはnullである必要があります。",
        )


def _field_error(
    documents_path: Path,
    line_number: int,
    field_name: str,
    reason: str,
) -> AuditInputError:
    """入力位置とフィールド名を含む監査入力例外を作成する。"""
    return AuditInputError(f"{documents_path}:{line_number}: {field_name}: {reason}")
