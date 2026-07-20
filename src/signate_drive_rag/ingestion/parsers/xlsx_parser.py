"""XLSXをopenpyxlで構造付き抽出するパーサー。"""

from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from signate_drive_rag.domain import ExtractedDocument, ExtractedUnit, ExtractionIssue, JsonValue
from signate_drive_rag.domain.source_file import SourceFile
from signate_drive_rag.ingestion.parsers.extraction_issue import (
    XLSX_FORMULA_CACHED_VALUE_MISSING,
    XLSX_HIDDEN_SHEET,
    XLSX_LARGE_CELL_VALUE,
    XLSX_LARGE_SHEET,
    XLSX_METADATA_LIMITED,
    XLSX_SHEET_HAS_NO_CELLS,
    XLSX_VERY_WIDE_SHEET,
    extraction_issue,
)
from signate_drive_rag.ingestion.parsers.xlsx_adapter import (
    OpenpyxlWorkbookAdapter,
    SheetInspection,
    WorkbookInspection,
    XlsxParserOptions,
    XlsxWorkbookAdapter,
    XlsxWorkbookError,
)
from signate_drive_rag.ingestion.parsers.xlsx_region_builder import build_xlsx_row_block_units


class XlsxParserError(RuntimeError):
    """XLSX文書全体を処理できない場合の例外。"""


class XlsxParser:
    """XLSXをシート・セル範囲単位の抽出結果へ変換する。"""

    SUPPORTED_SUFFIXES: ClassVar[frozenset[str]] = frozenset({".xlsx"})

    def __init__(
        self,
        adapter: XlsxWorkbookAdapter | None = None,
        options: XlsxParserOptions | None = None,
    ) -> None:
        """openpyxl依存はアダプター差し替えで単体テスト可能にする。"""
        self._adapter = adapter if adapter is not None else OpenpyxlWorkbookAdapter()
        self._options = options if options is not None else XlsxParserOptions()

    @property
    def name(self) -> str:
        """パーサーを識別する名前を返す。"""
        return "openpyxl_xlsx"

    def supports(self, source_file: SourceFile) -> bool:
        """対象ファイルを処理できるか判定する。"""
        return source_file.suffix.lower() in self.SUPPORTED_SUFFIXES

    def parse(self, source_file: SourceFile) -> ExtractedDocument:
        """XLSXをワークブック要約、シート要約、行ブロックへ変換する。"""
        try:
            inspection = self._adapter.inspect(source_file.path, self._options)
            sheet_extractions = tuple(
                _extract_sheet(
                    self._adapter,
                    source_file.path,
                    sheet,
                    inspection,
                    self._options,
                )
                for sheet in inspection.sheets
            )
        except XlsxWorkbookError as error:
            raise XlsxParserError(f"{error.issue_type}: {_safe_message(str(error))}") from error
        except Exception as error:
            message = str(error).replace(str(source_file.path), "<source>")
            raise XlsxParserError(f"xlsx_unreadable: {_safe_message(message)}") from error

        document_metadata = _document_metadata(inspection, sheet_extractions)
        units = (
            _workbook_summary_unit(inspection, document_metadata),
            *(
                unit
                for sheet_extraction in sheet_extractions
                for unit in (
                    _sheet_summary_unit(sheet_extraction.sheet, document_metadata),
                    *sheet_extraction.units,
                )
            ),
        )
        issues = _document_issues(inspection, sheet_extractions, self._options)
        return ExtractedDocument(
            source_file=source_file,
            parser_name=self.name,
            units=units,
            issues=issues,
        )


class _SheetExtraction:
    """シート単位の抽出結果をまとめる内部値。"""

    def __init__(
        self,
        *,
        sheet: SheetInspection,
        units: tuple[ExtractedUnit, ...],
        formula_without_cached_value_count: int,
        large_cell_value_count: int,
    ) -> None:
        self.sheet = sheet
        self.units = units
        self.formula_without_cached_value_count = formula_without_cached_value_count
        self.large_cell_value_count = large_cell_value_count


def _extract_sheet(
    adapter: XlsxWorkbookAdapter,
    source_path: Path,
    sheet: SheetInspection,
    inspection: WorkbookInspection,
    options: XlsxParserOptions,
) -> _SheetExtraction:
    rows = tuple(adapter.iter_sheet_rows(source_path, sheet.sheet_name, sheet))
    build_result = build_xlsx_row_block_units(
        rows=rows,
        sheet=sheet,
        formulas=inspection.formulas.get(sheet.sheet_name, {}),
        options=options,
    )
    return _SheetExtraction(
        sheet=sheet,
        units=build_result.units,
        formula_without_cached_value_count=build_result.formula_without_cached_value_count,
        large_cell_value_count=build_result.large_cell_value_count,
    )


