"""監査入力ローダーの単体テスト。"""

import json
from pathlib import Path

import pytest

from signate_drive_rag.audit import AuditInputError, load_audit_documents


def document_record(
    *,
    relative_path: str = "プロジェクト/資料.md",
    text: str = "本文",
    locator: str | None = "line:1-1",
) -> dict[str, object]:
    """テスト用documents.jsonlレコードを作成する。"""
    return {
        "source": {
            "relative_path": relative_path,
            "name": Path(relative_path).name,
            "suffix": Path(relative_path).suffix,
            "mime_type": "text/markdown",
            "size_bytes": 123,
            "modified_at": "2026-07-11T12:00:00+00:00",
        },
        "parser_name": "markdown",
        "units": [
            {
                "unit_type": "markdown_section",
                "text": text,
                "locator": locator,
                "metadata": {"heading_path": ["見出し"]},
            }
        ],
    }


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    """JSONLテストファイルを書き込む。"""
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def test_load_audit_documents_reads_valid_documents_jsonl(tmp_path: Path) -> None:
    """正常なdocuments.jsonlを読み込める。"""
    documents_path = tmp_path / "documents.jsonl"
    write_jsonl(documents_path, [document_record(relative_path="案件/資料.md", text="日本語本文")])

    documents = load_audit_documents(documents_path)

    assert len(documents) == 1
    assert documents[0].relative_path == "案件/資料.md"
    assert documents[0].units[0].text == "日本語本文"


def test_load_audit_documents_reads_multiple_lines(tmp_path: Path) -> None:
    """複数行のJSONLを複数文書として読み込める。"""
    documents_path = tmp_path / "documents.jsonl"
    write_jsonl(
        documents_path,
        [
            document_record(relative_path="a.md"),
            document_record(relative_path="b.md"),
        ],
    )

    documents = load_audit_documents(documents_path)

    assert [document.relative_path for document in documents] == ["a.md", "b.md"]


def test_load_audit_documents_raises_for_missing_file(tmp_path: Path) -> None:
    """存在しない入力で例外になる。"""
    with pytest.raises(AuditInputError):
        load_audit_documents(tmp_path / "missing.jsonl")


def test_load_audit_documents_raises_for_directory(tmp_path: Path) -> None:
    """ディレクトリを入力すると例外になる。"""
    with pytest.raises(AuditInputError):
        load_audit_documents(tmp_path)


def test_load_audit_documents_raises_with_line_number_for_invalid_json(
    tmp_path: Path,
) -> None:
    """不正JSONでは行番号付きの例外になる。"""
    documents_path = tmp_path / "documents.jsonl"
    documents_path.write_text(
        json.dumps(document_record(), ensure_ascii=False) + "\n{invalid}\n",
        encoding="utf-8",
    )

    with pytest.raises(AuditInputError, match=":2:"):
        load_audit_documents(documents_path)


def test_load_audit_documents_raises_for_empty_line(tmp_path: Path) -> None:
    """空行を含むJSONLでは例外になる。"""
    documents_path = tmp_path / "documents.jsonl"
    documents_path.write_text(json.dumps(document_record()) + "\n\n", encoding="utf-8")

    with pytest.raises(AuditInputError, match="空行"):
        load_audit_documents(documents_path)


@pytest.mark.parametrize(
    "record",
    [
        {"parser_name": "markdown", "units": []},
        {**document_record(), "parser_name": 123},
        {**document_record(), "units": {}},
        {**document_record(), "units": ["bad"]},
    ],
)
def test_load_audit_documents_raises_for_invalid_required_fields(
    tmp_path: Path,
    record: dict[str, object],
) -> None:
    """必須フィールド欠落や型不正では例外になる。"""
    documents_path = tmp_path / "documents.jsonl"
    write_jsonl(documents_path, [record])

    with pytest.raises(AuditInputError):
        load_audit_documents(documents_path)


def test_load_audit_documents_reads_empty_jsonl(tmp_path: Path) -> None:
    """空のJSONLを空の文書一覧として読み込める。"""
    documents_path = tmp_path / "documents.jsonl"
    documents_path.write_text("", encoding="utf-8")

    assert load_audit_documents(documents_path) == ()
