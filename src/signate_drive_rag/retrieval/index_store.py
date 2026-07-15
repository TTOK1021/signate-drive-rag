"""BM25インデックスの保存と読込。"""

import json
import shutil
from pathlib import Path
from typing import Any, cast

import bm25s  # type: ignore[import-untyped]

from signate_drive_rag.domain.extracted_document import JsonValue
from signate_drive_rag.retrieval.models import (
    SCHEMA_VERSION,
    SEARCH_CHANNELS,
    BuiltBm25Index,
    LexicalRecord,
    LoadedBm25Index,
)
from signate_drive_rag.retrieval.serializer import (
    lexical_record_to_json,
    write_json_atomic,
    write_jsonl_atomic,
)

MANIFEST_FILE_NAME = "manifest.json"
RECORDS_FILE_NAME = "records.jsonl"


class RetrievalIndexError(ValueError):
    """BM25インデックスが不正または保存できない場合の例外。"""


def save_bm25_index(index: BuiltBm25Index, output_dir: Path, *, overwrite: bool = False) -> None:
    """構築済みインデックスを一時ディレクトリ経由で保存する。"""
    if output_dir.exists() and not overwrite:
        raise RetrievalIndexError(f"出力ディレクトリが既に存在します: {output_dir}")

    temporary_dir = output_dir.with_name(f"{output_dir.name}.tmp")
    if temporary_dir.exists():
        shutil.rmtree(temporary_dir)
    temporary_dir.mkdir(parents=True)
    try:
        write_json_atomic(temporary_dir / MANIFEST_FILE_NAME, index.manifest)
        write_jsonl_atomic(
            temporary_dir / RECORDS_FILE_NAME,
            (lexical_record_to_json(record) for record in index.records),
        )
        for channel_name in SEARCH_CHANNELS:
            channel_dir = temporary_dir / channel_name
            channel_dir.mkdir()
            if index.records:
                index.channel_indexes[channel_name].save(channel_dir, show_progress=False)

        if output_dir.exists():
            shutil.rmtree(output_dir)
        temporary_dir.rename(output_dir)
    except Exception:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        raise


def load_bm25_index(index_dir: Path) -> LoadedBm25Index:
    """保存済みBM25インデックスを検証しながら読み込む。"""
    if not index_dir.exists():
        raise RetrievalIndexError(f"インデックスディレクトリが存在しません: {index_dir}")
    if not index_dir.is_dir():
        raise RetrievalIndexError(f"インデックスパスがディレクトリではありません: {index_dir}")

    manifest = _load_manifest(index_dir / MANIFEST_FILE_NAME)
    channels = _validate_manifest(manifest)
    records = _load_records(index_dir / RECORDS_FILE_NAME)
    record_count = _require_int(manifest, "record_count", MANIFEST_FILE_NAME)
    if len(records) != record_count:
        raise RetrievalIndexError("manifestのrecord_countとrecords.jsonl件数が一致しません。")
    _validate_records(records)

    channel_indexes: dict[str, Any] = {}
    for channel_name in channels:
        channel_dir = index_dir / channel_name
        if not channel_dir.is_dir():
            raise RetrievalIndexError(f"必須チャネルディレクトリが存在しません: {channel_name}")
        if record_count > 0:
            channel_index = bm25s.BM25.load(channel_dir, load_corpus=False)
            if int(channel_index.scores.get("num_docs", -1)) != record_count:
                raise RetrievalIndexError(f"{channel_name}: 文書数がrecord_countと一致しません。")
            channel_indexes[channel_name] = channel_index

    return LoadedBm25Index(
        manifest=manifest,
        records=records,
        channel_indexes=channel_indexes,
    )


