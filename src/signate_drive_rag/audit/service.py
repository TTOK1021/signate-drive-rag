"""抽出済み文書の品質を監査するサービス。"""

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import mean, median

from signate_drive_rag.audit.models import (
    AuditDocument,
    AuditIssue,
    AuditResult,
    AuditSampleDocument,
    AuditSampleUnit,
    AuditSummary,
    AuditUnit,
    DistributionStatistics,
    ParserAuditSummary,
)

DEFAULT_LARGE_UNIT_CHARS = 20_000
DEFAULT_SAMPLES_PER_PARSER = 3
DEFAULT_PREVIEW_CHARS = 300

SEVERITIES = ("error", "warning", "info")
ISSUE_TYPES = (
    "document_has_no_units",
    "document_has_no_text",
    "empty_unit",
    "missing_required_locator",
    "invalid_locator_format",
    "duplicate_unit_text",
    "large_unit",
    "low_text_content",
    "image_dominant_document",
    "pdf_page_needs_ocr",
    "pdf_partially_needs_ocr",
    "pdf_page_extraction_failed",
    "pdf_encrypted_unreadable",
    "pdf_unreadable",
    "xlsx_not_ooxml",
    "xlsx_zip_unreadable",
    "xlsx_uncompressed_size_limit_exceeded",
    "xlsx_compression_ratio_limit_exceeded",
    "xlsx_unreadable",
    "xlsx_sheet_has_no_cells",
    "xlsx_hidden_sheet",
    "xlsx_metadata_limited",
    "xlsx_formula_cached_value_missing",
    "xlsx_large_sheet",
    "xlsx_very_wide_sheet",
    "xlsx_large_cell_value",
)

_LOCATOR_PREFIX_BY_UNIT_TYPE = {
    "docx_heading": "item:",
    "docx_paragraph": "item:",
    "docx_list_item": "item:",
    "docx_table": "table:",
    "docx_table_row": "table:",
    "markdown_section": "line:",
    "notebook_cell": "cell:",
    "notebook_output": "cell:",
    "pdf_page_text": "page:",
    "pptx_slide_title": "slide:",
    "pptx_slide_text": "slide:",
    "pptx_speaker_notes": "slide:",
    "pptx_slide_table": "slide:",
    "pptx_slide_table_row": "slide:",
    "table_header": "row:",
    "table_row": "row:",
    "xlsx_workbook_summary": "workbook",
    "xlsx_sheet_summary": "sheet:",
    "xlsx_table_rows": "sheet:",
}


@dataclass(frozen=True, slots=True)
class _DocumentMetrics:
    """集計で再利用する文書単位の指標。"""

    document: AuditDocument
    unit_count: int
    character_count: int
    source_size_bytes: int
    empty_unit_count: int
    locator_issue_count: int
    duplicate_unit_count: int
    largest_unit_characters: int


class AuditService:
    """抽出済み文書の品質監査を実行する。"""

    def __init__(
        self,
        *,
        large_unit_chars: int = DEFAULT_LARGE_UNIT_CHARS,
        samples_per_parser: int = DEFAULT_SAMPLES_PER_PARSER,
        preview_chars: int = DEFAULT_PREVIEW_CHARS,
    ) -> None:
        """監査しきい値とサンプル条件を受け取る。"""
        if large_unit_chars < 0:
            raise ValueError("large_unit_chars must be greater than or equal to 0")
        if samples_per_parser < 0:
            raise ValueError("samples_per_parser must be greater than or equal to 0")
        if preview_chars < 0:
            raise ValueError("preview_chars must be greater than or equal to 0")
        self._large_unit_chars = large_unit_chars
        self._samples_per_parser = samples_per_parser
        self._preview_chars = preview_chars

    def audit(self, documents: Sequence[AuditDocument]) -> AuditResult:
        """抽出済み文書を監査し、集計・問題・サンプルを返す。"""
        sorted_documents = tuple(sorted(documents, key=lambda document: document.relative_path))
        metrics_by_path: dict[str, _DocumentMetrics] = {}
        issues: list[AuditIssue] = []

        for document in sorted_documents:
            document_issues = _audit_document(document, self._large_unit_chars)
            issues.extend(document_issues)
            metrics_by_path[document.relative_path] = _build_document_metrics(
                document,
                document_issues,
            )

        sorted_issues = tuple(sorted(issues, key=_issue_sort_key))
        summary = _build_summary(sorted_documents, metrics_by_path, sorted_issues)
        samples = _select_samples(
            sorted_documents,
            samples_per_parser=self._samples_per_parser,
            preview_chars=self._preview_chars,
        )
        return AuditResult(summary=summary, issues=sorted_issues, samples=samples)


