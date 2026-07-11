"""ファイル形式ごとの抽出パーサー。"""

from signate_drive_rag.ingestion.parsers.base import DocumentParser
from signate_drive_rag.ingestion.parsers.plain_text import PlainTextParser

__all__ = ["DocumentParser", "PlainTextParser"]
