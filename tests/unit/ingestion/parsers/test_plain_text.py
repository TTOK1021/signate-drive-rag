"""プレーンテキストパーサーの単体テスト。"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from signate_drive_rag.domain import SourceFile
from signate_drive_rag.ingestion.parsers import PlainTextParser


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


@pytest.mark.parametrize("suffix", [".txt", ".py", ".toml", ".lock"])
def test_plain_text_parser_supports_plain_text_suffixes(
    tmp_path: Path,
    suffix: str,
) -> None:
    """対象拡張子のファイルを処理可能と判定する。"""
    file_path = tmp_path / f"sample{suffix}"
    file_path.write_text("content", encoding="utf-8")

    assert PlainTextParser().supports(make_source_file(file_path)) is True


def test_plain_text_parser_supports_suffix_case_insensitively(tmp_path: Path) -> None:
    """拡張子の大文字小文字を区別せず処理可能と判定する。"""
    file_path = tmp_path / "sample.TXT"
    file_path.write_text("content", encoding="utf-8")

    assert PlainTextParser().supports(make_source_file(file_path)) is True


def test_plain_text_parser_does_not_support_unknown_suffix(tmp_path: Path) -> None:
    """対象外拡張子では処理不可と判定する。"""
    file_path = tmp_path / "sample.pdf"
    file_path.write_text("content", encoding="utf-8")

    assert PlainTextParser().supports(make_source_file(file_path)) is False


def test_plain_text_parser_extracts_japanese_utf8_text(tmp_path: Path) -> None:
    """日本語のUTF-8テキストを抽出できる。"""
    file_path = tmp_path / "sample.txt"
    file_path.write_text("こんにちは\n世界", encoding="utf-8")

    document = PlainTextParser().parse(make_source_file(file_path))

    assert document.units[0].text == "こんにちは\n世界"


def test_plain_text_parser_normalizes_windows_line_endings(tmp_path: Path) -> None:
    """Windows形式の改行をLFへ統一することを確認する。"""
    file_path = tmp_path / "sample.txt"
    file_path.write_bytes(b"first\r\nsecond\r\n")

    document = PlainTextParser().parse(make_source_file(file_path))

    assert document.units[0].text == "first\nsecond"


def test_plain_text_parser_extracts_empty_file(tmp_path: Path) -> None:
    """空ファイルを空文字かつ0行として抽出する。"""
    file_path = tmp_path / "empty.txt"
    file_path.write_text("", encoding="utf-8")

    document = PlainTextParser().parse(make_source_file(file_path))

    assert len(document.units) == 1
    assert document.units[0].text == ""
    assert document.units[0].metadata["line_count"] == 0


@pytest.mark.parametrize(
    ("content", "expected_line_count"),
    [
        ("", 0),
        ("abc", 1),
        ("abc\n", 1),
        ("abc\ndef", 2),
    ],
)
def test_plain_text_parser_counts_lines_by_defined_rules(
    tmp_path: Path,
    content: str,
    expected_line_count: int,
) -> None:
    """空文字と末尾改行を含む行数定義を満たす。"""
    file_path = tmp_path / "sample.txt"
    file_path.write_text(content, encoding="utf-8")

    document = PlainTextParser().parse(make_source_file(file_path))

    assert document.units[0].metadata["line_count"] == expected_line_count


def test_plain_text_parser_preserves_source_file_and_parser_name(tmp_path: Path) -> None:
    """抽出結果にSourceFileとパーサー名を保持する。"""
    file_path = tmp_path / "sample.py"
    file_path.write_text("print('hello')", encoding="utf-8")
    source_file = make_source_file(file_path)

    document = PlainTextParser().parse(source_file)

    assert document.source_file == source_file
    assert document.parser_name == "plain_text"


def test_plain_text_parser_raises_decode_error_for_invalid_utf8(tmp_path: Path) -> None:
    """UTF-8として不正なファイルでは読み込みエラーを送出する。"""
    file_path = tmp_path / "invalid.txt"
    file_path.write_bytes(b"\xff\xfe")

    with pytest.raises(UnicodeDecodeError):
        PlainTextParser().parse(make_source_file(file_path))