def _audit_document(document: AuditDocument, large_unit_chars: int) -> list[AuditIssue]:
    """1文書に対して監査ルールを適用する。"""
    issues: list[AuditIssue] = list(document.extraction_issues)
    character_count = sum(len(unit.text) for unit in document.units)
    severity_for_empty_document = "info" if document.size_bytes == 0 else "warning"

    if len(document.units) == 0:
        issues.append(
            AuditIssue(
                relative_path=document.relative_path,
                parser_name=document.parser_name,
                issue_type="document_has_no_units",
                severity=severity_for_empty_document,
                message=f"抽出単位が0件です。source_size_bytes={document.size_bytes}",
            )
        )
    if character_count == 0 and not _has_issue(document.extraction_issues, "document_has_no_text"):
        issues.append(
            AuditIssue(
                relative_path=document.relative_path,
                parser_name=document.parser_name,
                issue_type="document_has_no_text",
                severity=severity_for_empty_document,
                message=f"抽出文字数が0です。source_size_bytes={document.size_bytes}",
            )
        )

    first_unit_index_by_text: dict[str, int] = {}
    for unit_index, unit in enumerate(document.units):
        issues.extend(_audit_unit(document, unit, unit_index, large_unit_chars))
        if unit.text == "":
            continue
        first_unit_index = first_unit_index_by_text.get(unit.text)
        if first_unit_index is None:
            first_unit_index_by_text[unit.text] = unit_index
            continue
        issues.append(
            AuditIssue(
                relative_path=document.relative_path,
                parser_name=document.parser_name,
                issue_type="duplicate_unit_text",
                severity="info",
                message=(
                    "同一文書内で同じ抽出テキストが再出現しました。"
                    f"first_unit_index={first_unit_index}, unit_index={unit_index}"
                ),
                unit_index=unit_index,
                locator=unit.locator,
            )
        )
    return issues


def _has_issue(issues: Sequence[AuditIssue], issue_type: str) -> bool:
    """パーサー由来issueと監査由来issueの重複を避ける。"""
    return any(issue.issue_type == issue_type for issue in issues)


def _audit_unit(
    document: AuditDocument,
    unit: AuditUnit,
    unit_index: int,
    large_unit_chars: int,
) -> list[AuditIssue]:
    """1抽出単位に対して監査ルールを適用する。"""
    issues: list[AuditIssue] = []
    if unit.text == "":
        issues.append(
            AuditIssue(
                relative_path=document.relative_path,
                parser_name=document.parser_name,
                issue_type="empty_unit",
                severity="info",
                message=(
                    f"空の抽出単位です。unit_index={unit_index}, "
                    f"unit_type={unit.unit_type}, locator={unit.locator}"
                ),
                unit_index=unit_index,
                locator=unit.locator,
            )
        )

    locator_issue_type = _locator_issue_type(unit)
    if locator_issue_type is not None:
        issues.append(
            AuditIssue(
                relative_path=document.relative_path,
                parser_name=document.parser_name,
                issue_type=locator_issue_type,
                severity="warning",
                message=(
                    f"locatorが期待形式を満たしません。unit_index={unit_index}, "
                    f"unit_type={unit.unit_type}, locator={unit.locator}"
                ),
                unit_index=unit_index,
                locator=unit.locator,
            )
        )

    unit_characters = len(unit.text)
    if unit_characters > large_unit_chars:
        issues.append(
            AuditIssue(
                relative_path=document.relative_path,
                parser_name=document.parser_name,
                issue_type="large_unit",
                severity="warning",
                message=(
                    f"抽出単位がしきい値を超えています。"
                    f"characters={unit_characters}, threshold={large_unit_chars}"
                ),
                unit_index=unit_index,
                locator=unit.locator,
            )
        )
    return issues


