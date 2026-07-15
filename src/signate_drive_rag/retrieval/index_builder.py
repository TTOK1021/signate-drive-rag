"""検索用チャンクからBM25インデックスを構築する処理。"""

from importlib import metadata
from typing import Any

import bm25s  # type: ignore[import-untyped]

from signate_drive_rag.chunking.models import RetrievalChunk
from signate_drive_rag.retrieval.models import (
    CONTENT_NGRAM_CHANNEL,
    CONTENT_WORD_CHANNEL,
    CONTEXT_WORD_CHANNEL,
    SCHEMA_VERSION,
    SEARCH_CHANNELS,
    BuiltBm25Index,
    LexicalRecord,
)
from signate_drive_rag.retrieval.tokenizer import (
    JapaneseNgramTokenizer,
    WordTokenizer,
    build_context_text,
)

BM25_PARAMETERS: dict[str, float | str] = {
    "k1": 1.5,
    "b": 0.75,
    "delta": 0.5,
    "method": "lucene",
}
_EMPTY_CHANNEL_TOKEN = "__signate_empty_channel__"


def build_bm25_index(
    chunks: tuple[RetrievalChunk, ...],
    *,
    source_sha256: str,
    ngram_min: int = 2,
    ngram_max: int = 3,
) -> BuiltBm25Index:
    """検索用チャンクから3チャネルのBM25インデックスを構築する。"""
    records = _build_records(chunks)
    word_tokenizer = WordTokenizer()
    ngram_tokenizer = JapaneseNgramTokenizer(ngram_min=ngram_min, ngram_max=ngram_max)
    tokenized_documents = {
        CONTENT_WORD_CHANNEL: tuple(word_tokenizer.tokenize(record.text) for record in records),
        CONTENT_NGRAM_CHANNEL: tuple(ngram_tokenizer.tokenize(record.text) for record in records),
        CONTEXT_WORD_CHANNEL: tuple(
            word_tokenizer.tokenize(build_context_text(record)) for record in records
        ),
    }
    channel_indexes = {
        channel_name: _build_channel_index(tokenized_documents[channel_name])
        for channel_name in SEARCH_CHANNELS
        if records
    }
    return BuiltBm25Index(
        manifest=_build_manifest(
            source_sha256=source_sha256,
            record_count=len(records),
            ngram_min=ngram_min,
            ngram_max=ngram_max,
        ),
        records=records,
        channel_indexes=channel_indexes,
    )


def _build_records(chunks: tuple[RetrievalChunk, ...]) -> tuple[LexicalRecord, ...]:
    """入力順ではなく内容ベースの順序でrecord_indexを固定する。"""
    sorted_chunks = sorted(
        chunks,
        key=lambda chunk: (chunk.relative_path, chunk.chunk_index, chunk.chunk_id),
    )
    return tuple(
        LexicalRecord(
            record_index=record_index,
            chunk_id=chunk.chunk_id,
            relative_path=chunk.relative_path,
            parser_name=chunk.parser_name,
            unit_type=chunk.unit_type,
            text=chunk.text,
            locator=chunk.locator,
            metadata=chunk.metadata,
        )
        for record_index, chunk in enumerate(sorted_chunks)
    )


def _build_channel_index(tokenized_documents: tuple[tuple[str, ...], ...]) -> Any:
    """bm25sの公開APIで1チャネル分のインデックスを作る。"""
    bm25_index = bm25s.BM25(**BM25_PARAMETERS)
    documents = [list(tokens) for tokens in tokenized_documents]
    if documents and all(len(tokens) == 0 for tokens in documents):
        # bm25sは完全な空語彙を保存できないため、検索クエリに出ない番兵語で形だけ作る。
        documents = [[_EMPTY_CHANNEL_TOKEN] for _ in documents]
    bm25_index.index(documents, show_progress=False)
    return bm25_index


def _build_manifest(
    *,
    source_sha256: str,
    record_count: int,
    ngram_min: int,
    ngram_max: int,
) -> dict[str, Any]:
    """検索設定を再現できるmanifestを構成する。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "source_sha256": source_sha256,
        "record_count": record_count,
        "channels": list(SEARCH_CHANNELS),
        "normalization": {
            "unicode": "NFKC",
            "casefold": True,
        },
        "tokenizer": {
            "ngram_min": ngram_min,
            "ngram_max": ngram_max,
        },
        "bm25": {
            "library": "bm25s",
            "library_version": metadata.version("bm25s"),
            "parameters": BM25_PARAMETERS,
        },
    }
