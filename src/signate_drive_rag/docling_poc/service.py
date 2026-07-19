"""Docling形式別PoCの一括実行サービス。"""

import logging
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from importlib import metadata
from pathlib import Path

from signate_drive_rag.docling_poc.analyzer import analyze_document_structure, json_byte_length
from signate_drive_rag.docling_poc.models import (
    DEFAULT_DOCLING_PROFILES,
    JAPANESE_OCR_SUFFIXES,
    SUPPORTED_DOCLING_PROFILES,
    SUPPORTED_DOCLING_SUFFIXES,
    ConversionOutput,
    ConvertedArtifact,
    DoclingPocManifest,
    DoclingPocResult,
    DoclingPocRun,
    DoclingPocSummary,
    DocumentConversionAdapter,
    SelectedDocument,
)
from signate_drive_rag.docling_poc.selector import (
    group_candidates_by_suffix,
    select_representative_documents,
)
from signate_drive_rag.document_diagnostics.models import (
    OcrEnvironmentDiagnostic,
    ocr_environment_to_json,
)
from signate_drive_rag.document_diagnostics.ocr_diagnostic import diagnose_tesseract_environment
from signate_drive_rag.domain import SourceFile
from signate_drive_rag.ingestion import discover_files

LOGGER = logging.getLogger(__name__)
DOCLING_STATUS_VALUES = ("success", "partial_success", "failed", "timeout", "skipped")


class DoclingPocInputError(ValueError):
    """Docling PoCの入力値が不正な場合の例外。"""


