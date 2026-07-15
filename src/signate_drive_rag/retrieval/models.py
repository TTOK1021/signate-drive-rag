"""BM25検索で使用する共通モデル。"""

from dataclasses import dataclass
from typing import Any

from signate_drive_rag.domain.extracted_document import JsonValue

CONTENT_WORD_CHANNEL = "content_word"
CONTENT_NGRAM_CHANNEL = "content_ngram"
CONTEXT_WORD_CHANNEL = "context_word"
SEARCH_CHANNELS = (CONTENT_WORD_CHANNEL, CONTENT_NGRAM_CHANNEL, CONTEXT_WORD_CHANNEL)
SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class LexicalRecord:
    """BM25インデックスと検索用チャンクを対応付けるレコード。"""

    record_index: int
    chunk_id: str
    relative_path: str
    parser_name: str
    unit_type: str
    text: str
    locator: str | None
    metadata: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class BuiltBm25Index:
    """構築済みBM25インデックス一式。"""

    manifest: dict[str, JsonValue]
    records: tuple[LexicalRecord, ...]
    channel_indexes: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LoadedBm25Index:
    """保存済みBM25インデックスを読み込んだ結果。"""

    manifest: dict[str, JsonValue]
    records: tuple[LexicalRecord, ...]
    channel_indexes: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SearchResult:
    """質問に対する検索結果。"""

    rank: int
    chunk_id: str
    relative_path: str
    locator: str | None
    parser_name: str
    unit_type: str
    score: float
    channel_ranks: dict[str, int]
    text: str
    metadata: dict[str, JsonValue]