def _locator_issue_type(unit: AuditUnit) -> str | None:
    """unit_typeごとの必須locator検証結果を返す。"""
    if unit.unit_type == "json_value":
        return "missing_required_locator" if unit.locator is None else None
    expected_prefix = _LOCATOR_PREFIX_BY_UNIT_TYPE.get(unit.unit_type)
    if expected_prefix is None:
        return None
    if unit.locator is None:
        return "missing_required_locator"
    if not unit.locator.startswith(expected_prefix):
        return "invalid_locator_format"
    return None


def _build_document_metrics(
    document: AuditDocument,
    issues: Sequence[AuditIssue],
) -> _DocumentMetrics:
    """文書単位の集計値を作成する。"""
    return _DocumentMetrics(
        document=document,
        unit_count=len(document.units),
        character_count=sum(len(unit.text) for unit in document.units),
        source_size_bytes=document.size_bytes,
        empty_unit_count=sum(1 for unit in document.units if unit.text == ""),
        locator_issue_count=sum(
            1
            for issue in issues
            if issue.issue_type in {"missing_required_locator", "invalid_locator_format"}
        ),
        duplicate_unit_count=sum(
            1 for issue in issues if issue.issue_type == "duplicate_unit_text"
        ),
        largest_unit_characters=max((len(unit.text) for unit in document.units), default=0),
    )


def _build_summary(
    documents: Sequence[AuditDocument],
    metrics_by_path: dict[str, _DocumentMetrics],
    issues: Sequence[AuditIssue],
) -> AuditSummary:
    """監査結果全体の集計を作成する。"""
    metrics = [metrics_by_path[document.relative_path] for document in documents]
    issue_type_counts = _issue_count_dict([issue.issue_type for issue in issues], ISSUE_TYPES)
    severity_counts = _issue_count_dict([issue.severity for issue in issues], SEVERITIES)
    return AuditSummary(
        documents=len(documents),
        total_units=sum(metric.unit_count for metric in metrics),
        total_characters=sum(metric.character_count for metric in metrics),
        total_source_bytes=sum(metric.source_size_bytes for metric in metrics),
        documents_with_no_units=sum(1 for metric in metrics if metric.unit_count == 0),
        documents_with_no_text=sum(1 for metric in metrics if metric.character_count == 0),
        empty_units=sum(metric.empty_unit_count for metric in metrics),
        units_without_required_locator=sum(metric.locator_issue_count for metric in metrics),
        duplicate_units=sum(metric.duplicate_unit_count for metric in metrics),
        large_units=issue_type_counts["large_unit"],
        pdf_pages=_pdf_page_count(documents),
        pdf_pages_with_text=sum(
            1
            for document in documents
            for unit in document.units
            if unit.unit_type == "pdf_page_text"
        ),
        pdf_pages_needing_ocr=issue_type_counts["pdf_page_needs_ocr"],
        xlsx_sheets=_xlsx_metric_sum(documents, "sheet_count"),
        xlsx_row_blocks=sum(
            1
            for document in documents
            for unit in document.units
            if unit.unit_type == "xlsx_table_rows"
        ),
        xlsx_non_empty_cells=_xlsx_metric_sum(documents, "non_empty_cell_count"),
        xlsx_formula_cells=_xlsx_metric_sum(documents, "formula_cell_count"),
        xlsx_formula_without_cached_values=_xlsx_metric_sum(
            documents,
            "formula_without_cached_value_count",
        ),
        xlsx_merged_ranges=_xlsx_metric_sum(documents, "merged_range_count"),
        xlsx_excel_tables=_xlsx_metric_sum(documents, "excel_table_count"),
        xlsx_hidden_sheets=issue_type_counts["xlsx_hidden_sheet"],
        xlsx_empty_sheets=issue_type_counts["xlsx_sheet_has_no_cells"],
        xlsx_large_sheets=issue_type_counts["xlsx_large_sheet"],
        xlsx_very_wide_sheets=issue_type_counts["xlsx_very_wide_sheet"],
        total_issues=len(issues),
        issues_by_severity=severity_counts,
        issues_by_type=issue_type_counts,
        units_by_type=dict(
            sorted(
                Counter(unit.unit_type for document in documents for unit in document.units).items()
            )
        ),
        by_parser=_build_parser_summaries(documents, metrics_by_path, issues),
        document_character_statistics=distribution_statistics(
            [metric.character_count for metric in metrics]
        ),
        unit_character_statistics=distribution_statistics(
            [len(unit.text) for document in documents for unit in document.units]
        ),
    )


