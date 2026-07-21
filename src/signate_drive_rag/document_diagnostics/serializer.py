"""文書診断結果をファイルへ保存する処理。"""

import json
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from signate_drive_rag.document_diagnostics.models import (
    DocumentDiagnosticManifest,
    DocumentDiagnosticReport,
    DocumentDiagnosticSummary,
    IgnoredFile,
    OcrEnvironmentDiagnostic,
    PdfDiagnosticResult,
    ocr_environment_to_json,
)


class DocumentDiagnosticOutputError(RuntimeError):
    """文書診断成果物の保存に失敗した場合の例外。"""


def save_document_diagnostic_report(
    report: DocumentDiagnosticReport,
    output_dir: Path,
    *,
    overwrite: bool,
) -> None:
    """診断成果物を一時ディレクトリへ作成してから最終ディレクトリへ置き換える。"""
    temporary_dir = output_dir.with_name(f"{output_dir.name}.tmp")
    backup_dir = output_dir.with_name(f"{output_dir.name}.bak")
    if output_dir.exists() and not overwrite:
        raise DocumentDiagnosticOutputError(f"出力先が既に存在します: {output_dir}")
    if temporary_dir.exists():
        shutil.rmtree(temporary_dir)
    if backup_dir.exists():
        shutil.rmtree(backup_dir)

    try:
        temporary_dir.mkdir(parents=True)
        _write_all_outputs(report, temporary_dir)
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


def _write_all_outputs(report: DocumentDiagnosticReport, output_dir: Path) -> None:
    _write_json(output_dir / "manifest.json", _manifest_to_record(report.manifest))
    _write_jsonl(
        output_dir / "pdf_results.jsonl",
        (_pdf_result_to_record(result) for result in report.pdf_results),
    )
    _write_json(
        output_dir / "ocr_environment.json",
        _ocr_environment_to_record(report.ocr_environment),
    )
    _write_jsonl(
        output_dir / "ignored.jsonl",
        (_ignored_file_to_record(ignored_file) for ignored_file in report.ignored_files),
    )
    _write_json(output_dir / "summary.json", _summary_to_record(report.summary))
    _write_text(output_dir / "report.md", _build_report(report))


def _write_json(path: Path, record: Any) -> None:
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as output_file:
        for record in records:
            output_file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _manifest_to_record(manifest: DocumentDiagnosticManifest) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "formats": list(manifest.formats),
        "sample_pages": manifest.sample_pages,
        "try_docling": manifest.try_docling,
        "diagnose_ocr": manifest.diagnose_ocr,
        "remote_services_enabled": manifest.remote_services_enabled,
        "dependencies": dict(sorted(manifest.dependencies.items())),
    }


def _pdf_result_to_record(result: PdfDiagnosticResult) -> dict[str, Any]:
    return {
        "relative_path": result.relative_path,
        "size_bytes": result.size_bytes,
        "sha256": result.sha256,
        "header_is_pdf": result.header_is_pdf,
        "eof_marker_found": result.eof_marker_found,
        "pypdf_readable": result.pypdf_readable,
        "encrypted": result.encrypted,
        "decryption_attempted": result.decryption_attempted,
        "decryption_succeeded": result.decryption_succeeded,
        "page_count": result.page_count,
        "pages_with_text": result.pages_with_text,
        "sampled_text_characters": result.sampled_text_characters,
        "metadata_available": result.metadata_available,
        "docling_attempted": result.docling_attempted,
        "docling_status": result.docling_status,
        "docling_error_type": result.docling_error_type,
        "docling_error_message": result.docling_error_message,
        "diagnosis": result.diagnosis,
        "warnings": list(result.warnings),
        "errors": list(result.errors),
    }


def _ocr_environment_to_record(diagnostic: OcrEnvironmentDiagnostic | None) -> Any:
    return ocr_environment_to_json(diagnostic)


def _ignored_file_to_record(ignored_file: IgnoredFile) -> dict[str, Any]:
    return {
        "relative_path": ignored_file.relative_path,
        "suffix": ignored_file.suffix,
        "size_bytes": ignored_file.size_bytes,
        "reason": ignored_file.reason,
    }


def _summary_to_record(summary: DocumentDiagnosticSummary) -> dict[str, Any]:
    return {
        "candidate_files": summary.candidate_files,
        "diagnosed_files": summary.diagnosed_files,
        "ignored_files": summary.ignored_files,
        "ignored_by_reason": dict(sorted(summary.ignored_by_reason.items())),
        "header_is_pdf": summary.header_is_pdf,
        "header_is_not_pdf": summary.header_is_not_pdf,
        "pypdf_readable": summary.pypdf_readable,
        "pypdf_unreadable": summary.pypdf_unreadable,
        "encrypted": summary.encrypted,
        "encrypted_unreadable": summary.encrypted_unreadable,
        "readable_text_pdf": summary.readable_text_pdf,
        "readable_image_or_empty_text_pdf": summary.readable_image_or_empty_text_pdf,
        "docling_attempted": summary.docling_attempted,
        "docling_success": summary.docling_success,
        "docling_partial_success": summary.docling_partial_success,
        "docling_failed": summary.docling_failed,
        "diagnosis_counts": dict(sorted(summary.diagnosis_counts.items())),
        "ocr_usable": summary.ocr_usable,
        "ocr_diagnosis": summary.ocr_diagnosis,
    }


