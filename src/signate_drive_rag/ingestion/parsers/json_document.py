"""JSONファイルをJSON Pointer単位で抽出するパーサー。"""

import json
from collections.abc import Iterator
from typing import Any

from signate_drive_rag.domain.extracted_document import ExtractedDocument, ExtractedUnit
from signate_drive_rag.domain.source_file import SourceFile


class JsonDocumentParser:
    """JSONの末端値と空コンテナを抽出する。"""

    SUPPORTED_SUFFIXES = frozenset({".json"})

    @property
    def name(self) -> str:
        """パーサーを識別する名前を返す。"""
        return "json"

    def supports(self, source_file: SourceFile) -> bool:
        """対象ファイルを処理できるか判定する。"""
        return source_file.suffix.lower() in self.SUPPORTED_SUFFIXES

    def parse(self, source_file: SourceFile) -> ExtractedDocument:
        """JSONファイルをJSON Pointer付きの値へ分解する。"""
        with source_file.path.open("r", encoding="utf-8") as source_stream:
            json_value = json.load(source_stream)

        units = tuple(_iter_json_units(json_value, pointer=""))
        return ExtractedDocument(source_file=source_file, parser_name=self.name, units=units)


def _iter_json_units(value: Any, pointer: str) -> Iterator[ExtractedUnit]:
    """JSONの抽出順を入力順に保ちながら末端値を走査する。"""
    if isinstance(value, dict):
        if not value:
            yield _json_unit(pointer, "{}", "object")
            return
        for key, child_value in value.items():
            yield from _iter_json_units(child_value, _join_pointer(pointer, str(key)))
        return

    if isinstance(value, list):
        if not value:
            yield _json_unit(pointer, "[]", "array")
            return
        for index, child_value in enumerate(value):
            yield from _iter_json_units(child_value, _join_pointer(pointer, str(index)))
        return

    text, value_type = _json_scalar_text_and_type(value)
    yield _json_unit(pointer, text, value_type)


def _json_scalar_text_and_type(value: Any) -> tuple[str, str]:
    """JSONスカラーをJSON表現に近い文字列と型名へ変換する。"""
    if isinstance(value, str):
        return value, "string"
    if isinstance(value, bool):
        return ("true" if value else "false"), "boolean"
    if value is None:
        return "null", "null"
    if isinstance(value, int):
        return str(value), "integer"
    if isinstance(value, float):
        return str(value), "number"
    raise TypeError(f"対応していないJSON値です: {type(value).__name__}")


def _json_unit(pointer: str, text: str, value_type: str) -> ExtractedUnit:
    """JSON値を共通抽出単位へ変換する。"""
    return ExtractedUnit(
        unit_type="json_value",
        text=text,
        locator=pointer,
        metadata={
            "json_pointer": pointer,
            "value_type": value_type,
        },
    )


def _join_pointer(parent_pointer: str, token: str) -> str:
    """JSON Pointer仕様に沿ってパス要素を結合する。"""
    escaped_token = token.replace("~", "~0").replace("/", "~1")
    return f"{parent_pointer}/{escaped_token}" if parent_pointer else f"/{escaped_token}"
