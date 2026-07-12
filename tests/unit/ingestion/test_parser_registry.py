"""パーサーレジストリの単体テスト。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from signate_drive_rag.domain import ExtractedDocument, SourceFile
from signate_drive_rag.ingestion.parser_registry import (
    AmbiguousParserError,
    DuplicateParserError,
    ParserNotFoundError,
    ParserRegistry,
    create_default_parser_registry,
)


def make_source_file(path: Path) -> SourceFile:
    """テスト用のSourceFileを作成する。"""
    stat_result = path.stat()
    return SourceFile(
        path=path,
        relative_path=Path(path.name),
        name=path.name,
        suffix=path.suffix.lower(),
        mime_type=None,
        size_bytes=stat_result.st_size,
        modified_at=datetime.fromtimestamp(stat_result.st_mtime, tz=UTC),
    )


@dataclass(frozen=True, slots=True)
class FakeParser:
    """レジストリの選択動作だけを確認するための偽パーサー。"""

    name: str
    supported_suffixes: frozenset[str]

    def supports(self, source_file: SourceFile) -> bool:
        """対象ファイルを処理できるか判定する。"""
        return source_file.suffix.lower() in self.supported_suffixes

    def parse(self, source_file: SourceFile) -> ExtractedDocument:
        """このテストでは抽出処理を使用しない。"""
        return ExtractedDocument(source_file=source_file, parser_name=self.name, units=())


def test_parser_registry_finds_supported_parser(tmp_path: Path) -> None:
    """対応するパーサーを取得できる。"""
    file_path = tmp_path / "sample.txt"
    file_path.write_text("content", encoding="utf-8")
    parser = FakeParser(name="text", supported_suffixes=frozenset({".txt"}))
    registry = ParserRegistry()
    registry.register(parser)

    assert registry.find_parser(make_source_file(file_path)) == parser


def test_parser_registry_raises_when_parser_is_not_found(tmp_path: Path) -> None:
    """対応パーサーが存在しない場合は例外を送出する。"""
    file_path = tmp_path / "sample.pdf"
    file_path.write_text("content", encoding="utf-8")
    registry = ParserRegistry()
    registry.register(FakeParser(name="text", supported_suffixes=frozenset({".txt"})))

    with pytest.raises(ParserNotFoundError):
        registry.find_parser(make_source_file(file_path))


def test_parser_registry_raises_for_duplicate_parser_name() -> None:
    """同じ名前のパーサーを重複登録した場合は例外を送出する。"""
    registry = ParserRegistry()
    registry.register(FakeParser(name="text", supported_suffixes=frozenset({".txt"})))

    with pytest.raises(DuplicateParserError):
        registry.register(FakeParser(name="text", supported_suffixes=frozenset({".py"})))


def test_parser_registry_raises_when_multiple_parsers_support_file(tmp_path: Path) -> None:
    """複数パーサーが対応する場合は曖昧性エラーを送出する。"""
    file_path = tmp_path / "sample.txt"
    file_path.write_text("content", encoding="utf-8")
    registry = ParserRegistry()
    registry.register(FakeParser(name="text_a", supported_suffixes=frozenset({".txt"})))
    registry.register(FakeParser(name="text_b", supported_suffixes=frozenset({".txt"})))

    with pytest.raises(AmbiguousParserError):
        registry.find_parser(make_source_file(file_path))


def test_parser_registry_selection_does_not_depend_on_registration_order(
    tmp_path: Path,
) -> None:
    """登録順を変えても選択結果と曖昧性エラー条件が変わらない。"""
    text_path = tmp_path / "sample.txt"
    text_path.write_text("content", encoding="utf-8")
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_text("content", encoding="utf-8")
    text_parser = FakeParser(name="text", supported_suffixes=frozenset({".txt"}))
    pdf_parser = FakeParser(name="pdf", supported_suffixes=frozenset({".pdf"}))
    broad_parser = FakeParser(name="broad", supported_suffixes=frozenset({".txt"}))

    first_registry = ParserRegistry()
    first_registry.register(text_parser)
    first_registry.register(pdf_parser)
    second_registry = ParserRegistry()
    second_registry.register(pdf_parser)
    second_registry.register(text_parser)

    assert first_registry.find_parser(make_source_file(text_path)).name == "text"
    assert second_registry.find_parser(make_source_file(text_path)).name == "text"

    first_registry.register(broad_parser)
    second_registry.register(broad_parser)
    with pytest.raises(AmbiguousParserError):
        first_registry.find_parser(make_source_file(text_path))
    with pytest.raises(AmbiguousParserError):
        second_registry.find_parser(make_source_file(text_path))


@pytest.mark.parametrize(
    ("file_name", "parser_name"),
    [
        ("sample.md", "markdown"),
        ("sample.json", "json"),
        ("sample.ipynb", "notebook"),
        ("sample.csv", "delimited_text"),
        ("sample.tsv", "delimited_text"),
    ],
)
def test_default_parser_registry_selects_structured_document_parsers(
    tmp_path: Path,
    file_name: str,
    parser_name: str,
) -> None:
    """標準レジストリで構造化文書パーサーを拡張子から選択できる。"""
    file_path = tmp_path / file_name
    file_path.write_text("", encoding="utf-8")

    registry = create_default_parser_registry()

    assert registry.find_parser(make_source_file(file_path)).name == parser_name


@pytest.mark.parametrize("file_name", ["sample.csv", "sample.tsv"])
def test_default_parser_registry_selects_delimited_text_without_ambiguity(
    tmp_path: Path,
    file_name: str,
) -> None:
    """CSV・TSVで既存パーサーとの曖昧性が発生しない。"""
    file_path = tmp_path / file_name
    file_path.write_text("A,B\n1,2", encoding="utf-8")

    registry = create_default_parser_registry()

    assert registry.find_parser(make_source_file(file_path)).name == "delimited_text"
