"""Docling PoCシリアライザーのテスト。"""

import csv
import json
from pathlib import Path

import pytest

from signate_drive_rag.docling_poc.models import (
    ConvertedArtifact,
    DoclingPocManifest,
    DoclingPocResult,
    DoclingPocRun,
    DoclingPocSummary,
    SelectedDocument,
)
from signate_drive_rag.docling_poc.serializer import (
    DoclingPocOutputError,
    save_docling_poc_run,
)


def make_run() -> DoclingPocRun:
    """保存テスト用のPoC結果を作成する。"""
    sample_id = "a" * 64
    return DoclingPocRun(
        manifest=DoclingPocManifest(
            source_root_name="共有ドライブ",
            docling_version="2.113.0",
            profiles=("default_local",),
            formats=(".pdf",),
            samples_per_format=1,
            selection_strategy="size_quantile",
            timeout_seconds=180,
            preview_chars=20,
            remote_services_enabled=False,
            ocr_settings_by_profile={"default_local": {"engine": "docling_default"}},
            ocr_environment=None,
        ),
        selections=(
            SelectedDocument(
                sample_id=sample_id,
                relative_path="資料/サンプル.pdf",
                suffix=".pdf",
                size_bytes=123,
                selection_rank=1,
                selection_quantile=0.5,
            ),
        ),
        results=(
            DoclingPocResult(
                sample_id=sample_id,
                relative_path="資料/サンプル.pdf",
                suffix=".pdf",
                size_bytes=123,
                profile="default_local",
                status="success",
                elapsed_seconds=1.25,
                markdown_characters=8,
                text_characters=7,
                json_bytes=20,
                page_count=1,
                total_items=2,
                table_count=1,
                picture_count=0,
                heading_count=1,
                provenance_items=1,
                provenance_coverage=0.5,
                item_counts_by_label={"table": 1, "text": 1},
                output_directory=f"converted/{sample_id}/default_local",
                warnings=(),
                errors=(),
            ),
        ),
        artifacts=(
            ConvertedArtifact(
                sample_id=sample_id,
                profile="default_local",
                markdown="# 日本語",
                text="日本語本文",
                json_document={"text": "日本語本文"},
            ),
        ),
        summary=DoclingPocSummary(
            candidate_counts_by_suffix={".pdf": 1},
            selected_counts_by_suffix={".pdf": 1},
            executed_conversions=1,
            status_counts={
                "failed": 0,
                "partial_success": 0,
                "skipped": 0,
                "success": 1,
                "timeout": 0,
            },
            result_counts_by_suffix={
                ".pdf": {
                    "failed": 0,
                    "partial_success": 0,
                    "skipped": 0,
                    "success": 1,
                    "timeout": 0,
                }
            },
            average_elapsed_seconds_by_suffix={".pdf": 1.25},
            average_text_characters_by_suffix={".pdf": 7.0},
            table_counts_by_suffix={".pdf": 1},
            average_provenance_coverage_by_suffix={".pdf": 0.5},
        ),
    )


def test_save_docling_poc_run_writes_jsonl_csv_report_and_artifacts(tmp_path: Path) -> None:
    """JSON、JSONL、CSV、Markdown、converted成果物を生成できる。"""
    output_dir = tmp_path / "docling_poc"

    save_docling_poc_run(make_run(), output_dir, overwrite=False)

    assert (
        json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))["docling_version"]
        == "2.113.0"
    )
    assert (
        json.loads((output_dir / "selection.jsonl").read_text(encoding="utf-8"))["relative_path"]
        == "資料/サンプル.pdf"
    )
    assert (
        json.loads((output_dir / "results.jsonl").read_text(encoding="utf-8"))["status"]
        == "success"
    )
    assert (output_dir / "errors.jsonl").read_text(encoding="utf-8") == ""
    assert (
        json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))[
            "executed_conversions"
        ]
        == 1
    )
    assert (output_dir / "review.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    with (output_dir / "review.csv").open(encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert rows[0]["text_preview"] == "日本語本文"
    assert rows[0]["text_quality"] == ""
    assert "# Docling形式別PoCレポート" in (output_dir / "report.md").read_text(encoding="utf-8")
    artifact_dir = output_dir / "converted" / ("a" * 64) / "default_local"
    assert (artifact_dir / "document.md").read_text(encoding="utf-8") == "# 日本語"
    assert (
        json.loads((artifact_dir / "document.json").read_text(encoding="utf-8"))["text"]
        == "日本語本文"
    )
    assert (artifact_dir / "document.txt").read_text(encoding="utf-8") == "日本語本文"
    assert not (tmp_path / "docling_poc.tmp").exists()


def test_save_docling_poc_run_does_not_overwrite_without_flag(tmp_path: Path) -> None:
    """overwriteなしでは既存出力を壊さない。"""
    output_dir = tmp_path / "docling_poc"
    output_dir.mkdir()
    marker = output_dir / "marker.txt"
    marker.write_text("old", encoding="utf-8")

    with pytest.raises(DoclingPocOutputError):
        save_docling_poc_run(make_run(), output_dir, overwrite=False)

    assert marker.read_text(encoding="utf-8") == "old"


def test_save_docling_poc_run_overwrites_existing_output(tmp_path: Path) -> None:
    """overwrite指定時だけ既存出力を置き換える。"""
    output_dir = tmp_path / "docling_poc"
    output_dir.mkdir()
    (output_dir / "old.txt").write_text("old", encoding="utf-8")

    save_docling_poc_run(make_run(), output_dir, overwrite=True)

    assert not (output_dir / "old.txt").exists()
    assert (output_dir / "manifest.json").exists()