def _load_manifest(path: Path) -> dict[str, JsonValue]:
    """manifest.jsonを読み込む。"""
    if not path.is_file():
        raise RetrievalIndexError(f"manifest.jsonが存在しません: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RetrievalIndexError("manifest.jsonはJSONオブジェクトである必要があります。")
    return cast(dict[str, JsonValue], value)


def _validate_manifest(manifest: dict[str, JsonValue]) -> tuple[str, ...]:
    """対応スキーマと必須チャネルを検証する。"""
    if _require_int(manifest, "schema_version", MANIFEST_FILE_NAME) != SCHEMA_VERSION:
        raise RetrievalIndexError("未対応のmanifest schema_versionです。")
    channels_value = manifest.get("channels")
    if not isinstance(channels_value, list) or not all(
        isinstance(channel, str) for channel in channels_value
    ):
        raise RetrievalIndexError("manifest.channelsは文字列配列である必要があります。")
    channels = tuple(cast(list[str], channels_value))
    if tuple(channels) != SEARCH_CHANNELS:
        raise RetrievalIndexError("必須チャネル構成が一致しません。")
    _require_str(manifest, "source_sha256", MANIFEST_FILE_NAME)
    _require_int(manifest, "record_count", MANIFEST_FILE_NAME)
    return channels


def _load_records(path: Path) -> tuple[LexicalRecord, ...]:
    """records.jsonlを読み込む。"""
    if not path.is_file():
        raise RetrievalIndexError(f"records.jsonlが存在しません: {path}")
    records: list[LexicalRecord] = []
    with path.open("r", encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            if line.strip() == "":
                raise RetrievalIndexError(f"{path}:{line_number}: 空行は使用できません。")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise RetrievalIndexError(
                    f"{path}:{line_number}: オブジェクトである必要があります。"
                )
            records.append(_parse_record(value, path, line_number))
    return tuple(records)


def _parse_record(value: dict[str, Any], path: Path, line_number: int) -> LexicalRecord:
    """records.jsonlの1行をLexicalRecordへ変換する。"""
    locator = _required(value, "locator", path.name)
    if locator is not None and not isinstance(locator, str):
        raise RetrievalIndexError(f"{path}:{line_number}: locator: 文字列またはnullが必要です。")
    metadata = _required(value, "metadata", path.name)
    if not isinstance(metadata, dict):
        raise RetrievalIndexError(f"{path}:{line_number}: metadata: オブジェクトが必要です。")
    return LexicalRecord(
        record_index=_require_int(value, "record_index", path.name),
        chunk_id=_require_str(value, "chunk_id", path.name),
        relative_path=_require_str(value, "relative_path", path.name),
        parser_name=_require_str(value, "parser_name", path.name),
        unit_type=_require_str(value, "unit_type", path.name),
        text=_require_str(value, "text", path.name),
        locator=locator,
        metadata=cast(dict[str, JsonValue], metadata),
    )


def _validate_records(records: tuple[LexicalRecord, ...]) -> None:
    """record_indexの連続性とchunk_id重複を検証する。"""
    seen_chunk_ids: set[str] = set()
    for expected_index, record in enumerate(records):
        if record.record_index != expected_index:
            raise RetrievalIndexError("record_indexが0から連続していません。")
        if record.chunk_id in seen_chunk_ids:
            raise RetrievalIndexError("records.jsonlに重複chunk_idがあります。")
        seen_chunk_ids.add(record.chunk_id)


def _required(mapping: dict[str, Any], field_name: str, source_name: str) -> Any:
    """必須フィールドを取得する。"""
    if field_name not in mapping:
        raise RetrievalIndexError(f"{source_name}: {field_name}: 必須フィールドがありません。")
    return mapping[field_name]


def _require_str(mapping: dict[str, Any], field_name: str, source_name: str) -> str:
    """必須文字列フィールドを取得する。"""
    value = _required(mapping, field_name, source_name)
    if not isinstance(value, str):
        raise RetrievalIndexError(f"{source_name}: {field_name}: 文字列である必要があります。")
    return value


def _require_int(mapping: dict[str, Any], field_name: str, source_name: str) -> int:
    """必須整数フィールドを取得する。"""
    value = _required(mapping, field_name, source_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RetrievalIndexError(f"{source_name}: {field_name}: 整数である必要があります。")
    return value