def _build_report(report: DocumentDiagnosticReport) -> str:
    lines = [
        "# 文書入力・環境診断レポート",
        "",
        "## 実行条件",
        "",
        f"- formats: {', '.join(report.manifest.formats)}",
        f"- sample_pages: {report.manifest.sample_pages}",
        f"- try_docling: {str(report.manifest.try_docling).lower()}",
        f"- diagnose_ocr: {str(report.manifest.diagnose_ocr).lower()}",
        f"- remote_services_enabled: {str(report.manifest.remote_services_enabled).lower()}",
        f"- dependencies: {_format_dependencies(report.manifest.dependencies)}",
        "",
        "## Office一時ファイル",
        "",
        f"- 除外数: {report.summary.ignored_files}",
    ]
    for reason, count in report.summary.ignored_by_reason.items():
        lines.append(f"- {reason}: {count}")
    lines.extend(
        [
            "",
            "## PDF全体結果",
            "",
            f"- 診断対象PDF: {report.summary.candidate_files}",
            f"- 診断済みPDF: {report.summary.diagnosed_files}",
            f"- PDFヘッダーあり: {report.summary.header_is_pdf}",
            f"- pypdf読取可能: {report.summary.pypdf_readable}",
            f"- 暗号化PDF: {report.summary.encrypted}",
            f"- Docling試行: {report.summary.docling_attempted}",
            "",
            "## PDF診断分類",
            "",
        ]
    )
    if report.summary.diagnosis_counts:
        for diagnosis, count in report.summary.diagnosis_counts.items():
            lines.append(f"- {diagnosis}: {count}")
    else:
        lines.append("- 対象PDFなし: 0")
    lines.extend(["", "## PDF別結果", ""])
    if report.pdf_results:
        lines.append(
            "| relative_path | diagnosis | pages | text_chars | pypdf | docling | errors |"
        )
        lines.append("|---|---|---:|---:|---|---|---:|")
        for result in report.pdf_results:
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{result.relative_path}`",
                        result.diagnosis,
                        "" if result.page_count is None else str(result.page_count),
                        str(result.sampled_text_characters),
                        str(result.pypdf_readable).lower(),
                        result.docling_status or "",
                        str(len(result.errors)),
                    ]
                )
                + " |"
            )
    else:
        lines.append("診断対象PDFはありません。")
    lines.extend(
        [
            "",
            "## Doclingとの比較",
            "",
            f"- Docling成功: {report.summary.docling_success}",
            f"- Docling部分成功: {report.summary.docling_partial_success}",
            f"- Docling失敗: {report.summary.docling_failed}",
            "- pypdf可読かつDocling失敗: "
            f"{_count_pypdf_readable_docling_failed(report.pdf_results)}",
            "",
            "## OCR環境",
            "",
        ]
    )
    _append_ocr_environment(lines, report.ocr_environment)
    lines.extend(
        [
            "",
            "## 推奨される次の対応",
            "",
            "- not_pdfやpdf_header_onlyは、拡張子と実体の不一致またはファイル破損を個別確認する。",
            "- pypdf_unreadableは、PDF構造破損や暗号化の有無を切り分ける。",
            "- readable_image_or_empty_text_pdfは、OCR適用候補として扱う。",
            "- ocr_environment_unavailableの場合は、japanese_ocrの再実行前に"
            "Tesseractと言語データを確認する。",
            "",
        ]
    )
    return "\n".join(lines)


def _append_ocr_environment(
    lines: list[str],
    ocr_environment: OcrEnvironmentDiagnostic | None,
) -> None:
    if ocr_environment is None:
        lines.append("OCR環境診断は実行していません。")
        return
    lines.extend(
        [
            f"- engine: {ocr_environment.engine}",
            f"- diagnosis: {ocr_environment.diagnosis}",
            f"- usable: {str(ocr_environment.usable).lower()}",
            f"- executable_found: {str(ocr_environment.executable_found).lower()}",
            f"- version: {ocr_environment.version or ''}",
            f"- required_languages: {', '.join(ocr_environment.required_languages)}",
            f"- missing_languages: {', '.join(ocr_environment.missing_languages)}",
        ]
    )


def _count_pypdf_readable_docling_failed(pdf_results: tuple[PdfDiagnosticResult, ...]) -> int:
    return sum(
        1 for result in pdf_results if result.pypdf_readable and result.docling_status == "failed"
    )


def _format_dependencies(dependencies: dict[str, str]) -> str:
    return ", ".join(
        f"{dependency_name}={version}" for dependency_name, version in sorted(dependencies.items())
    )
