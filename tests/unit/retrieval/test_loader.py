"""chunks.jsonlローダーのテスト。"""

import json
from pathlib import Path

import pytest

from signate_drive_rag.retrieval.loader import RetrievalInputError, load_retrieval_chunks


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    """テスト用JSONLを書き込む。"""
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def chunk_record(chunk_id: str = "chunk-1") -> dict[str, object]:
    """正常なchunkレコードを作成する。"""
    return {
        "chunk_id": chunk_id,
        "relative_path": "資料/契約.md",
        "parser_name": "markdown",
        "unit_type": "markdown_section",
        "text": "契約金額",
        "locator": "heading:1",
        "source_unit_indices": [0, 1],
        "chunk_index": 0,
        "metadata": {"heading": "契約"},
    }


def test_load_retrieval_chunks_reads_valid_jsonl_and_preserves_order(tmp_path: Path) -> None:
    """正常なchunks.jsonlを入力順のまま読み込める。"""
    path = tmp_path / "chunks.jsonl"
    write_jsonl(path, [chunk_record("b"), chunk_record("a")])

    chunks = load_retrieval_chunks(path)

    assert [chunk.chunk_id for chunk in chunks] == ["b", "a"]
    assert chunks[0].relative_path == "資料/契約.md"
    assert chunks[0].text == "契約金額"
    assert chunks[0].source_unit_indices == (0, 1)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("{broken}\n", "JSONとして不正"),
        ("\n", "空行"),
        (json.dumps({"chunk_id": "x"}, ensure_ascii=False) + "\n", "locator"),
    ],
)
def test_load_retrieval_chunks_raises_with_line_number(
    tmp_path: Path,
    content: str,
    expected: str,
) -> None:
    """不正なJSONLでは行番号と原因を含むエラーにする。"""
    path = tmp_path / "chunks.jsonl"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(RetrievalInputError) as error:
        load_retrieval_chunks(path)

    assert "chunks.jsonl:1" in str(error.value)
    assert expected in str(error.value)


def test_load_retrieval_chunks_rejects_invalid_types_and_duplicate_chunk_id(
    tmp_path: Path,
) -> None:
    """型不正とchunk_id重複を検出する。"""
    invalid_path = tmp_path / "invalid.jsonl"
    invalid_record = chunk_record()
    invalid_record["source_unit_indices"] = ["0"]
    write_jsonl(invalid_path, [invalid_record])

    with pytest.raises(RetrievalInputError, match="source_unit_indices"):
        load_retrieval_chunks(invalid_path)

    duplicate_path = tmp_path / "duplicate.jsonl"
    write_jsonl(duplicate_path, [chunk_record("same"), chunk_record("same")])
    with pytest.raises(RetrievalInputError, match="重複"):
        load_retrieval_chunks(duplicate_path)


def test_load_retrieval_chunks_reads_empty_jsonl(tmp_path: Path) -> None:
    """空のchunks.jsonlは空コーパスとして読み込める。"""
    path = tmp_path / "chunks.jsonl"
    path.write_text("", encoding="utf-8")

    assert load_retrieval_chunks(path) == ()
