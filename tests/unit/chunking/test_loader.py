"""チャンク生成入力ローダーの単体テスト。"""

import json
from pathlib import Path

import pytest

from signate_drive_rag.chunking import ChunkInputError, load_chunk_source_documents


def record(relative_path: str = "案件/資料.md", text: str = "日本語本文") -> dict[str, object]:
    """documents.jsonlのテストレコードを作成する。"""
    return {
        "source": {
            "relative_path": relative_path,
            "name": Path(relative_path).name,
            "suffix": Path(relative_path).suffix,
            "mime_type": None,
            "size_bytes": 10,
            "modified_at": "2026-07-11T12:00:00+00:00",
        },
        "parser_name": "markdown",
        "units": [
            {
                "unit_type": "markdown_section",
                "text": text,
                "locator": "line:1-1",
                "metadata": {"heading_path": ["見出し"]},
            }
        ],
    }


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    """JSONLを書き込む。"""
    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        encoding="utf-8",
    )


def test_load_chunk_source_documents_preserves_japanese_path_text_and_metadata(
    tmp_path: Path,
) -> None:
    """日本語パス・本文・metadataを保持して読み込める。"""
    documents_path = tmp_path / "documents.jsonl"
    write_jsonl(documents_path, [record()])

    documents = load_chunk_source_documents(documents_path)

    assert documents[0].relative_path == "案件/資料.md"
    assert documents[0].units[0].text == "日本語本文"
    assert documents[0].units[0].metadata["heading_path"] == ["見出し"]


def test_load_chunk_source_documents_preserves_input_order(tmp_path: Path) -> None:
    """入力JSONLの文書順を維持して読み込む。"""
    documents_path = tmp_path / "documents.jsonl"
    write_jsonl(documents_path, [record("b.md"), record("a.md")])

    documents = load_chunk_source_documents(documents_path)

    assert [document.relative_path for document in documents] == ["b.md", "a.md"]


def test_load_chunk_source_documents_reads_empty_jsonl(tmp_path: Path) -> None:
    """空のJSONLを空の文書一覧として読み込める。"""
    documents_path = tmp_path / "documents.jsonl"
    documents_path.write_text("", encoding="utf-8")

    assert load_chunk_source_documents(documents_path) == ()


def test_load_chunk_source_documents_raises_for_invalid_json_with_line_number(
    tmp_path: Path,
) -> None:
    """不正JSONでは行番号付きの例外になる。"""
    documents_path = tmp_path / "documents.jsonl"
    documents_path.write_text(
        json.dumps(record(), ensure_ascii=False) + "\n{invalid}\n",
        encoding="utf-8",
    )

    with pytest.raises(ChunkInputError, match=":2:"):
        load_chunk_source_documents(documents_path)


def test_load_chunk_source_documents_raises_for_missing_required_field(
    tmp_path: Path,
) -> None:
    """必須フィールド欠落では例外になる。"""
    documents_path = tmp_path / "documents.jsonl"
    write_jsonl(documents_path, [{"parser_name": "markdown", "units": []}])

    with pytest.raises(ChunkInputError):
        load_chunk_source_documents(documents_path)