def _pdf_page_count(documents: Sequence[AuditDocument]) -> int:
    """pypdf由来metadataからPDFページ総数を文書単位で合計する。"""
    total = 0
    for document in documents:
        if document.parser_name != "pypdf":
            continue
        page_count = _document_page_count(document)
        if page_count is not None:
            total += page_count
            continue
        total += sum(1 for unit in document.units if unit.unit_type == "pdf_page_text")
    return total


def _document_page_count(document: AuditDocument) -> int | None:
    for unit in document.units:
        value = unit.metadata.get("page_count")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    for issue in document.extraction_issues:
        if issue.metadata is None:
            continue
        value = issue.metadata.get("page_count")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _xlsx_metric_sum(documents: Sequence[AuditDocument], key: str) -> int:
    """workbook summary metadataからXLSX文書単位の値を集計する。"""
    total = 0
    for document in documents:
        if document.parser_name != "openpyxl_xlsx":
            continue
        for unit in document.units:
            if unit.unit_type != "xlsx_workbook_summary":
                continue
            value = unit.metadata.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                total += value
            break
    return total


def _build_parser_summaries(
    documents: Sequence[AuditDocument],
    metrics_by_path: dict[str, _DocumentMetrics],
    issues: Sequence[AuditIssue],
) -> dict[str, ParserAuditSummary]:
    """パーサー別の集計を作成する。"""
    documents_by_parser: dict[str, list[AuditDocument]] = defaultdict(list)
    for document in documents:
        documents_by_parser[document.parser_name].append(document)

    summaries: dict[str, ParserAuditSummary] = {}
    for parser_name in sorted(documents_by_parser):
        parser_documents = documents_by_parser[parser_name]
        metrics = [metrics_by_path[document.relative_path] for document in parser_documents]
        parser_relative_paths = {document.relative_path for document in parser_documents}
        summaries[parser_name] = ParserAuditSummary(
            documents=len(parser_documents),
            units=sum(metric.unit_count for metric in metrics),
            characters=sum(metric.character_count for metric in metrics),
            source_bytes=sum(metric.source_size_bytes for metric in metrics),
            documents_with_no_units=sum(1 for metric in metrics if metric.unit_count == 0),
            documents_with_no_text=sum(1 for metric in metrics if metric.character_count == 0),
            empty_units=sum(metric.empty_unit_count for metric in metrics),
            units_without_required_locator=sum(metric.locator_issue_count for metric in metrics),
            duplicate_units=sum(metric.duplicate_unit_count for metric in metrics),
            issues=sum(1 for issue in issues if issue.relative_path in parser_relative_paths),
            document_character_statistics=distribution_statistics(
                [metric.character_count for metric in metrics]
            ),
            unit_character_statistics=distribution_statistics(
                [len(unit.text) for document in parser_documents for unit in document.units]
            ),
        )
    return summaries


