"""JSONパーサーの単体テスト。"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from signate_drive_rag.domain import SourceFile
from signate_drive_rag.ingestion.parsers import JsonDocumentParser


def make_source_file(path: Path) -> SourceFile:
    """テスト用のSourceFileを作成する。"""
    stat_result = path.stat()
    return SourceFile(
        path=path,
        relative_path=Path(path.name),
        name=path.name,
        suffix=path.suffix,
        mime_type=None,
        size_bytes=stat_result.st_size,
        modified_at=datetime.fromtimestamp(stat_result.st_mtime, tz=UTC),
    )


def write_json(path: Path, value: object) -> None:
    """テスト用JSONをUTF-8で書き込む。"""
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_json_document_parser_supports_json_suffix(tmp_path: Path) -> None:
    """json拡張子のファイルを処理可能と判定する。"""
    file_path = tmp_path / "sample.json"
    write_json(file_path, {"name": "sample"})

    assert JsonDocumentParser().supports(make_source_file(file_path)) is True


def test_json_document_parser_extracts_nested_object(tmp_path: Path) -> None:
    """ネストしたオブジェクトをJSON Pointer付きで抽出する。"""
    file_path = tmp_path / "sample.json"
    write_json(file_path, {"customer": {"contract": {"amount": 5000000}}})

    document = JsonDocumentParser().parse(make_source_file(file_path))

    assert document.units[0].locator == "/customer/contract/amount"
    assert document.units[0].text == "5000000"


def test_json_document_parser_extracts_array_with_indexes(tmp_path: Path) -> None:
    """配列要素をインデックス付きJSON Pointerで抽出する。"""
    file_path = tmp_path / "sample.json"
    write_json(file_path, {"records": [{"project_id": "p1"}, {"project_id": "p2"}]})

    document = JsonDocumentParser().parse(make_source_file(file_path))

    assert [unit.locator for unit in document.units] == [
        "/records/0/project_id",
        "/records/1/project_id",
    ]


def test_json_document_parser_distinguishes_scalar_value_types(tmp_path: Path) -> None:
    """文字列、整数、浮動小数、真偽値、nullの型を区別する。"""
    file_path = tmp_path / "sample.json"
    write_json(
        file_path,
        {"s": "x", "i": 1, "n": 1.5, "b": True, "none": None},
    )

    document = JsonDocumentParser().parse(make_source_file(file_path))

    assert [(unit.text, unit.metadata["value_type"]) for unit in document.units] == [
        ("x", "string"),
        ("1", "integer"),
        ("1.5", "number"),
        ("true", "boolean"),
        ("null", "null"),
    ]


def test_json_document_parser_does_not_treat_boolean_as_integer(tmp_path: Path) -> None:
    """Pythonのboolをintegerとして扱わない。"""
    file_path = tmp_path / "sample.json"
    write_json(file_path, {"enabled": False})

    document = JsonDocumentParser().parse(make_source_file(file_path))

    assert document.units[0].metadata["value_type"] == "boolean"
    assert document.units[0].text == "false"


def test_json_document_parser_preserves_empty_containers(tmp_path: Path) -> None:
    """空オブジェクトと空配列を抽出単位として保持する。"""
    file_path = tmp_path / "sample.json"
    write_json(file_path, {"empty_object": {}, "empty_array": []})

    document = JsonDocumentParser().parse(make_source_file(file_path))

    assert [(unit.locator, unit.text, unit.metadata["value_type"]) for unit in document.units] == [
        ("/empty_object", "{}", "object"),
        ("/empty_array", "[]", "array"),
    ]


def test_json_document_parser_escapes_json_pointer_tokens(tmp_path: Path) -> None:
    """JSON Pointerの/と~を仕様どおりエスケープする。"""
    file_path = tmp_path / "sample.json"
    write_json(file_path, {"a/b": {"x~y": 10}})

    document = JsonDocumentParser().parse(make_source_file(file_path))

    assert document.units[0].locator == "/a~1b/x~0y"


def test_json_document_parser_extracts_root_scalar(tmp_path: Path) -> None:
    """ルートがスカラーの場合は空文字JSON Pointerで抽出する。"""
    file_path = tmp_path / "sample.json"
    write_json(file_path, "sample")

    document = JsonDocumentParser().parse(make_source_file(file_path))

    assert document.units[0].locator == ""
    assert document.units[0].text == "sample"


def test_json_document_parser_preserves_japanese_string(tmp_path: Path) -> None:
    """日本語文字列をそのまま抽出する。"""
    file_path = tmp_path / "sample.json"
    write_json(file_path, {"message": "こんにちは"})

    document = JsonDocumentParser().parse(make_source_file(file_path))

    assert document.units[0].text == "こんにちは"


def test_json_document_parser_preserves_key_order(tmp_path: Path) -> None:
    """入力JSONのキー順を抽出順として維持する。"""
    file_path = tmp_path / "sample.json"
    file_path.write_text('{"b": 2, "a": 1, "c": 3}', encoding="utf-8")

    document = JsonDocumentParser().parse(make_source_file(file_path))

    assert [unit.locator for unit in document.units] == ["/b", "/a", "/c"]


def test_json_document_parser_raises_json_decode_error_for_invalid_json(
    tmp_path: Path,
) -> None:
    """不正JSONではJSONDecodeErrorを送出する。"""
    file_path = tmp_path / "invalid.json"
    file_path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        JsonDocumentParser().parse(make_source_file(file_path))
