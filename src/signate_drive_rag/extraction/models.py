"""一括抽出処理の結果を表すモデル。"""

from dataclasses import dataclass

from signate_drive_rag.domain import ExtractedDocument, SourceFile


@dataclass(frozen=True, slots=True)
class ExtractionFailure:
    """原本ファイルの抽出に失敗した情報。"""

    source_file: SourceFile
    parser_name: str
    error_type: str
    error_message: str


@dataclass(frozen=True, slots=True)
class ExtractionSummary:
    """一括抽出処理の集計情報。"""

    discovered_files: int
    supported_files: int
    succeeded_files: int
    failed_files: int
    unsupported_files: int
    total_units: int
    total_characters: int
    by_parser: dict[str, int]
    by_suffix: dict[str, int]


@dataclass(frozen=True, slots=True)
class BatchExtractionResult:
    """一括抽出処理の結果。"""

    documents: tuple[ExtractedDocument, ...]
    failures: tuple[ExtractionFailure, ...]
    unsupported_files: tuple[SourceFile, ...]
    summary: ExtractionSummary
