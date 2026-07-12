"""ファイル形式に対応する抽出パーサーを管理するレジストリ。"""

from collections.abc import Mapping
from types import MappingProxyType

from signate_drive_rag.domain.source_file import SourceFile
from signate_drive_rag.ingestion.parsers.base import DocumentParser


class ParserRegistryError(Exception):
    """パーサー選択で発生する例外の基底クラス。"""


class ParserNotFoundError(ParserRegistryError):
    """対応するパーサーが見つからない場合の例外。"""


class DuplicateParserError(ParserRegistryError):
    """同じ名前のパーサーが重複登録された場合の例外。"""


class AmbiguousParserError(ParserRegistryError):
    """複数のパーサーが同じファイルへ対応する場合の例外。"""


class ParserRegistry:
    """ファイル形式に対応するパーサーを管理する。"""

    def __init__(self) -> None:
        """空のパーサーレジストリを作成する。"""
        self._parsers_by_name: dict[str, DocumentParser] = {}

    @property
    def parsers(self) -> Mapping[str, DocumentParser]:
        """登録済みパーサーを名前で参照する読み取り専用ビューを返す。"""
        return MappingProxyType(self._parsers_by_name)

    def register(self, parser: DocumentParser) -> None:
        """パーサーを登録する。"""
        if parser.name in self._parsers_by_name:
            raise DuplicateParserError(f"同じ名前のパーサーが登録されています: {parser.name}")

        self._parsers_by_name[parser.name] = parser

    def find_parser(self, source_file: SourceFile) -> DocumentParser:
        """対象ファイルを処理できるパーサーを取得する。"""
        matched_parsers = [
            parser for parser in self._parsers_by_name.values() if parser.supports(source_file)
        ]
        if not matched_parsers:
            raise ParserNotFoundError(
                f"対応するパーサーが見つかりません: {source_file.relative_path.as_posix()}"
            )
        if len(matched_parsers) > 1:
            parser_names = ", ".join(sorted(parser.name for parser in matched_parsers))
            raise AmbiguousParserError(
                f"複数のパーサーが対応しています: {source_file.relative_path.as_posix()} "
                f"({parser_names})"
            )

        return matched_parsers[0]


def create_default_parser_registry() -> ParserRegistry:
    """標準パーサーを登録したレジストリを作成する。"""
    from signate_drive_rag.ingestion.parsers import (
        DelimitedTextParser,
        JsonDocumentParser,
        MarkdownParser,
        NotebookParser,
        PlainTextParser,
    )

    registry = ParserRegistry()
    for parser in (
        PlainTextParser(),
        MarkdownParser(),
        JsonDocumentParser(),
        NotebookParser(),
        DelimitedTextParser(),
    ):
        registry.register(parser)
    return registry