class DoclingPocService:
    """未対応形式へDoclingを適用してPoC成果物を作成する。"""

    def __init__(
        self,
        conversion_adapter: DocumentConversionAdapter,
        *,
        ocr_environment: OcrEnvironmentDiagnostic | None = None,
    ) -> None:
        """テストで偽アダプターを差し替えられるようにする。"""
        self._conversion_adapter = conversion_adapter
        self._ocr_environment = ocr_environment

    def run_from_root(
        self,
        source_root: Path,
        *,
        formats: frozenset[str],
        samples_per_format: int,
        profiles: tuple[str, ...],
        timeout_seconds: int,
        preview_chars: int,
    ) -> DoclingPocRun:
        """共有ドライブルートを探索してPoCを実行する。"""
        source_files = discover_files(source_root)
        return self.run(
            source_files,
            source_root_name=source_root.resolve().name,
            formats=formats,
            samples_per_format=samples_per_format,
            profiles=profiles,
            timeout_seconds=timeout_seconds,
            preview_chars=preview_chars,
        )

    def run(
        self,
        source_files: Sequence[SourceFile],
        *,
        source_root_name: str,
        formats: frozenset[str],
        samples_per_format: int,
        profiles: tuple[str, ...],
        timeout_seconds: int,
        preview_chars: int,
    ) -> DoclingPocRun:
        """探索済みファイルから代表サンプルを変換する。"""
        validate_docling_poc_options(
            formats=formats,
            samples_per_format=samples_per_format,
            profiles=profiles,
            timeout_seconds=timeout_seconds,
            preview_chars=preview_chars,
        )
        candidates_by_suffix = group_candidates_by_suffix(source_files, formats)
        selections = select_representative_documents(
            source_files,
            samples_per_format=samples_per_format,
            formats=formats,
        )
        source_by_relative_path = {
            source_file.relative_path.as_posix(): source_file for source_file in source_files
        }
        ocr_environment = self._diagnose_ocr_if_needed(profiles)
        results: list[DoclingPocResult] = []
        artifacts: list[ConvertedArtifact] = []

        for selection in selections:
            source_file = source_by_relative_path[selection.relative_path]
            for profile in profiles:
                if not _is_profile_applicable(selection.suffix, profile):
                    continue
                if (
                    profile == "japanese_ocr"
                    and ocr_environment is not None
                    and not ocr_environment.usable
                ):
                    results.append(_skipped_ocr_result(selection, profile))
                    continue
                result, artifact = self._convert_one(
                    source_file,
                    selection,
                    profile=profile,
                    timeout_seconds=timeout_seconds,
                )
                results.append(result)
                if artifact is not None:
                    artifacts.append(artifact)

        summary = _build_summary(candidates_by_suffix, selections, results, formats)
        manifest = DoclingPocManifest(
            source_root_name=source_root_name,
            docling_version=metadata.version("docling"),
            profiles=profiles,
            formats=tuple(sorted(formats)),
            samples_per_format=samples_per_format,
            selection_strategy="size_quantile",
            timeout_seconds=timeout_seconds,
            preview_chars=preview_chars,
            remote_services_enabled=False,
            ocr_settings_by_profile={
                "default_local": {
                    "engine": "docling_default",
                    "languages": [],
                    "force_full_page_ocr": False,
                },
                "japanese_ocr": {
                    "engine": "tesseract_cli",
                    "languages": ["jpn", "eng"],
                    "force_full_page_ocr": True,
                },
            },
            ocr_environment=ocr_environment_to_json(ocr_environment),
        )
        return DoclingPocRun(
            manifest=manifest,
            selections=tuple(selections),
            results=tuple(sorted(results, key=_result_sort_key)),
            artifacts=tuple(
                sorted(artifacts, key=lambda artifact: (artifact.sample_id, artifact.profile))
            ),
            summary=summary,
        )

    def _convert_one(
        self,
        source_file: SourceFile,
        selection: SelectedDocument,
        *,
        profile: str,
        timeout_seconds: int,
    ) -> tuple[DoclingPocResult, ConvertedArtifact | None]:
        started_at = time.perf_counter()
        LOGGER.info(
            "docling_poc_conversion_started",
            extra={
                "suffix": selection.suffix,
                "relative_path": selection.relative_path,
                "profile": profile,
            },
        )
        try:
            conversion_output = self._conversion_adapter.convert(
                source_file.path,
                profile=profile,
                timeout_seconds=timeout_seconds,
            )
        except TimeoutError as error:
            conversion_output = _failed_output("timeout", error)
        except Exception as error:
            # PoCでは形式別の失敗傾向を比較するため、1件の失敗で全体を止めない。
            conversion_output = _failed_output("failed", error)

        elapsed_seconds = time.perf_counter() - started_at
        structure = analyze_document_structure(conversion_output.document)
        output_directory = None
        artifact = None
        if conversion_output.status in {"success", "partial_success"}:
            output_directory = f"converted/{selection.sample_id}/{profile}"
            artifact = ConvertedArtifact(
                sample_id=selection.sample_id,
                profile=profile,
                markdown=conversion_output.markdown,
                text=conversion_output.text,
                json_document=conversion_output.json_document,
            )
        result = DoclingPocResult(
            sample_id=selection.sample_id,
            relative_path=selection.relative_path,
            suffix=selection.suffix,
            size_bytes=selection.size_bytes,
            profile=profile,
            status=conversion_output.status,
            elapsed_seconds=elapsed_seconds,
            markdown_characters=len(conversion_output.markdown),
            text_characters=len(conversion_output.text),
            json_bytes=json_byte_length(conversion_output.json_document),
            page_count=structure.page_count,
            total_items=structure.total_items,
            table_count=structure.table_count,
            picture_count=structure.picture_count,
            heading_count=structure.heading_count,
            provenance_items=structure.provenance_items,
            provenance_coverage=structure.provenance_coverage,
            item_counts_by_label=structure.item_counts_by_label,
            output_directory=output_directory,
            warnings=conversion_output.warnings,
            errors=conversion_output.errors,
        )
        LOGGER.info(
            "docling_poc_conversion_finished",
            extra={
                "suffix": selection.suffix,
                "relative_path": selection.relative_path,
                "profile": profile,
                "status": result.status,
                "elapsed_seconds": result.elapsed_seconds,
                "error_type": _first_error_type(result.errors),
            },
        )
        return result, artifact

    def _diagnose_ocr_if_needed(
        self,
        profiles: tuple[str, ...],
    ) -> OcrEnvironmentDiagnostic | None:
        if "japanese_ocr" not in profiles:
            return None
        if self._ocr_environment is not None:
            return self._ocr_environment
        return diagnose_tesseract_environment()


def validate_docling_poc_options(
    *,
    formats: frozenset[str],
    samples_per_format: int,
    profiles: tuple[str, ...],
    timeout_seconds: int,
    preview_chars: int,
) -> None:
    """Docling PoCの入力値を検証する。"""
    unknown_formats = formats - SUPPORTED_DOCLING_SUFFIXES
    if unknown_formats:
        raise DoclingPocInputError(f"未知の形式です: {', '.join(sorted(unknown_formats))}")
    unknown_profiles = set(profiles) - SUPPORTED_DOCLING_PROFILES
    if unknown_profiles:
        raise DoclingPocInputError(f"未知のprofileです: {', '.join(sorted(unknown_profiles))}")
    if samples_per_format <= 0:
        raise DoclingPocInputError("samples_per_formatは1以上である必要があります。")
    if timeout_seconds <= 0:
        raise DoclingPocInputError("timeout_secondsは1以上である必要があります。")
    if preview_chars < 0:
        raise DoclingPocInputError("preview_charsは0以上である必要があります。")


