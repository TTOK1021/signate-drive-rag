"""UTF-8のプレーンテキストファイルを抽出するパーサー。"""

from signate_drive_rag.domain.extracted_document import ExtractedDocument, ExtractedUnit
from signate_drive_rag.domain.source_file import SourceFile


class PlainTextParser:
    """UTF-8として読めるプレーンテキスト形式を抽出する。"""

    SUPPORTED_SUFFIXES = frozenset({".txt", ".py", ".toml", ".lock"})

    @property
    def name(self) -> str:
        """パーサーを識別する名前を返す。"""
        return "plain_text"

    def supports(self, source_file: SourceFile) -> bool:
        """対象ファイルを処理できるか判定する。"""
        return source_file.suffix.lower() in self.SUPPORTED_SUFFIXES

    def parse(self, source_file: SourceFile) -> ExtractedDocument:
        """原本ファイルからUTF-8テキストを抽出する。"""
        with source_file.path.open("r", encoding="utf-8", newline="") as source_stream:
            raw_text = source_stream.read()

        normalized_lines = raw_text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
        normalized_text = "\n".join(normalized_lines)
        line_count = 0 if raw_text == "" else len(normalized_lines)

        unit = ExtractedUnit(
            unit_type="text",
            text=normalized_text,
            locator=None,
            metadata={
                "encoding": "utf-8",
                "line_count": line_count,
            },
        )
        return ExtractedDocument(
            source_file=source_file,
            parser_name=self.name,
            units=(unit,),
        )
