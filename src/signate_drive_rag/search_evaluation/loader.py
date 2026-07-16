"""検索評価用JSONLを読み込む処理。"""

import hashlib
import json
from pathlib import Path
from typing import Any

from signate_drive_rag.search_evaluation.models import (
    ExpectedRelevantResult,
    SearchEvaluationQuery,
)


class SearchEvaluationInputError(ValueError):
    """検索評価入力JSONLが不正な場合の例外。"""


def calculate_query_file_sha256(path: Path) -> str:
    """質問ファイル全体のSHA-256を計算する。"""
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for block in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_search_evaluation_queries(path: Path) -> tuple[SearchEvaluationQuery, ...]:
    """検索評価用JSONLを読み込み、質問モデルへ変換する。"""
    if not path.exists():
        raise SearchEvaluationInputError(f"入力ファイルが存在しません: {path}")
    if not path.is_file():
        raise SearchEvaluationInputError(f"入力パスがファイルではありません: {path}")

    queries: list[SearchEvaluationQuery] = []
    seen_query_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            if line.strip() == "":
                raise SearchEvaluationInputError(
                    f"{path}:{line_number}: 空行または空白行は使用できません。"
                )
            query = _parse_query_line(line, path, line_number)
            if query.query_id in seen_query_ids:
                raise _field_error(path, line_number, "query_id", "重複しています。")
            seen_query_ids.add(query.query_id)
            queries.append(query)
    return tuple(queries)


def _parse_query_line(line: str, path: Path, line_number: int) -> SearchEvaluationQuery:
    """JSONLの1行を検索評価質問へ変換する。"""
    try:
        value = json.loads(line)
    except json.JSONDecodeError as error:
        raise SearchEvaluationInputError(
            f"{path}:{line_number}: JSONとして不正です: {error.msg}"
        ) from error
    record = _require_mapping(value, path, line_number, "<root>")
    query_id = _require_non_empty_str(record, "query_id", path, line_number)
    query = _require_non_blank_str(record, "query", path, line_number)
    query_type = _require_non_empty_str(record, "query_type", path, line_number)
    notes = _optional_str(record, "notes", path, line_number)
    expected_relevant = _parse_expected_relevant(
        record.get("expected_relevant", []),
        path,
        line_number,
    )
    return SearchEvaluationQuery(
        query_id=query_id,
        query=query,
        query_type=query_type,
        expected_relevant=expected_relevant,
        notes=notes,
    )


def _parse_expected_relevant(
    value: Any,
    path: Path,
    line_number: int,
) -> tuple[ExpectedRelevantResult, ...]:
    """expected_relevantを検証してtupleへ変換する。"""
    if not isinstance(value, list):
        raise _field_error(path, line_number, "expected_relevant", "配列である必要があります。")
    expected: list[ExpectedRelevantResult] = []
    for index, item in enumerate(value):
        field_name = f"expected_relevant[{index}]"
        record = _require_mapping(item, path, line_number, field_name)
        relative_path = _require_non_empty_str(
            record,
            "relative_path",
            path,
            line_number,
            field_name,
        )
        locator = record.get("locator")
        if locator is not None and not isinstance(locator, str):
            raise _field_error(
                path,
                line_number,
                f"{field_name}.locator",
                "文字列またはnullである必要があります。",
            )
        expected.append(ExpectedRelevantResult(relative_path=relative_path, locator=locator))
    return tuple(expected)


def _require_mapping(
    value: Any,
    path: Path,
    line_number: int,
    field_name: str,
) -> dict[str, Any]:
    """JSONオブジェクトを辞書として取得する。"""
    if not isinstance(value, dict):
        raise _field_error(path, line_number, field_name, "オブジェクトである必要があります。")
    return value


def _required(
    mapping: dict[str, Any],
    field_name: str,
    path: Path,
    line_number: int,
    prefix: str | None = None,
) -> Any:
    """必須フィールドの存在を確認して値を返す。"""
    if field_name not in mapping:
        full_name = field_name if prefix is None else f"{prefix}.{field_name}"
        raise _field_error(path, line_number, full_name, "必須フィールドがありません。")
    return mapping[field_name]


def _require_str(
    mapping: dict[str, Any],
    field_name: str,
    path: Path,
    line_number: int,
    prefix: str | None = None,
) -> str:
    """必須文字列フィールドを取得する。"""
    value = _required(mapping, field_name, path, line_number, prefix)
    if not isinstance(value, str):
        full_name = field_name if prefix is None else f"{prefix}.{field_name}"
        raise _field_error(path, line_number, full_name, "文字列である必要があります。")
    return value


def _require_non_empty_str(
    mapping: dict[str, Any],
    field_name: str,
    path: Path,
    line_number: int,
    prefix: str | None = None,
) -> str:
    """空文字列を許可しない文字列フィールドを取得する。"""
    value = _require_str(mapping, field_name, path, line_number, prefix)
    if value == "":
        full_name = field_name if prefix is None else f"{prefix}.{field_name}"
        raise _field_error(path, line_number, full_name, "空文字列は使用できません。")
    return value


def _require_non_blank_str(
    mapping: dict[str, Any],
    field_name: str,
    path: Path,
    line_number: int,
) -> str:
    """空白だけを許可しない文字列フィールドを取得する。"""
    value = _require_str(mapping, field_name, path, line_number)
    if value.strip() == "":
        raise _field_error(path, line_number, field_name, "空白だけの文字列は使用できません。")
    return value


def _optional_str(
    mapping: dict[str, Any],
    field_name: str,
    path: Path,
    line_number: int,
) -> str:
    """省略可能な文字列フィールドを取得する。"""
    if field_name not in mapping:
        return ""
    value = mapping[field_name]
    if not isinstance(value, str):
        raise _field_error(path, line_number, field_name, "文字列である必要があります。")
    return value


def _field_error(
    path: Path,
    line_number: int,
    field_name: str,
    reason: str,
) -> SearchEvaluationInputError:
    """入力位置とフィールド名を含む検索評価入力例外を作成する。"""
    return SearchEvaluationInputError(f"{path}:{line_number}: {field_name}: {reason}")