def _workbook_summary_unit(
    inspection: WorkbookInspection,
    document_metadata: dict[str, JsonValue],
) -> ExtractedUnit:
    sheet_names = [sheet.sheet_name for sheet in inspection.sheets]
    text = "\n".join(
        [
            "Excelワークブック",
            f"シート数: {len(inspection.sheets)}",
            f"シート: {', '.join(sheet_names)}",
            f"非表示シート数: {_sheet_state_count(inspection.sheets, 'hidden')}",
            f"定義名数: {len(inspection.defined_names)}",
            f"数式セル数: {sum(sheet.formula_cell_count for sheet in inspection.sheets)}",
        ]
    )
    metadata: dict[str, JsonValue] = {
        **document_metadata,
        "sheet_names": list(sheet_names),
        "defined_names": [
            {
                "defined_name": defined_name.defined_name,
                "destination_sheet": defined_name.destination_sheet,
                "destination_range": defined_name.destination_range,
            }
            for defined_name in inspection.defined_names
        ],
    }
    return ExtractedUnit(
        unit_type="xlsx_workbook_summary",
        text=text,
        locator="workbook",
        metadata=metadata,
    )


def _sheet_summary_unit(
    sheet: SheetInspection,
    document_metadata: dict[str, JsonValue],
) -> ExtractedUnit:
    text = "\n".join(
        [
            f"シート名: {sheet.sheet_name}",
            f"状態: {sheet.sheet_state}",
            f"使用範囲: {sheet.declared_dimension}",
            f"実データ範囲: {sheet.actual_dimension or ''}",
            f"非空セル数: {sheet.non_empty_cell_count}",
            f"数式セル数: {sheet.formula_cell_count}",
            f"結合セル範囲数: {len(sheet.merged_ranges)}",
            f"Excelテーブル数: {len(sheet.tables)}",
            f"非表示行数: {len(sheet.hidden_rows)}",
            f"非表示列数: {len(sheet.hidden_columns)}",
        ]
    )
    metadata: dict[str, JsonValue] = {
        "sheet_name": sheet.sheet_name,
        "sheet_index": sheet.sheet_index,
        "sheet_state": sheet.sheet_state,
        "declared_dimension": sheet.declared_dimension,
        "actual_dimension": sheet.actual_dimension,
        "min_row": sheet.min_row,
        "max_row": sheet.max_row,
        "min_column": sheet.min_column,
        "max_column": sheet.max_column,
        "non_empty_cell_count": sheet.non_empty_cell_count,
        "formula_cell_count": sheet.formula_cell_count,
        "merged_range_count": len(sheet.merged_ranges),
        "table_count": len(sheet.tables),
        "hidden_row_count": len(sheet.hidden_rows),
        "hidden_column_count": len(sheet.hidden_columns),
        "document_metadata": document_metadata,
    }
    return ExtractedUnit(
        unit_type="xlsx_sheet_summary",
        text=text,
        locator=f"sheet:{sheet.sheet_name}",
        metadata=metadata,
    )


def _document_metadata(
    inspection: WorkbookInspection,
    sheet_extractions: Sequence[_SheetExtraction],
) -> dict[str, JsonValue]:
    row_block_count = sum(len(sheet.units) for sheet in sheet_extractions)
    text_characters = sum(len(unit.text) for sheet in sheet_extractions for unit in sheet.units)
    return {
        "openpyxl_version": inspection.openpyxl_version,
        "defusedxml_available": inspection.defusedxml_available,
        "openpyxl_license": inspection.openpyxl_license,
        "defusedxml_license": inspection.defusedxml_license,
        "sheet_count": len(inspection.sheets),
        "visible_sheet_count": _sheet_state_count(inspection.sheets, "visible"),
        "hidden_sheet_count": _sheet_state_count(inspection.sheets, "hidden"),
        "very_hidden_sheet_count": _sheet_state_count(inspection.sheets, "veryHidden"),
        "non_empty_cell_count": sum(sheet.non_empty_cell_count for sheet in inspection.sheets),
        "formula_cell_count": sum(sheet.formula_cell_count for sheet in inspection.sheets),
        "formula_without_cached_value_count": sum(
            sheet.formula_without_cached_value_count for sheet in sheet_extractions
        ),
        "merged_range_count": sum(len(sheet.merged_ranges) for sheet in inspection.sheets),
        "excel_table_count": sum(len(sheet.tables) for sheet in inspection.sheets),
        "row_block_count": row_block_count,
        "text_characters": text_characters,
        "largest_sheet_rows": max((sheet.max_row or 0 for sheet in inspection.sheets), default=0),
        "largest_sheet_columns": max(
            (sheet.max_column or 0 for sheet in inspection.sheets),
            default=0,
        ),
        "zip_uncompressed_bytes": inspection.zip_uncompressed_bytes,
        "zip_compressed_bytes": inspection.zip_compressed_bytes,
        "zip_compression_ratio": inspection.zip_compression_ratio,
    }


