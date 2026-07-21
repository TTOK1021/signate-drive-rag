"""抽出結果監査のモデル。"""

from dataclasses import dataclass

from signate_drive_rag.domain.extracted_document import JsonValue


@dataclass(frozen=True, slots=True)
class AuditUnit:
    """監査対象となる抽出単位。"""

    unit_type: str
    text: str
    locator: str | None
    metadata: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class AuditDocument:
    """監査対象となる抽出済み文書。"""

    relative_path: str
    name: str
    suffix: str
    size_bytes: int
    parser_name: str
    units: tuple[AuditUnit, ...]
    extraction_issues: tuple["AuditIssue", ...] = ()


@dataclass(frozen=True, slots=True)
class AuditIssue:
    """抽出結果から検出した品質上の問題。"""

    relative_path: str
    parser_name: str
    issue_type: str
    severity: str
    message: str
    unit_index: int | None = None
    locator: str | None = None
    metadata: dict[str, JsonValue] | None = None


@dataclass(frozen=True, slots=True)
class DistributionStatistics:
    """数値データの分布統計。"""

    count: int
    minimum: int
    maximum: int
    mean: float
    median: float
    percentile_95: float


@dataclass(frozen=True, slots=True)
class ParserAuditSummary:
    """パーサー単位の抽出品質集計。"""

    documents: int
    units: int
    characters: int
    source_bytes: int
    documents_with_no_units: int
    documents_with_no_text: int
    empty_units: int
    units_without_required_locator: int
    duplicate_units: int
    issues: int
    document_character_statistics: DistributionStatistics
    unit_character_statistics: DistributionStatistics


@dataclass(frozen=True, slots=True)
class AuditSummary:
    """抽出品質監査の集計結果。"""

    documents: int
    total_units: int
    total_characters: int
    total_source_bytes: int
    documents_with_no_units: int
    documents_with_no_text: int
    empty_units: int
    units_without_required_locator: int
    duplicate_units: int
    large_units: int
    pdf_pages: int
    pdf_pages_with_text: int
    pdf_pages_needing_ocr: int
    png_documents: int
    png_ocr_success: int
    png_ocr_no_text: int
    png_ocr_failed: int
    pdf_pages_ocr_targeted: int
    pdf_pages_ocr_success: int
    pdf_pages_ocr_no_text: int
    pdf_pages_ocr_failed: int
    ocr_regions_detected: int
    ocr_regions_included: int
    ocr_regions_low_confidence: int
    ocr_characters: int
    mean_ocr_confidence: float
    documents_with_ocr: int
    xlsx_sheets: int
    xlsx_row_blocks: int
    xlsx_non_empty_cells: int
    xlsx_formula_cells: int
    xlsx_formula_without_cached_values: int
    xlsx_merged_ranges: int
    xlsx_excel_tables: int
    xlsx_hidden_sheets: int
    xlsx_empty_sheets: int
    xlsx_large_sheets: int
    xlsx_very_wide_sheets: int
    total_issues: int
    issues_by_severity: dict[str, int]
    issues_by_type: dict[str, int]
    units_by_type: dict[str, int]
    by_parser: dict[str, ParserAuditSummary]
    document_character_statistics: DistributionStatistics
    unit_character_statistics: DistributionStatistics


@dataclass(frozen=True, slots=True)
class AuditSampleUnit:
    """目視確認用に抜粋した抽出単位。"""

    unit_index: int
    unit_type: str
    locator: str | None
    text_preview: str


@dataclass(frozen=True, slots=True)
class AuditSampleDocument:
    """目視確認用に抜粋した文書。"""

    relative_path: str
    parser_name: str
    source_size_bytes: int
    unit_count: int
    character_count: int
    sample_units: tuple[AuditSampleUnit, ...]


@dataclass(frozen=True, slots=True)
class AuditResult:
    """抽出品質監査の結果。"""

    summary: AuditSummary
    issues: tuple[AuditIssue, ...]
    samples: tuple[AuditSampleDocument, ...]