def parse_formats(value: str) -> frozenset[str]:
    """CLIのカンマ区切り形式指定を拡張子集合へ変換する。"""
    suffixes = frozenset(_normalize_suffix(part) for part in value.split(",") if part.strip())
    if not suffixes:
        raise DoclingPocInputError("formatsを1件以上指定してください。")
    return suffixes


def parse_profiles(value: str) -> tuple[str, ...]:
    """CLIのカンマ区切りprofile指定をtupleへ変換する。"""
    profiles = tuple(part.strip() for part in value.split(",") if part.strip())
    if not profiles:
        raise DoclingPocInputError("profilesを1件以上指定してください。")
    return profiles


def default_docling_profiles() -> tuple[str, ...]:
    """標準profileを返す。"""
    return DEFAULT_DOCLING_PROFILES


def _normalize_suffix(value: str) -> str:
    suffix = value.strip().lower()
    if not suffix:
        raise DoclingPocInputError("空の形式は指定できません。")
    return suffix if suffix.startswith(".") else f".{suffix}"


def _is_profile_applicable(suffix: str, profile: str) -> bool:
    if profile == "default_local":
        return True
    if profile == "japanese_ocr":
        return suffix in JAPANESE_OCR_SUFFIXES
    return False


def _failed_output(status: str, error: Exception) -> ConversionOutput:
    message = str(error)
    if len(message) > 500:
        message = message[:500] + "..."
    return ConversionOutput(
        status=status,
        markdown="",
        text="",
        json_document={},
        document=None,
        warnings=(),
        errors=(f"{type(error).__name__}: {message}",),
    )


def _skipped_ocr_result(selection: SelectedDocument, profile: str) -> DoclingPocResult:
    return DoclingPocResult(
        sample_id=selection.sample_id,
        relative_path=selection.relative_path,
        suffix=selection.suffix,
        size_bytes=selection.size_bytes,
        profile=profile,
        status="skipped",
        elapsed_seconds=0.0,
        markdown_characters=0,
        text_characters=0,
        json_bytes=2,
        page_count=None,
        total_items=0,
        table_count=0,
        picture_count=0,
        heading_count=0,
        provenance_items=0,
        provenance_coverage=0.0,
        item_counts_by_label={},
        output_directory=None,
        warnings=("ocr_environment_unavailable",),
        errors=(),
    )


def _build_summary(
    candidates_by_suffix: dict[str, tuple[SourceFile, ...]],
    selections: Sequence[SelectedDocument],
    results: Sequence[DoclingPocResult],
    formats: frozenset[str],
) -> DoclingPocSummary:
    candidate_counts = {
        suffix: len(candidates_by_suffix.get(suffix, ())) for suffix in sorted(formats)
    }
    selected_counter = Counter(selection.suffix for selection in selections)
    selected_counts = {suffix: selected_counter[suffix] for suffix in sorted(formats)}
    status_counts = {status: 0 for status in DOCLING_STATUS_VALUES}
    status_counts.update(Counter(result.status for result in results))
    result_counts_by_suffix: dict[str, dict[str, int]] = {}
    for suffix in sorted({*candidate_counts, *(result.suffix for result in results)}):
        counts = Counter(result.status for result in results if result.suffix == suffix)
        result_counts_by_suffix[suffix] = {
            status: counts[status] for status in DOCLING_STATUS_VALUES
        }

    return DoclingPocSummary(
        candidate_counts_by_suffix=candidate_counts,
        selected_counts_by_suffix=selected_counts,
        executed_conversions=sum(1 for result in results if result.status != "skipped"),
        status_counts=dict(sorted(status_counts.items())),
        result_counts_by_suffix=result_counts_by_suffix,
        average_elapsed_seconds_by_suffix=_average_by_suffix(results, "elapsed_seconds"),
        average_text_characters_by_suffix=_average_by_suffix(results, "text_characters"),
        table_counts_by_suffix=dict(
            sorted(
                (
                    suffix,
                    sum(result.table_count for result in results if result.suffix == suffix),
                )
                for suffix in {result.suffix for result in results}
            )
        ),
        average_provenance_coverage_by_suffix=_average_by_suffix(results, "provenance_coverage"),
    )


def _average_by_suffix(
    results: Sequence[DoclingPocResult], attribute_name: str
) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for result in results:
        value = getattr(result, attribute_name)
        if isinstance(value, int | float):
            grouped[result.suffix].append(float(value))
    return {
        suffix: sum(values) / len(values) if values else 0.0
        for suffix, values in sorted(grouped.items())
    }


def _first_error_type(errors: tuple[str, ...]) -> str:
    if not errors:
        return ""
    return errors[0].split(":", maxsplit=1)[0]


def _result_sort_key(result: DoclingPocResult) -> tuple[str, str, str]:
    return (result.suffix, result.relative_path, result.profile)
