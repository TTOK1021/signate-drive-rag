"""検索評価JSONLローダーのテスト。"""

import json
from pathlib import Path

import pytest

from signate_drive_rag.search_evaluation import (
    SearchEvaluationInputError,
    load_search_evaluation_queries,
)


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    """テスト用JSONLを書き込む。"""
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def query_record(query_id: str = "q1") -> dict[str, object]:
    """正常な質問レコードを作成する。"""
    return {
        "query_id": query_id,
        "query": "契約金額",
        "query_type": "exact",
        "expected_relevant": [{"relative_path": "資料/契約.md", "locator": None}],
        "notes": "確認用",
    }


def test_load_search_evaluation_queries_reads_valid_jsonl(tmp_path: Path) -> None:
    """正常な質問JSONLを入力順で読み込める。"""
    path = tmp_path / "queries.jsonl"
    write_jsonl(path, [query_record("q1"), query_record("q2")])

    queries = load_search_evaluation_queries(path)

    assert [query.query_id for query in queries] == ["q1", "q2"]
    assert queries[0].query == "契約金額"
    assert queries[0].expected_relevant[0].relative_path == "資料/契約.md"
    assert queries[0].expected_relevant[0].locator is None
    assert queries[0].notes == "確認用"


def test_load_search_evaluation_queries_uses_empty_expected_when_omitted(
    tmp_path: Path,
) -> None:
    """expected_relevant省略時は目視確認対象として空tupleにする。"""
    path = tmp_path / "queries.jsonl"
    record = query_record()
    del record["expected_relevant"]
    del record["notes"]
    write_jsonl(path, [record])

    queries = load_search_evaluation_queries(path)

    assert queries[0].expected_relevant == ()
    assert queries[0].notes == ""


def test_load_search_evaluation_queries_reads_empty_jsonl(tmp_path: Path) -> None:
    """空JSONLを空の質問セットとして読み込める。"""
    path = tmp_path / "queries.jsonl"
    path.write_text("", encoding="utf-8")

    assert load_search_evaluation_queries(path) == ()


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("{broken}\n", "JSONとして不正"),
        ("\n", "空行"),
        (json.dumps({"query_id": "q"}, ensure_ascii=False) + "\n", "query"),
    ],
)
def test_load_search_evaluation_queries_raises_with_line_number(
    tmp_path: Path,
    content: str,
    expected: str,
) -> None:
    """不正なJSONLでは行番号と原因を含むエラーにする。"""
    path = tmp_path / "queries.jsonl"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(SearchEvaluationInputError) as error:
        load_search_evaluation_queries(path)

    assert "queries.jsonl:1" in str(error.value)
    assert expected in str(error.value)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda record: record.update({"query_id": 1}),
        lambda record: record.update({"query": "   "}),
        lambda record: record.update({"query_type": ""}),
        lambda record: record.update({"expected_relevant": "bad"}),
        lambda record: record.update(
            {"expected_relevant": [{"relative_path": "", "locator": None}]}
        ),
        lambda record: record.update({"expected_relevant": [{"relative_path": "x", "locator": 1}]}),
    ],
)
def test_load_search_evaluation_queries_rejects_invalid_fields(
    tmp_path: Path,
    mutator,
) -> None:
    """フィールドの型不正、空質問、空relative_pathを検出する。"""
    path = tmp_path / "queries.jsonl"
    record = query_record()
    mutator(record)
    write_jsonl(path, [record])

    with pytest.raises(SearchEvaluationInputError):
        load_search_evaluation_queries(path)


def test_load_search_evaluation_queries_rejects_duplicate_query_id(tmp_path: Path) -> None:
    """query_idの重複を検出する。"""
    path = tmp_path / "queries.jsonl"
    write_jsonl(path, [query_record("same"), query_record("same")])

    with pytest.raises(SearchEvaluationInputError, match="重複"):
        load_search_evaluation_queries(path)
