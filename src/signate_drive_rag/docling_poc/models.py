"""Docling形式別PoCのデータモデル。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from signate_drive_rag.domain.extracted_document import JsonValue

SUPPORTED_DOCLING_SUFFIXES = frozenset({".docx", ".pptx", ".pdf", ".xlsx", ".png"})
DEFAULT_DOCLING_PROFILES = ("default_local", "japanese_ocr")
SUPPORTED_DOCLING_PROFILES = frozenset(DEFAULT_DOCLING_PROFILES)
JAPANESE_OCR_SUFFIXES = frozenset({".pdf", ".png"})


@dataclass(frozen=True, slots=True)
class SelectedDocument:
    """Docling PoCで変換する代表文書。"""

    sample_id: str
    relative_path: str
    suffix: str
    size_bytes: int
    selection_rank: int
    selection_quantile: float


@dataclass(frozen=True, slots=True)
class ConversionOutput:
    """Doclingアダプターが返す変換結果。"""

    status: str
    markdown: str
    text: str
    json_document: dict[str, JsonValue]
    document: object | None
    warnings: tuple[str, ...]
    errors: tuple[str, ...]


class DocumentConversionAdapter(Protocol):
    """文書を統一形式へ変換するアダプター。"""

    def convert(
        self,
        source_path: Path,
        *,
        profile: str,
        timeout_seconds: int,
    ) -> ConversionOutput:
        """指定プロファイルで文書を変換する。"""
        ...


@dataclass(frozen=True, slots=True)
class DocumentStructureSummary:
    """DoclingDocumentから集計した構造情報。"""

    page_count: int | None
    total_items: int
    text_item_count: int
    paragraph_count: int
    list_item_count: int
    table_count: int
    picture_count: int
    heading_count: int
    provenance_items: int
    provenance_coverage: float
    item_counts_by_label: dict[str, int]


@dataclass(frozen=True, slots=True)
class ConvertedArtifact:
    """converted配下へ保存する変換本文。"""

    sample_id: str
    profile: str
    markdown: str
    text: str
    json_document: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class DoclingPocResult:
    """1ファイル・1プロファイルの変換結果。"""

    sample_id: str
    relative_path: str
    suffix: str
    size_bytes: int
    profile: str
    status: str
    elapsed_seconds: float
    markdown_characters: int
    text_characters: int
    json_bytes: int
    page_count: int | None
    total_items: int
    table_count: int
    picture_count: int
    heading_count: int
    provenance_items: int
    provenance_coverage: float
    item_counts_by_label: dict[str, int]
    output_directory: str | None
    warnings: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DoclingPocSummary:
    """Docling形式別PoCの集計情報。"""

    candidate_counts_by_suffix: dict[str, int]
    selected_counts_by_suffix: dict[str, int]
    executed_conversions: int
    status_counts: dict[str, int]
    result_counts_by_suffix: dict[str, dict[str, int]]
    average_elapsed_seconds_by_suffix: dict[str, float]
    average_text_characters_by_suffix: dict[str, float]
    table_counts_by_suffix: dict[str, int]
    average_provenance_coverage_by_suffix: dict[str, float]


@dataclass(frozen=True, slots=True)
class DoclingPocManifest:
    """Docling形式別PoCの実行条件。"""

    source_root_name: str
    docling_version: str
    profiles: tuple[str, ...]
    formats: tuple[str, ...]
    samples_per_format: int
    selection_strategy: str
    timeout_seconds: int
    preview_chars: int
    remote_services_enabled: bool
    ocr_settings_by_profile: dict[str, dict[str, JsonValue]]
    ocr_environment: dict[str, JsonValue] | None


@dataclass(frozen=True, slots=True)
class DoclingPocRun:
    """Docling形式別PoC全体の結果。"""

    manifest: DoclingPocManifest
    selections: tuple[SelectedDocument, ...]
    results: tuple[DoclingPocResult, ...]
    artifacts: tuple[ConvertedArtifact, ...]
    summary: DoclingPocSummary
