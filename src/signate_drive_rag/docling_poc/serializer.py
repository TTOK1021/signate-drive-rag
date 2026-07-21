"""Docling PoC成果物をファイルへ保存する処理。"""

import csv
import json
import shutil
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from signate_drive_rag.docling_poc.models import (
    ConvertedArtifact,
    DoclingPocManifest,
    DoclingPocResult,
    DoclingPocRun,
    DoclingPocSummary,
    SelectedDocument,
)


class DoclingPocOutputError(RuntimeError):
    """Docling PoC成果物の保存に失敗した場合の例外。"""


def save_docling_poc_run(run: DoclingPocRun, output_dir: Path, *, overwrite: bool) -> None:
    """PoC成果物全体を一時ディレクトリで構築してから置き換える。"""
    temporary_dir = output_dir.with_name(f"{output_dir.name}.tmp")
    backup_dir = output_dir.with_name(f"{output_dir.name}.bak")
    if output_dir.exists() and not overwrite:
        raise DoclingPocOutputError(f"出力先が既に存在します: {output_dir}")
    if temporary_dir.exists():
        shutil.rmtree(temporary_dir)
    if backup_dir.exists():
        shutil.rmtree(backup_dir)

    try:
        temporary_dir.mkdir(parents=True)
        _write_all_outputs(run, temporary_dir)
        if output_dir.exists():
            output_dir.replace(backup_dir)
        temporary_dir.replace(output_dir)
    except Exception:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        if backup_dir.exists() and not output_dir.exists():
            backup_dir.replace(output_dir)
        raise
    else:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)


def _write_all_outputs(run: DoclingPocRun, output_dir: Path) -> None:
    _write_json(output_dir / "manifest.json", _manifest_to_record(run.manifest))
    _write_jsonl(
        output_dir / "selection.jsonl",
        (_selection_to_record(selection) for selection in run.selections),
    )
    _write_jsonl(
        output_dir / "results.jsonl",
        (_result_to_record(result) for result in run.results),
    )
    _write_jsonl(
        output_dir / "errors.jsonl",
        (_error_to_record(result) for result in run.results if result.errors),
    )
    _write_json(output_dir / "summary.json", _summary_to_record(run.summary))
    _write_review_csv(output_dir / "review.csv", run)
    _write_text(output_dir / "report.md", _build_report(run))
    for artifact in run.artifacts:
        _write_artifact(output_dir, artifact)


def _write_json(path: Path, record: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as output_file:
        for record in records:
            output_file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _write_review_csv(path: Path, run: DoclingPocRun) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=_review_fieldnames())
        writer.writeheader()
        previews = _artifact_preview_by_key(run.artifacts, run.manifest.preview_chars)
        for result in run.results:
            text_preview, markdown_preview = previews.get(
                (result.sample_id, result.profile), ("", "")
            )
            writer.writerow(_review_row(result, text_preview, markdown_preview))


def _write_artifact(output_dir: Path, artifact: ConvertedArtifact) -> None:
    artifact_dir = output_dir / "converted" / artifact.sample_id / artifact.profile
    artifact_dir.mkdir(parents=True, exist_ok=True)
    _write_text(artifact_dir / "document.md", artifact.markdown)
    _write_json(artifact_dir / "document.json", artifact.json_document)
    _write_text(artifact_dir / "document.txt", artifact.text)


def _manifest_to_record(manifest: DoclingPocManifest) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_root_name": manifest.source_root_name,
        "docling_version": manifest.docling_version,
        "profiles": list(manifest.profiles),
        "formats": list(manifest.formats),
        "samples_per_format": manifest.samples_per_format,
        "selection_strategy": manifest.selection_strategy,
        "timeout_seconds": manifest.timeout_seconds,
        "preview_chars": manifest.preview_chars,
        "remote_services_enabled": manifest.remote_services_enabled,
        "ocr_settings_by_profile": manifest.ocr_settings_by_profile,
        "ocr_environment": manifest.ocr_environment,
    }


def _selection_to_record(selection: SelectedDocument) -> dict[str, Any]:
    return {
        "sample_id": selection.sample_id,
        "relative_path": selection.relative_path,
        "suffix": selection.suffix,
        "size_bytes": selection.size_bytes,
        "selection_rank": selection.selection_rank,
        "selection_quantile": selection.selection_quantile,
    }


