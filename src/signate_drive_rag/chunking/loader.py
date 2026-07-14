"""documents.jsonlをチャンク生成用モデルへ読み込む処理。"""

from pathlib import Path

from signate_drive_rag.audit import AuditInputError, load_audit_documents
from signate_drive_rag.chunking.models import ChunkSourceDocument, ChunkSourceUnit

ChunkInputError = AuditInputError


def load_chunk_source_documents(documents_path: Path) -> tuple[ChunkSourceDocument, ...]:
    """documents.jsonlを読み込み、チャンク生成用文書へ変換する。"""
    return tuple(
        ChunkSourceDocument(
            relative_path=document.relative_path,
            name=document.name,
            suffix=document.suffix,
            size_bytes=document.size_bytes,
            parser_name=document.parser_name,
            units=tuple(
                ChunkSourceUnit(
                    unit_type=unit.unit_type,
                    text=unit.text,
                    locator=unit.locator,
                    metadata=unit.metadata,
                )
                for unit in document.units
            ),
        )
        for document in load_audit_documents(documents_path)
    )
