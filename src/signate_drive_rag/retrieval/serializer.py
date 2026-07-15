"""BM25検索結果とレコードをJSON/JSONLへ保存する処理。"""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from signate_drive_rag.retrieval.models import LexicalRecord, SearchResult


def lexical_record_to_json(record: LexicalRecord) -> dict[str, Any]:
    """LexicalRecordをJSON互換の辞書へ変換する。"""
    return {
        "record_index": record.record_index,
        "chunk_id": record.chunk_id,
        "relative_path": record.relative_path,
        "parser_name": record.parser_name,
        "unit_type": record.unit_type,
        "text": record.text,
        "locator": record.locator,
        "metadata": record.metadata,
    }


def search_result_to_json(result: SearchResult) -> dict[str, Any]:
    """SearchResultをJSON互換の辞書へ変換する。"""
    return {
        "rank": result.rank,
        "chunk_id": result.chunk_id,
        "relative_path": result.relative_path,
        "locator": result.locator,
        "parser_name": result.parser_name,
        "unit_type": result.unit_type,
        "score": result.score,
        "channel_ranks": dict(sorted(result.channel_ranks.items())),
        "text": result.text,
        "metadata": result.metadata,
    }


def write_json_atomic(path: Path, record: dict[str, Any]) -> None:
    """JSONを一時ファイルへ書き、成功後に置き換える。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def write_jsonl_atomic(path: Path, records: Iterable[dict[str, Any]]) -> None:
    """JSONLを一時ファイルへ書き、成功後に置き換える。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as output_file:
            for record in records:
                output_file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        temporary_path.replace(path)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def save_search_results(
    output_path: Path,
    *,
    query: str,
    top_k: int,
    results: tuple[SearchResult, ...],
) -> None:
    """検索結果をJSONとして保存する。"""
    write_json_atomic(
        output_path,
        {
            "query": query,
            "top_k": top_k,
            "results": [search_result_to_json(result) for result in results],
        },
    )
