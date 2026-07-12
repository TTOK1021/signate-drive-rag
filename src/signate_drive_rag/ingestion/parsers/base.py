"""原本ファイル抽出パーサーの共通インターフェース。"""

from typing import Protocol

from signate_drive_rag.domain.extracted_document import ExtractedDocument
from signate_drive_rag.domain.source_file import SourceFile


class DocumentParser(Protocol):
    """原本ファイルから内容を抽出するパーサー。"""

    @property
    def name(self) -> str:
        """パーサーを識別する名前を返す。"""
        ...

    def supports(self, source_file: SourceFile) -> bool:
        """対象ファイルを処理できるか判定する。"""
        ...

    def parse(self, source_file: SourceFile) -> ExtractedDocument:
        """原本ファイルから内容を抽出する。"""
        ...
