"""監査結果シリアライザーの単体テスト。"""

import json
from pathlib import Path

from signate_drive_rag.audit.models import (
    AuditIssue,
    AuditResult,
    AuditSampleDocument,
    AuditSampleUnit,
    AuditSummary,
    DistributionStatistics,
    ParserAuditSummary,
)
from signate_drive_rag.audit.serializer import save_audit_result


def statistics() -> DistributionStatistics:
    """テスト用の分布統計を作成する。"""
    return DistributionStatistics(
        count=1,
        minimum=3,
        maximum=3,
        mean=3.0,
        median=3.0,
        percentile_95=3.0,
    )


def parser_summary() -> ParserAuditSummary:
    """テスト用のパーサー別集計を作成する。"""
    return ParserAuditSummary(
        documents=1,
        units=1,
        characters=3,
        source_bytes=10,
        documents_with_no_units=0,
        documents_with_no_text=0,
        empty_units=0,
        units_without_required_locator=0,
        duplicate_units=0,
        issues=0,
        document_character_statistics=statistics(),
        unit_character_statistics=statistics(),
    )


def audit_result(*, include_issue: bool = True, include_sample: bool = True) -> AuditResult:
    """テスト用の監査結果を作成する。"""
    issues = (
        (
            AuditIssue(
                relative_path="プロジェクト/資料.md",
                parser_name="markdown",
                issue_type="large_unit",
                severity="warning",
                message="大きいunitです",
                unit_index=0,
                locator="line:1-1",
            ),
        )
        if include_issue
        else ()
    )
    samples = (
        (
            AuditSampleDocument(
                relative_path="プロジェクト/資料.md",
                parser_name="markdown",
                source_size_bytes=10,
                unit_count=1,
                character_count=3,
                sample_units=(
                    AuditSampleUnit(
                        unit_index=0,
                        unit_type="markdown_section",
                        locator="line:1-1",
                        text_preview="本文",
                    ),
                ),
            ),
        )
        if include_sample
        else ()
    )
    return AuditResult(
        summary=AuditSummary(
            documents=1,
            total_units=1,
            total_characters=3,
            total_source_bytes=10,
            documents_with_no_units=0,
            documents_with_no_text=0,
            empty_units=0,
            units_without_required_locator=0,
            duplicate_units=0,
            large_units=1 if include_issue else 0,
            units_by_type={"markdown_section": 1},
            pdf_pages=0,
            pdf_pages_with_text=0,
            pdf_pages_needing_ocr=0,
            xlsx_sheets=0,
            xlsx_row_blocks=0,
            xlsx_non_empty_cells=0,
            xlsx_formula_cells=0,
            xlsx_formula_without_cached_values=0,
            xlsx_merged_ranges=0,
            xlsx_excel_tables=0,
            xlsx_hidden_sheets=0,
            xlsx_empty_sheets=0,
            xlsx_large_sheets=0,
            xlsx_very_wide_sheets=0,
            total_issues=len(issues),
            issues_by_severity={"error": 0, "warning": len(issues), "info": 0},
            issues_by_type={
                "document_has_no_units": 0,
                "document_has_no_text": 0,
                "empty_unit": 0,
                "missing_required_locator": 0,
                "invalid_locator_format": 0,
                "duplicate_unit_text": 0,
                "large_unit": len(issues),
            },
            by_parser={"markdown": parser_summary()},
            document_character_statistics=statistics(),
            unit_character_statistics=statistics(),
        ),
        issues=issues,
        samples=samples,
    )


def test_save_audit_result_writes_valid_json_files(tmp_path: Path) -> None:
    """summary.json、issues.jsonl、samples.jsonlを有効なJSONとして保存する。"""
    output_dir = tmp_path / "out"

    save_audit_result(audit_result(), output_dir)

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    issue = json.loads((output_dir / "issues.jsonl").read_text(encoding="utf-8"))
    sample = json.loads((output_dir / "samples.jsonl").read_text(encoding="utf-8"))
    assert summary["documents"] == 1
    assert issue["relative_path"] == "プロジェクト/資料.md"
    assert sample["sample_units"][0]["text_preview"] == "本文"


def test_save_audit_result_writes_empty_jsonl_when_no_records(tmp_path: Path) -> None:
    """issueとsampleが0件でも空ファイルを生成する。"""
    output_dir = tmp_path / "out"

    save_audit_result(audit_result(include_issue=False, include_sample=False), output_dir)

    assert (output_dir / "issues.jsonl").read_text(encoding="utf-8") == ""
    assert (output_dir / "samples.jsonl").read_text(encoding="utf-8") == ""


def test_save_audit_result_creates_output_directory_and_replaces_files(
    tmp_path: Path,
) -> None:
    """出力先を作成し、既存ファイルを置き換える。"""
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "summary.json").write_text("old", encoding="utf-8")

    save_audit_result(audit_result(), output_dir)

    assert (
        json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))["total_issues"] == 1
    )


def test_save_audit_result_leaves_no_temporary_files(tmp_path: Path) -> None:
    """正常終了後にtmpファイルを残さない。"""
    output_dir = tmp_path / "out"

    save_audit_result(audit_result(), output_dir)

    assert list(output_dir.glob("*.tmp")) == []


def test_save_audit_result_keeps_deterministic_order(tmp_path: Path) -> None:
    """同じ入力を2回保存しても出力順が変わらない。"""
    output_dir = tmp_path / "out"
    result = audit_result()

    save_audit_result(result, output_dir)
    first = (output_dir / "summary.json").read_text(encoding="utf-8")
    save_audit_result(result, output_dir)
    second = (output_dir / "summary.json").read_text(encoding="utf-8")

    assert first == second