def _result_to_record(result: DoclingPocResult) -> dict[str, Any]:
    return {
        "sample_id": result.sample_id,
        "relative_path": result.relative_path,
        "suffix": result.suffix,
        "size_bytes": result.size_bytes,
        "profile": result.profile,
        "status": result.status,
        "elapsed_seconds": result.elapsed_seconds,
        "markdown_characters": result.markdown_characters,
        "text_characters": result.text_characters,
        "json_bytes": result.json_bytes,
        "page_count": result.page_count,
        "total_items": result.total_items,
        "table_count": result.table_count,
        "picture_count": result.picture_count,
        "heading_count": result.heading_count,
        "provenance_items": result.provenance_items,
        "provenance_coverage": result.provenance_coverage,
        "item_counts_by_label": dict(sorted(result.item_counts_by_label.items())),
        "output_directory": result.output_directory,
        "warnings": list(result.warnings),
        "errors": list(result.errors),
    }


def _error_to_record(result: DoclingPocResult) -> dict[str, Any]:
    return {
        "sample_id": result.sample_id,
        "relative_path": result.relative_path,
        "suffix": result.suffix,
        "profile": result.profile,
        "status": result.status,
        "errors": list(result.errors),
    }


def _summary_to_record(summary: DoclingPocSummary) -> dict[str, Any]:
    return {
        "candidate_counts_by_suffix": dict(sorted(summary.candidate_counts_by_suffix.items())),
        "selected_counts_by_suffix": dict(sorted(summary.selected_counts_by_suffix.items())),
        "executed_conversions": summary.executed_conversions,
        "status_counts": dict(sorted(summary.status_counts.items())),
        "result_counts_by_suffix": {
            suffix: dict(sorted(counts.items()))
            for suffix, counts in sorted(summary.result_counts_by_suffix.items())
        },
        "average_elapsed_seconds_by_suffix": dict(
            sorted(summary.average_elapsed_seconds_by_suffix.items())
        ),
        "average_text_characters_by_suffix": dict(
            sorted(summary.average_text_characters_by_suffix.items())
        ),
        "table_counts_by_suffix": dict(sorted(summary.table_counts_by_suffix.items())),
        "average_provenance_coverage_by_suffix": dict(
            sorted(summary.average_provenance_coverage_by_suffix.items())
        ),
    }


def _review_fieldnames() -> list[str]:
    return [
        "sample_id",
        "relative_path",
        "suffix",
        "size_bytes",
        "profile",
        "status",
        "elapsed_seconds",
        "text_characters",
        "markdown_characters",
        "json_bytes",
        "page_count",
        "total_items",
        "table_count",
        "picture_count",
        "heading_count",
        "provenance_coverage",
        "text_preview",
        "markdown_preview",
        "text_quality",
        "structure_quality",
        "table_quality",
        "locator_quality",
        "rag_usability",
        "review_notes",
    ]


def _review_row(
    result: DoclingPocResult,
    text_preview: str,
    markdown_preview: str,
) -> dict[str, str]:
    return {
        "sample_id": result.sample_id,
        "relative_path": result.relative_path,
        "suffix": result.suffix,
        "size_bytes": str(result.size_bytes),
        "profile": result.profile,
        "status": result.status,
        "elapsed_seconds": f"{result.elapsed_seconds:.6f}",
        "text_characters": str(result.text_characters),
        "markdown_characters": str(result.markdown_characters),
        "json_bytes": str(result.json_bytes),
        "page_count": "" if result.page_count is None else str(result.page_count),
        "total_items": str(result.total_items),
        "table_count": str(result.table_count),
        "picture_count": str(result.picture_count),
        "heading_count": str(result.heading_count),
        "provenance_coverage": f"{result.provenance_coverage:.6f}",
        "text_preview": text_preview,
        "markdown_preview": markdown_preview,
        "text_quality": "",
        "structure_quality": "",
        "table_quality": "",
        "locator_quality": "",
        "rag_usability": "",
        "review_notes": "",
    }


def _artifact_preview_by_key(
    artifacts: tuple[ConvertedArtifact, ...],
    preview_chars: int,
) -> dict[tuple[str, str], tuple[str, str]]:
    return {
        (artifact.sample_id, artifact.profile): (
            _preview(artifact.text, preview_chars),
            _preview(artifact.markdown, preview_chars),
        )
        for artifact in artifacts
    }


