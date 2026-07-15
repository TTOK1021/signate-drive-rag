"""検索用チャンク生成のモデル。"""

from dataclasses import dataclass

from signate_drive_rag.domain.extracted_document import JsonValue


@dataclass(frozen=True, slots=True)
class ChunkSourceUnit:
    """検索用チャンクの生成元となる抽出単位。"""

    unit_type: str
    text: str
    locator: str | None
    metadata: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ChunkSourceDocument:
    """検索用チャンクの生成元となる抽出済み文書。"""

    relative_path: str
    name: str
    suffix: str
    size_bytes: int
    parser_name: str
    units: tuple[ChunkSourceUnit, ...]


@dataclass(frozen=True, slots=True)
class RetrievalChunk:
    """検索インデックスへ登録する検索用チャンク。"""

    chunk_id: str
    relative_path: str
    parser_name: str
    unit_type: str
    text: str
    locator: str | None
    source_unit_indices: tuple[int, ...]
    chunk_index: int
    metadata: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ChunkIssue:
    """検索用チャンク生成時に検出した問題。"""

    relative_path: str
    parser_name: str
    issue_type: str
    severity: str
    message: str
    source_unit_index: int | None = None
    locator: str | None = None


@dataclass(frozen=True, slots=True)
class ChunkingSummary:
    """検索用チャンク生成結果の集計。"""

    source_documents: int
    source_units: int
    source_characters: int
    generated_chunks: int
    chunk_characters: int
    maximum_chunk_characters: int
    average_chunk_characters: float
    character_reduction_rate: float
    empty_units_skipped: int
    fallback_units: int
    total_issues: int
    issues_by_severity: dict[str, int]
    issues_by_type: dict[str, int]
    by_parser: dict[str, JsonValue]
    by_unit_type: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ChunkingResult:
    """検索用チャンク生成処理の結果。"""

    chunks: tuple[RetrievalChunk, ...]
    issues: tuple[ChunkIssue, ...]
    summary: ChunkingSummary