def _document_issues(
    inspection: WorkbookInspection,
    sheet_extractions: Sequence[_SheetExtraction],
    options: XlsxParserOptions,
) -> tuple[ExtractionIssue, ...]:
    issues: list[ExtractionIssue] = []
    if inspection.metadata_limited:
        issues.append(
            extraction_issue(
                XLSX_METADATA_LIMITED,
                message="ファイルサイズが上限を超えるため詳細metadata取得を省略しました。",
                metadata={"threshold": options.metadata_inspection_max_file_bytes},
            )
        )
    for sheet_extraction in sheet_extractions:
        sheet = sheet_extraction.sheet
        if sheet.non_empty_cell_count == 0:
            issues.append(
                extraction_issue(
                    XLSX_SHEET_HAS_NO_CELLS,
                    message="非空セルのないシートです。",
                    locator=f"sheet:{sheet.sheet_name}",
                    metadata=_sheet_issue_metadata(sheet),
                )
            )
        if sheet.sheet_state != "visible":
            issues.append(
                extraction_issue(
                    XLSX_HIDDEN_SHEET,
                    message="非表示シートを抽出対象に含めました。",
                    locator=f"sheet:{sheet.sheet_name}",
                    metadata=_sheet_issue_metadata(sheet),
                )
            )
        if (sheet.max_row or 0) >= options.large_sheet_row_threshold:
            issues.append(
                extraction_issue(
                    XLSX_LARGE_SHEET,
                    message="行数が大規模シートしきい値以上です。",
                    locator=f"sheet:{sheet.sheet_name}",
                    metadata={
                        **_sheet_issue_metadata(sheet),
                        "threshold": options.large_sheet_row_threshold,
                    },
                )
            )
        if (sheet.max_column or 0) >= options.very_wide_sheet_column_threshold:
            issues.append(
                extraction_issue(
                    XLSX_VERY_WIDE_SHEET,
                    message="列数が幅広シートしきい値以上です。",
                    locator=f"sheet:{sheet.sheet_name}",
                    metadata={
                        **_sheet_issue_metadata(sheet),
                        "threshold": options.very_wide_sheet_column_threshold,
                    },
                )
            )
        if sheet_extraction.formula_without_cached_value_count > 0:
            issues.append(
                extraction_issue(
                    XLSX_FORMULA_CACHED_VALUE_MISSING,
                    message="保存済み計算結果のない数式セルがあります。",
                    locator=f"sheet:{sheet.sheet_name}",
                    metadata={
                        **_sheet_issue_metadata(sheet),
                        "formula_without_cached_value_count": (
                            sheet_extraction.formula_without_cached_value_count
                        ),
                    },
                )
            )
        if sheet_extraction.large_cell_value_count > 0:
            issues.append(
                extraction_issue(
                    XLSX_LARGE_CELL_VALUE,
                    message="長大なセル値を含むシートです。",
                    locator=f"sheet:{sheet.sheet_name}",
                    metadata={
                        **_sheet_issue_metadata(sheet),
                        "large_cell_value_count": sheet_extraction.large_cell_value_count,
                    },
                )
            )
    return tuple(sorted(issues, key=lambda issue: (issue.locator or "", issue.issue_type)))


def _sheet_issue_metadata(sheet: SheetInspection) -> dict[str, JsonValue]:
    return {
        "sheet_name": sheet.sheet_name,
        "sheet_index": sheet.sheet_index,
        "sheet_state": sheet.sheet_state,
        "non_empty_cell_count": sheet.non_empty_cell_count,
        "max_row": sheet.max_row,
        "max_column": sheet.max_column,
    }


def _sheet_state_count(sheets: Sequence[SheetInspection], state: str) -> int:
    counter = Counter(sheet.sheet_state for sheet in sheets)
    return counter[state]


def _safe_message(message: str) -> str:
    if len(message) > 500:
        return message[:500] + "..."
    return message