def _build_report(run: DoclingPocRun) -> str:
    lines = [
        "# Docling形式別PoCレポート",
        "",
        "## 実行条件",
        "",
        f"- Docling: {run.manifest.docling_version}",
        f"- profiles: {', '.join(run.manifest.profiles)}",
        f"- formats: {', '.join(run.manifest.formats)}",
        f"- samples_per_format: {run.manifest.samples_per_format}",
        f"- timeout_seconds: {run.manifest.timeout_seconds}",
        f"- remote_services_enabled: {str(run.manifest.remote_services_enabled).lower()}",
        "",
        "## 全体結果",
        "",
        "| 形式 | 候補数 | 選択数 | 実行数 | 成功 | 部分成功 | 失敗 | "
        "平均処理時間 | 平均文字数 | 表数 | provenance coverage |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for suffix in run.manifest.formats:
        counts = run.summary.result_counts_by_suffix.get(suffix, {})
        executed = sum(count for status, count in counts.items() if status != "skipped")
        lines.append(
            "| "
            + " | ".join(
                [
                    suffix.upper().lstrip("."),
                    str(run.summary.candidate_counts_by_suffix.get(suffix, 0)),
                    str(run.summary.selected_counts_by_suffix.get(suffix, 0)),
                    str(executed),
                    str(counts.get("success", 0)),
                    str(counts.get("partial_success", 0)),
                    str(counts.get("failed", 0)),
                    f"{run.summary.average_elapsed_seconds_by_suffix.get(suffix, 0.0):.3f}",
                    f"{run.summary.average_text_characters_by_suffix.get(suffix, 0.0):.1f}",
                    str(run.summary.table_counts_by_suffix.get(suffix, 0)),
                    f"{run.summary.average_provenance_coverage_by_suffix.get(suffix, 0.0):.3f}",
                ]
            )
            + " |"
        )
    lines.extend(["", "## 形式別結果", ""])
    for suffix in run.manifest.formats:
        lines.extend([f"### {suffix.upper().lstrip('.')}", ""])
        counts = run.summary.result_counts_by_suffix.get(suffix, {})
        lines.append(
            f"- 成功: {counts.get('success', 0)}, 部分成功: {counts.get('partial_success', 0)}, "
            f"失敗: {counts.get('failed', 0)}, タイムアウト: {counts.get('timeout', 0)}"
        )
        lines.append("")
    lines.extend(["## サンプル別結果", ""])
    previews = _artifact_preview_by_key(run.artifacts, run.manifest.preview_chars)
    for result in run.results:
        text_preview, _markdown_preview = previews.get((result.sample_id, result.profile), ("", ""))
        lines.extend(
            [
                f"### {result.suffix.upper().lstrip('.')} / {result.profile} / {result.status}",
                "",
                f"- 相対パス: `{result.relative_path}`",
                f"- ファイルサイズ: {result.size_bytes}",
                f"- 処理時間: {result.elapsed_seconds:.3f}",
                f"- Markdown文字数: {result.markdown_characters}",
                f"- テキスト文字数: {result.text_characters}",
                f"- ページ数: {result.page_count if result.page_count is not None else '-'}",
                f"- 表数: {result.table_count}",
                f"- provenance coverage: {result.provenance_coverage:.3f}",
                f"- 成果物: `{result.output_directory or ''}`",
                f"- プレビュー: {_preview(text_preview, run.manifest.preview_chars)}",
                "",
            ]
        )
    lines.extend(["## エラー・警告", ""])
    error_results = [result for result in run.results if result.errors or result.warnings]
    if not error_results:
        lines.append("エラー・警告はありません。")
        lines.append("")
    for result in error_results:
        lines.append(f"- `{result.relative_path}` / {result.profile} / {result.status}")
        for error in result.errors:
            lines.append(f"  - error: {error}")
        for warning in result.warnings:
            lines.append(f"  - warning: {warning}")
    lines.extend(
        [
            "",
            "## 確認すべき論点",
            "",
            "- DOCX: 見出し・段落・表を確認してください",
            "- PPTX: スライド順・タイトル・表・ノートを確認してください",
            "- PDF: 読み順・表・ページ番号・OCRを確認してください",
            "- XLSX: シート名・セル番地・行列関係を確認してください",
            "- PNG: 日本語OCR・英数字・bboxを確認してください",
            "",
        ]
    )
    _append_ocr_environment_report(lines, run.manifest.ocr_environment)
    return "\n".join(lines)


def _append_ocr_environment_report(
    lines: list[str], ocr_environment: dict[str, Any] | None
) -> None:
    lines.extend(["", "## OCR環境", ""])
    if ocr_environment is None:
        lines.append("japanese_ocr profileは指定されていないため、OCR環境診断は実行していません。")
        return
    lines.extend(
        [
            f"- engine: {ocr_environment.get('engine', '')}",
            f"- diagnosis: {ocr_environment.get('diagnosis', '')}",
            f"- usable: {str(ocr_environment.get('usable', False)).lower()}",
        ]
    )
    if not ocr_environment.get("usable", False):
        lines.append("- japanese_ocr: ocr_environment_unavailableのためスキップ")


def _preview(text: str, preview_chars: int) -> str:
    if preview_chars == 0:
        return ""
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    normalized = " ".join(part.strip() for part in normalized.split("\n") if part.strip())
    if len(normalized) <= preview_chars:
        return normalized
    return normalized[:preview_chars] + "..."