def distribution_statistics(values: Sequence[int]) -> DistributionStatistics:
    """分布統計を決定的に計算する。"""
    if not values:
        return DistributionStatistics(
            count=0,
            minimum=0,
            maximum=0,
            mean=0.0,
            median=0.0,
            percentile_95=0.0,
        )
    sorted_values = sorted(values)
    return DistributionStatistics(
        count=len(sorted_values),
        minimum=sorted_values[0],
        maximum=sorted_values[-1],
        mean=float(mean(sorted_values)),
        median=float(median(sorted_values)),
        percentile_95=_percentile(sorted_values, 0.95),
    )


def _percentile(sorted_values: Sequence[int], percentile: float) -> float:
    """線形補間でパーセンタイルを計算する。"""
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * percentile
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    fraction = position - lower_index
    return float(
        sorted_values[lower_index]
        + (sorted_values[upper_index] - sorted_values[lower_index]) * fraction
    )


def _select_samples(
    documents: Sequence[AuditDocument],
    *,
    samples_per_parser: int,
    preview_chars: int,
) -> tuple[AuditSampleDocument, ...]:
    """パーサーごとに目視確認用サンプルを決定的に選択する。"""
    if samples_per_parser == 0:
        return ()

    documents_by_parser: dict[str, list[AuditDocument]] = defaultdict(list)
    for document in documents:
        documents_by_parser[document.parser_name].append(document)

    samples: list[AuditSampleDocument] = []
    for parser_name in sorted(documents_by_parser):
        parser_documents = sorted(
            documents_by_parser[parser_name],
            key=lambda document: document.relative_path,
        )
        for document_index in _select_evenly_spaced_indices(
            len(parser_documents),
            samples_per_parser,
        ):
            document = parser_documents[document_index]
            samples.append(_sample_document(document, preview_chars))
    return tuple(sorted(samples, key=lambda sample: (sample.parser_name, sample.relative_path)))


def _sample_document(document: AuditDocument, preview_chars: int) -> AuditSampleDocument:
    """文書から最大3件の抽出単位プレビューを作成する。"""
    unit_indices = _select_evenly_spaced_indices(len(document.units), 3)
    return AuditSampleDocument(
        relative_path=document.relative_path,
        parser_name=document.parser_name,
        source_size_bytes=document.size_bytes,
        unit_count=len(document.units),
        character_count=sum(len(unit.text) for unit in document.units),
        sample_units=tuple(
            AuditSampleUnit(
                unit_index=unit_index,
                unit_type=document.units[unit_index].unit_type,
                locator=document.units[unit_index].locator,
                text_preview=_preview_text(document.units[unit_index].text, preview_chars),
            )
            for unit_index in unit_indices
        ),
    )


def _select_evenly_spaced_indices(item_count: int, requested_count: int) -> tuple[int, ...]:
    """先頭・中央・末尾を含む等間隔のインデックスを選択する。"""
    if item_count == 0 or requested_count == 0:
        return ()
    if item_count <= requested_count:
        return tuple(range(item_count))
    if requested_count == 1:
        return (0,)

    selected: list[int] = []
    for sample_index in range(requested_count):
        index = round(sample_index * (item_count - 1) / (requested_count - 1))
        if index not in selected:
            selected.append(index)
    return tuple(selected)


def _preview_text(text: str, preview_chars: int) -> str:
    """本文を指定文字数までのプレビューに変換する。"""
    if preview_chars == 0:
        return ""
    if len(text) <= preview_chars:
        return text
    return f"{text[:preview_chars]}..."


def _issue_count_dict(values: Sequence[str], keys: Sequence[str]) -> dict[str, int]:
    """既知キーを0件でも含む集計辞書を返す。"""
    counter = Counter(values)
    return {key: counter[key] for key in keys}


def _issue_sort_key(issue: AuditIssue) -> tuple[str, int, str]:
    """issue出力を決定的に並べるためのキーを返す。"""
    unit_index = -1 if issue.unit_index is None else issue.unit_index
    return (issue.relative_path, unit_index, issue.issue_type)
