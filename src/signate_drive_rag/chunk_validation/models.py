"""検索用チャンク検証のモデル。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChunkValidationError:
    """検索用チャンクで検出した検証エラー。"""

    chunk_id: str | None
    relative_path: str | None
    issue_type: str
    severity: str
    message: str
    locator: str | None = None


@dataclass(frozen=True, slots=True)
class ChunkValidationSummary:
    """検索用チャンク検証の集計。"""

    chunks: int
    source_documents: int
    source_units: int
    errors: int
    warnings: int
    duplicate_chunk_ids: int
    duplicate_chunk_contents: int
    empty_text_chunks: int
    nul_text_chunks: int
    invalid_document_references: int
    invalid_unit_references: int
    absolute_path_violations: int
    invalid_locator_count: int
    json_metadata_errors: int
    oversized_chunks: int
    maximum_chunk_characters: int
    mean_chunk_characters: float
    median_chunk_characters: float
    p95_chunk_characters: float
    text_chunks: int
    table_chunks: int
    ocr_chunks: int


@dataclass(frozen=True, slots=True)
class ChunkValidationResult:
    """検索用チャンク検証の結果。"""

    summary: ChunkValidationSummary
    errors: tuple[ChunkValidationError, ...]
