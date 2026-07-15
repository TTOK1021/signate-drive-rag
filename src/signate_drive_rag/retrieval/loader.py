"""検索用chunks.jsonlを読み込む処理。"""

import hashlib
import json
from pathlib import Path
from typing import Any, cast

from signate_drive_rag.chunking.models import RetrievalChunk
from signate_drive_rag.domain.extracted_document import JsonValue


class RetrievalInputError(ValueError):
    """検索入力JSONLが不正な場合の例外。"""


def calculate_file_sha256(path: Path) -> str:
    """入力ファイル全体のSHA-256を計算する。"""
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for block in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_retrieval_chunks(chunks_path: Path) -> tuple[RetrievalChunk, ...]:
    """chunks.jsonlを読み込み、検索用チャンクへ変換する。"""
    if not chunks_path.exists():
        raise RetrievalInputError(f"入力ファイルが存在しません: {chunks_path}")
    if not chunks_path.is_file():
        raise RetrievalInputError(f"入力パスがファイルではありません: {chunks_path}")

    chunks: list[RetrievalChunk] = []
    seen_chunk_ids: set[str] = set()
    with chunks_path.open("r", encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            if line.strip() == "":
                raise RetrievalInputError(
                    f"{chunks_path}:{line_number}: 空行または空白行は使用できません。"
                )
            chunk = _parse_chunk_line(line, chunks_path, line_number)
            if chunk.chunk_id in seen_chunk_ids:
                raise _field_error(chunks_path, line_number, "chunk_id", "重複しています。")
            seen_chunk_ids.add(chunk.chunk_id)
            chunks.append(chunk)
    return tuple(chunks)


def _parse_chunk_line(line: str, chunks_path: Path, line_number: int) -> RetrievalChunk:
    """JSONLの1行をRetrievalChunkへ変換する。"""
    try:
        value = json.loads(line)
    except json.JSONDecodeError as error:
        raise RetrievalInputError(
            f"{chunks_path}:{line_number}: JSONとして不正です: {error.msg}"
        ) from error

    record = _require_mapping(value, chunks_path, line_number, "<root>")
    locator = _required(record, "locator", chunks_path, line_number)
    if locator is not None and not isinstance(locator, str):
        raise _field_error(chunks_path, line_number, "locator", "文字列またはnullが必要です。")
    metadata = _require_mapping(
        _required(record, "metadata", chunks_path, line_number),
        chunks_path,
        line_number,
        "metadata",
    )
    source_unit_indices = _parse_int_array(
        _required(record, "source_unit_indices", chunks_path, line_number),
        chunks_path,
        line_number,
        "source_unit_indices",
    )
    chunk_id = _require_non_empty_str(record, "chunk_id", chunks_path, line_number)
    relative_path = _require_non_empty_str(record, "relative_path", chunks_path, line_number)
    text = _require_non_empty_str(record, "text", chunks_path, line_number)
    return RetrievalChunk(
        chunk_id=chunk_id,
        relative_path=relative_path,
        parser_name=_require_str(record, "parser_name", chunks_path, line_number),
        unit_type=_require_str(record, "unit_type", chunks_path, line_number),
        text=text,
        locator=locator,
        source_unit_indices=source_unit_indices,
        chunk_index=_require_int(record, "chunk_index", chunks_path, line_number),
        metadata=cast(dict[str, JsonValue], metadata),
    )


def _required(
    mapping: dict[str, Any],
    field_name: str,
    chunks_path: Path,
    line_number: int,
) -> Any:
    """必須フィールドの存在を確認して値を返す。"""
    if field_name not in mapping:
        raise _field_error(chunks_path, line_number, field_name, "必須フィールドがありません。")
    return mapping[field_name]


def _require_str(
    mapping: dict[str, Any],
    field_name: str,
    chunks_path: Path,
    line_number: int,
) -> str:
    """必須文字列フィールドを取得する。"""
    value = _required(mapping, field_name, chunks_path, line_number)
    if not isinstance(value, str):
        raise _field_error(chunks_path, line_number, field_name, "文字列である必要があります。")
    return value


def _require_non_empty_str(
    mapping: dict[str, Any],
    field_name: str,
    chunks_path: Path,
    line_number: int,
) -> str:
    """空文字列を許可しない文字列フィールドを取得する。"""
    value = _require_str(mapping, field_name, chunks_path, line_number)
    if value == "":
        raise _field_error(chunks_path, line_number, field_name, "空文字列は使用できません。")
    return value


def _require_int(
    mapping: dict[str, Any],
    field_name: str,
    chunks_path: Path,
    line_number: int,
) -> int:
    """必須整数フィールドを取得する。"""
    value = _required(mapping, field_name, chunks_path, line_number)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _field_error(chunks_path, line_number, field_name, "整数である必要があります。")
    return value


def _require_mapping(
    value: Any,
    chunks_path: Path,
    line_number: int,
    field_name: str,
) -> dict[str, Any]:
    """JSONオブジェクトを辞書として取得する。"""
    if not isinstance(value, dict):
        raise _field_error(
            chunks_path,
            line_number,
            field_name,
            "オブジェクトである必要があります。",
        )
    return value


def _parse_int_array(
    value: Any,
    chunks_path: Path,
    line_number: int,
    field_name: str,
) -> tuple[int, ...]:
    """整数配列をtupleへ変換する。"""
    if not isinstance(value, list):
        raise _field_error(chunks_path, line_number, field_name, "配列である必要があります。")
    indices: list[int] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int):
            raise _field_error(
                chunks_path,
                line_number,
                f"{field_name}[{index}]",
                "整数である必要があります。",
            )
        indices.append(item)
    return tuple(indices)


def _field_error(
    chunks_path: Path,
    line_number: int,
    field_name: str,
    reason: str,
) -> RetrievalInputError:
    """入力位置とフィールド名を含む検索入力例外を作成する。"""
    return RetrievalInputError(f"{chunks_path}:{line_number}: {field_name}: {reason}")
