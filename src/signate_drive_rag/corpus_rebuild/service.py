"""全文書コーパス再構築を既存サービスで実行するオーケストレーター。"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import shutil
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from signate_drive_rag.audit import AuditService, load_audit_documents, save_audit_result
from signate_drive_rag.baseline_comparison import (
    BaselineComparisonService,
    save_baseline_comparison_result,
)
from signate_drive_rag.chunk_validation import (
    VALIDATION_RULESET_VERSION,
    ChunkValidationResult,
    ChunkValidationService,
    save_chunk_validation_result,
)
from signate_drive_rag.chunking import (
    ChunkingService,
    load_chunk_source_documents,
    save_chunking_result,
)
from signate_drive_rag.corpus_rebuild.models import (
    RebuildCorpusOptions,
    RebuildCorpusResult,
    StageStatus,
)
from signate_drive_rag.document_diagnostics.models import IgnoredFile
from signate_drive_rag.domain import SourceFile
from signate_drive_rag.extraction import ExtractionService, save_extraction_result
from signate_drive_rag.ingestion import discover_files_with_ignored
from signate_drive_rag.ingestion.parser_registry import (
    ParserNotFoundError,
    ParserRegistry,
    create_default_parser_registry,
)
from signate_drive_rag.ocr.device import is_torch_cuda_available, resolve_ocr_gpu_flag
from signate_drive_rag.ocr.models import OcrOptions
from signate_drive_rag.retrieval import (
    Bm25Retriever,
    build_bm25_index,
    calculate_file_sha256,
    load_bm25_index,
    load_retrieval_chunks,
    save_bm25_index,
)
from signate_drive_rag.search_evaluation import (
    SearchEvaluationService,
    calculate_query_file_sha256,
    load_search_evaluation_queries,
    save_search_evaluation_result,
)

STAGE_NAMES = (
    "scan",
    "extract",
    "audit",
    "chunk",
    "validate_chunks",
    "build_bm25",
    "evaluate_search",
    "compare_baseline",
)


class RebuildCorpusError(RuntimeError):
    """全文書コーパス再構築に失敗した場合の例外。"""


@dataclass(frozen=True, slots=True)
class _StageOutput:
    summary_path: Path | None
    output_fingerprint: str


class RebuildCorpusService:
    """全共有ドライブ向けコーパスを一括で再構築する。"""

    def rebuild(self, options: RebuildCorpusOptions) -> RebuildCorpusResult:
        """指定設定で全文書コーパス再構築を実行する。"""
        _validate_options(options)
        if options.output_dir.exists() and any(options.output_dir.iterdir()):
            if not options.overwrite and not options.resume:
                raise RebuildCorpusError(f"出力先が既に存在します: {options.output_dir}")
            if options.overwrite:
                shutil.rmtree(options.output_dir)
        options.output_dir.mkdir(parents=True, exist_ok=True)

        resolved_gpu = _resolve_ocr_gpu(options)
        ocr_options = (
            OcrOptions(
                languages=options.ocr_languages,
                gpu=resolved_gpu,
                model_dir=options.ocr_model_dir,
            )
            if options.enable_ocr
            else None
        )
        parser_registry = (
            create_default_parser_registry(ocr_options=ocr_options)
            if ocr_options is not None
            else create_default_parser_registry()
        )

        existing_stages = _load_stage_statuses(options.output_dir / "stage_status.json")
        stages: list[StageStatus] = []
        context = _PipelineContext(
            options=options,
            parser_registry=parser_registry,
            resolved_gpu=resolved_gpu,
        )
        _write_manifest(options, context, stages)

        stage_specs: tuple[tuple[str, Callable[[Path], _StageOutput]], ...] = (
            ("scan", lambda stage_dir: self._run_scan(stage_dir, context)),
            ("extract", lambda stage_dir: self._run_extract(stage_dir, context)),
            ("audit", lambda stage_dir: self._run_audit(stage_dir, context)),
            ("chunk", lambda stage_dir: self._run_chunk(stage_dir, context)),
            (
                "validate_chunks",
                lambda stage_dir: self._run_validate_chunks(stage_dir, context),
            ),
            ("build_bm25", lambda stage_dir: self._run_build_bm25(stage_dir, context)),
            (
                "evaluate_search",
                lambda stage_dir: self._run_evaluate_search(stage_dir, context),
            ),
            (
                "compare_baseline",
                lambda stage_dir: self._run_compare_baseline(stage_dir, context),
            ),
        )

        for stage_name, handler in stage_specs:
            try:
                stage_status = self._run_stage(
                    stage_name,
                    options,
                    context,
                    existing_stages,
                    handler,
                )
            except Exception as error:
                failed_stage = _failed_stage_status(stage_name, context, error)
                stages.append(failed_stage)
                _write_stage_statuses(options.output_dir / "stage_status.json", stages)
                _write_manifest(options, context, stages)
                _write_report(options, context, stages)
                raise
            stages.append(stage_status)
            _write_stage_statuses(options.output_dir / "stage_status.json", stages)
            _write_manifest(options, context, stages)
            if stage_name == "validate_chunks" and options.strict:
                try:
                    _enforce_quality_gate(context)
                except Exception as error:
                    failed_stage = _failed_stage_status("quality_gate", context, error)
                    stages.append(failed_stage)
                    _write_stage_statuses(options.output_dir / "stage_status.json", stages)
                    _write_manifest(options, context, stages)
                    _write_report(options, context, stages)
                    raise

        _write_report(options, context, stages)
        return RebuildCorpusResult(
            output_dir=options.output_dir,
            manifest_path=options.output_dir / "manifest.json",
            stage_status_path=options.output_dir / "stage_status.json",
            report_path=options.output_dir / "report.md",
            stages=tuple(stages),
        )

    def _run_stage(
        self,
        stage_name: str,
        options: RebuildCorpusOptions,
        context: _PipelineContext,
        existing_stages: dict[str, StageStatus],
        handler: Callable[[Path], _StageOutput],
    ) -> StageStatus:
        input_fingerprint = context.input_fingerprint(stage_name)
        settings_fingerprint = context.settings_fingerprint(stage_name)
        existing = existing_stages.get(stage_name)
        final_dir = options.output_dir / _stage_dir_name(stage_name)
        if options.resume and existing is not None and final_dir.exists():
            if (
                existing.status == "success"
                and existing.input_fingerprint == input_fingerprint
                and existing.settings_fingerprint == settings_fingerprint
            ):
                context.reuse_stage(stage_name, existing.output_fingerprint)
                return _reused_stage_status(existing)
            raise RebuildCorpusError(f"resume_fingerprint_mismatch: {stage_name}")
        if _is_optional_skipped_stage(stage_name, options):
            return _skipped_stage_status(
                stage_name,
                input_fingerprint,
                settings_fingerprint,
            )

        temporary_dir = options.output_dir / f"{_stage_dir_name(stage_name)}.tmp"
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        temporary_dir.mkdir(parents=True)
        started = _now_iso()
        start_time = time.perf_counter()
        try:
            stage_output = handler(temporary_dir)
            if final_dir.exists():
                shutil.rmtree(final_dir)
            temporary_dir.replace(final_dir)
        except Exception:
            if temporary_dir.exists():
                shutil.rmtree(temporary_dir)
            raise

        summary_path = (
            None
            if stage_output.summary_path is None
            else final_dir / stage_output.summary_path.relative_to(temporary_dir)
        )
        context.complete_stage(stage_name, stage_output.output_fingerprint)
        if stage_name == "scan":
            _write_source_snapshot_root(options, final_dir / "source_snapshot.jsonl")
        completed = _now_iso()
        return StageStatus(
            name=stage_name,
            status="success",
            started=started,
            completed=completed,
            elapsed_seconds=round(time.perf_counter() - start_time, 6),
            input_fingerprint=input_fingerprint,
            output_fingerprint=stage_output.output_fingerprint,
            settings_fingerprint=settings_fingerprint,
            summary_path=_relative_artifact_path(options.output_dir, summary_path),
        )

    def _run_scan(self, stage_dir: Path, context: _PipelineContext) -> _StageOutput:
        discovery_result = discover_files_with_ignored(context.options.source)
        context.source_files = tuple(discovery_result.source_files)
        context.ignored_files = tuple(discovery_result.ignored_files)
        file_records = []
        snapshot_records = []
        unsupported_files = 0
        files_by_parser: Counter[str] = Counter()
        for source_file in context.source_files:
            parser_name = _parser_name(context, source_file)
            if parser_name is None:
                unsupported_files += 1
            else:
                files_by_parser[parser_name] += 1
            file_records.append(_source_file_record(source_file, parser_name))
            snapshot_records.append(
                _snapshot_record(context.options.source, source_file, parser_name)
            )

        ignored_records = [
            {
                "relative_path": ignored.relative_path,
                "suffix": ignored.suffix,
                "size_bytes": ignored.size_bytes,
                "reason": ignored.reason,
            }
            for ignored in context.ignored_files
        ]
        for ignored in context.ignored_files:
            snapshot_records.append(
                {
                    "relative_path": ignored.relative_path,
                    "suffix": ignored.suffix,
                    "size_bytes": ignored.size_bytes,
                    "sha256": _file_sha256(context.options.source / ignored.relative_path),
                    "parser_name": None,
                    "ignored": True,
                    "ignored_reason": ignored.reason,
                }
            )

        snapshot_records = sorted(snapshot_records, key=lambda item: str(item["relative_path"]))
        _write_jsonl_atomic(stage_dir / "files.jsonl", file_records)
        _write_jsonl_atomic(stage_dir / "ignored.jsonl", ignored_records)
        _write_jsonl_atomic(stage_dir / "source_snapshot.jsonl", snapshot_records)
        context.source_snapshot_sha256 = _file_sha256(stage_dir / "source_snapshot.jsonl")
        summary = {
            "discovered_files": len(context.source_files) + len(context.ignored_files),
            "ignored_files": len(context.ignored_files),
            "processable_files": len(context.source_files),
            "unsupported_files": unsupported_files,
            "files_by_suffix": dict(
                sorted(Counter(file.suffix for file in context.source_files).items())
            ),
            "files_by_parser": dict(sorted(files_by_parser.items())),
            "ignored_by_reason": dict(sorted(discovery_result.ignored_by_reason.items())),
        }
        _write_json_atomic(stage_dir / "summary.json", summary)
        return _StageOutput(
            summary_path=stage_dir / "summary.json",
            output_fingerprint=_hash_json(summary),
        )

    def _run_extract(self, stage_dir: Path, context: _PipelineContext) -> _StageOutput:
        result = ExtractionService(context.parser_registry).extract(context.source_files)
        context.extraction_failed_files = result.summary.failed_files
        save_extraction_result(result, stage_dir)
        shutil.copyfile(stage_dir / "failures.jsonl", stage_dir / "errors.jsonl")
        _write_json_atomic(
            stage_dir / "manifest.json",
            {
                "schema_version": 1,
                "source_snapshot_sha256": context.source_snapshot_sha256,
                "resolved_ocr_device": context.resolved_ocr_device,
            },
        )
        summary = _read_json(stage_dir / "summary.json")
        return _StageOutput(
            summary_path=stage_dir / "summary.json",
            output_fingerprint=_hash_json(summary),
        )

    def _run_audit(self, stage_dir: Path, context: _PipelineContext) -> _StageOutput:
        audit_documents = load_audit_documents(context.extraction_dir / "documents.jsonl")
        audit_result = AuditService().audit(audit_documents)
        save_audit_result(audit_result, stage_dir)
        summary = _read_json(stage_dir / "summary.json")
        return _StageOutput(stage_dir / "summary.json", _hash_json(summary))

    def _run_chunk(self, stage_dir: Path, context: _PipelineContext) -> _StageOutput:
        source_documents = load_chunk_source_documents(context.extraction_dir / "documents.jsonl")
        chunking_result = ChunkingService(
            max_chars=context.options.max_chars,
            overlap_chars=context.options.overlap_chars,
            table_max_rows=context.options.table_max_rows,
        ).chunk(source_documents)
        save_chunking_result(chunking_result, stage_dir)
        _write_json_atomic(
            stage_dir / "manifest.json",
            {
                "schema_version": 1,
                "documents_sha256": _file_sha256(context.extraction_dir / "documents.jsonl"),
                "max_chars": context.options.max_chars,
                "overlap_chars": context.options.overlap_chars,
                "table_max_rows": context.options.table_max_rows,
            },
        )
        summary = _read_json(stage_dir / "summary.json")
        return _StageOutput(stage_dir / "summary.json", _hash_json(summary))

    def _run_validate_chunks(
        self,
        stage_dir: Path,
        context: _PipelineContext,
    ) -> _StageOutput:
        source_documents = load_chunk_source_documents(context.extraction_dir / "documents.jsonl")
        chunks = load_retrieval_chunks(context.chunks_dir / "chunks.jsonl")
        validation_result = ChunkValidationService(max_chars=context.options.max_chars).validate(
            chunks=chunks,
            source_documents=source_documents,
        )
        context.validation_result = validation_result
        context.validation_errors = validation_result.summary.errors
        context.duplicate_chunk_ids = validation_result.summary.duplicate_chunk_ids
        context.empty_text_chunks = validation_result.summary.empty_text_chunks
        context.invalid_chunk_references = (
            validation_result.summary.invalid_document_references
            + validation_result.summary.invalid_unit_references
        )
        save_chunk_validation_result(validation_result, stage_dir)
        summary = _read_json(stage_dir / "summary.json")
        return _StageOutput(stage_dir / "summary.json", _hash_json(summary))

    def _run_build_bm25(self, stage_dir: Path, context: _PipelineContext) -> _StageOutput:
        chunks_path = context.chunks_dir / "chunks.jsonl"
        chunks = load_retrieval_chunks(chunks_path)
        source_sha256 = calculate_file_sha256(chunks_path)
        index = build_bm25_index(chunks, source_sha256=source_sha256)
        save_bm25_index(index, stage_dir / "bm25", overwrite=False)
        manifest_path = stage_dir / "bm25" / "manifest.json"
        manifest = _read_json(manifest_path)
        manifest.update(
            {
                "source_chunks_sha256": source_sha256,
                "chunk_count": len(chunks),
                "indexed_chunk_count": len(index.records),
                "bm25_settings": manifest.get("bm25", {}),
            }
        )
        _write_json_atomic(manifest_path, manifest)
        return _StageOutput(
            summary_path=manifest_path,
            output_fingerprint=_hash_json(manifest),
        )

    def _run_evaluate_search(self, stage_dir: Path, context: _PipelineContext) -> _StageOutput:
        if context.options.queries is None:
            raise RebuildCorpusError("queries未指定の工程が実行されました。")
        queries = load_search_evaluation_queries(context.options.queries)
        query_file_sha256 = calculate_query_file_sha256(context.options.queries)
        loaded_index = load_bm25_index(context.index_dir)
        retriever = Bm25Retriever(
            loaded_index,
            candidate_multiplier=context.options.candidate_multiplier,
            rrf_k=context.options.rrf_k,
        )
        result = SearchEvaluationService(retriever).evaluate(
            queries,
            top_k=context.options.top_k,
            index_source_sha256=_string_value(loaded_index.manifest, "source_sha256"),
            query_file_sha256=query_file_sha256,
            candidate_multiplier=context.options.candidate_multiplier,
            rrf_k=context.options.rrf_k,
            preview_chars=context.options.preview_chars,
            report_results_per_query=context.options.report_results_per_query,
        )
        save_search_evaluation_result(result, stage_dir)
        summary = _read_json(stage_dir / "summary.json")
        return _StageOutput(stage_dir / "summary.json", _hash_json(summary))

    def _run_compare_baseline(
        self,
        stage_dir: Path,
        context: _PipelineContext,
    ) -> _StageOutput:
        if context.options.baseline_dir is None:
            raise RebuildCorpusError("baseline未指定の工程が実行されました。")
        result = BaselineComparisonService().compare(
            baseline_dir=context.options.baseline_dir,
            current_dir=context.evaluation_dir,
        )
        save_baseline_comparison_result(result, stage_dir)
        summary = _read_json(stage_dir / "summary.json")
        return _StageOutput(stage_dir / "summary.json", _hash_json(summary))


@dataclass(slots=True)
class _PipelineContext:
    options: RebuildCorpusOptions
    parser_registry: ParserRegistry
    resolved_gpu: bool
    source_files: tuple[SourceFile, ...] = ()
    ignored_files: tuple[IgnoredFile, ...] = ()
    source_snapshot_sha256: str = ""
    extraction_failed_files: int = 0
    validation_result: ChunkValidationResult | None = None
    validation_errors: int = 0
    duplicate_chunk_ids: int = 0
    empty_text_chunks: int = 0
    invalid_chunk_references: int = 0

    @property
    def resolved_ocr_device(self) -> str:
        if not self.options.enable_ocr:
            return "disabled"
        return "cuda" if self.resolved_gpu else "cpu"

    @property
    def extraction_dir(self) -> Path:
        return self.options.output_dir / "extraction"

    @property
    def chunks_dir(self) -> Path:
        return self.options.output_dir / "chunks"

    @property
    def index_dir(self) -> Path:
        return self.options.output_dir / "indexes" / "bm25"

    @property
    def evaluation_dir(self) -> Path:
        return self.options.output_dir / "evaluation"

    def input_fingerprint(self, stage_name: str) -> str:
        dependencies = {
            "scan": _source_input_fingerprint(self.options.source),
            "extract": self.source_snapshot_sha256,
            "audit": _safe_file_hash(self.extraction_dir / "documents.jsonl"),
            "chunk": _safe_file_hash(self.extraction_dir / "documents.jsonl"),
            "validate_chunks": _safe_file_hash(self.chunks_dir / "chunks.jsonl"),
            "quality_gate": _safe_file_hash(
                self.options.output_dir / "validation" / "summary.json"
            ),
            "build_bm25": _safe_file_hash(self.chunks_dir / "chunks.jsonl"),
            "evaluate_search": _hash_json(
                {
                    "index": _safe_file_hash(self.index_dir / "manifest.json"),
                    "queries": _safe_file_hash(self.options.queries),
                }
            ),
            "compare_baseline": _hash_json(
                {
                    "current": _safe_file_hash(self.evaluation_dir / "query_results.jsonl"),
                    "baseline": _safe_file_hash(
                        None
                        if self.options.baseline_dir is None
                        else self.options.baseline_dir / "query_results.jsonl"
                    ),
                }
            ),
        }
        return dependencies[stage_name]

    def settings_fingerprint(self, stage_name: str) -> str:
        shared = {
            "dependencies": _dependency_versions(),
            "ocr": _ocr_manifest_record(self.options, self),
        }
        stage_settings: dict[str, Any] = {
            "scan": {},
            "extract": {"parsers": sorted(self.parser_registry.parsers.keys())},
            "audit": {},
            "chunk": _chunk_settings(self.options),
            "validate_chunks": {
                "max_chars": self.options.max_chars,
                "ruleset_version": VALIDATION_RULESET_VERSION,
            },
            "quality_gate": {"strict": self.options.strict},
            "build_bm25": {"ngram_min": 2, "ngram_max": 3},
            "evaluate_search": _bm25_settings(self.options),
            "compare_baseline": {},
        }
        return _hash_json(
            {"stage": stage_name, "shared": shared, "settings": stage_settings[stage_name]}
        )

    def complete_stage(self, stage_name: str, output_fingerprint: str) -> None:
        if stage_name == "scan":
            source_snapshot = self.options.output_dir / "scan" / "source_snapshot.jsonl"
            self.source_snapshot_sha256 = _safe_file_hash(source_snapshot)

    def reuse_stage(self, stage_name: str, output_fingerprint: str) -> None:
        if stage_name == "scan":
            discovery_result = discover_files_with_ignored(self.options.source)
            self.source_files = tuple(discovery_result.source_files)
            self.ignored_files = tuple(discovery_result.ignored_files)
            source_snapshot = self.options.output_dir / "source_snapshot.jsonl"
            self.source_snapshot_sha256 = _safe_file_hash(source_snapshot)
        if stage_name == "extract":
            summary = _safe_read_json(self.options.output_dir / "extraction" / "summary.json")
            value = summary.get("failed_files", 0)
            self.extraction_failed_files = value if isinstance(value, int) else 0
        if stage_name == "validate_chunks":
            summary = _safe_read_json(self.options.output_dir / "validation" / "summary.json")
            self.validation_errors = _json_int(summary, "errors")
            self.duplicate_chunk_ids = _json_int(summary, "duplicate_chunk_ids")
            self.empty_text_chunks = _json_int(summary, "empty_text_chunks")
            self.invalid_chunk_references = _json_int(
                summary,
                "invalid_document_references",
            ) + _json_int(summary, "invalid_unit_references")


def _validate_options(options: RebuildCorpusOptions) -> None:
    if options.overwrite and options.resume:
        raise RebuildCorpusError("--overwriteと--resumeは同時に指定できません。")
    if not options.source.exists():
        raise FileNotFoundError(f"入力ルートが存在しません: {options.source}")
    if not options.source.is_dir():
        raise NotADirectoryError(f"入力ルートがディレクトリではありません: {options.source}")
    if options.top_k <= 0:
        raise ValueError("top_kは1以上である必要があります。")
    if options.candidate_multiplier <= 0:
        raise ValueError("candidate_multiplierは1以上である必要があります。")
    if options.rrf_k <= 0:
        raise ValueError("rrf_kは1以上である必要があります。")
    if options.enable_ocr and not (options.ocr_model_dir / "manifest.json").is_file():
        raise RebuildCorpusError(f"OCRモデルmanifestが存在しません: {options.ocr_model_dir}")


def _resolve_ocr_gpu(options: RebuildCorpusOptions) -> bool:
    requested = options.ocr_device.strip().lower()
    if requested == "gpu" and not is_torch_cuda_available():
        raise RebuildCorpusError("OCRでgpuが指定されましたが、CUDA対応Torchを利用できません。")
    return resolve_ocr_gpu_flag(options.ocr_device)


def _parser_name(context: _PipelineContext, source_file: SourceFile) -> str | None:
    try:
        return str(context.parser_registry.find_parser(source_file).name)
    except ParserNotFoundError:
        return None


def _source_file_record(source_file: SourceFile, parser_name: str | None) -> dict[str, Any]:
    return {
        "relative_path": source_file.relative_path.as_posix(),
        "suffix": source_file.suffix,
        "size_bytes": source_file.size_bytes,
        "parser_name": parser_name,
        "supported": parser_name is not None,
    }


def _snapshot_record(
    root: Path,
    source_file: SourceFile,
    parser_name: str | None,
) -> dict[str, Any]:
    return {
        "relative_path": source_file.relative_path.as_posix(),
        "suffix": source_file.suffix,
        "size_bytes": source_file.size_bytes,
        "sha256": _file_sha256(root.resolve() / source_file.relative_path),
        "parser_name": parser_name,
        "ignored": False,
        "ignored_reason": None,
    }


def _source_input_fingerprint(root: Path) -> str:
    discovery_result = discover_files_with_ignored(root)
    records: list[dict[str, Any]] = []
    for source_file in discovery_result.source_files:
        records.append(
            {
                "relative_path": source_file.relative_path.as_posix(),
                "suffix": source_file.suffix,
                "size_bytes": source_file.size_bytes,
                "sha256": _file_sha256(root.resolve() / source_file.relative_path),
                "ignored": False,
                "ignored_reason": None,
            }
        )
    for ignored_file in discovery_result.ignored_files:
        records.append(
            {
                "relative_path": ignored_file.relative_path,
                "suffix": ignored_file.suffix,
                "size_bytes": ignored_file.size_bytes,
                "sha256": _file_sha256(root.resolve() / ignored_file.relative_path),
                "ignored": True,
                "ignored_reason": ignored_file.reason,
            }
        )
    return _hash_json(sorted(records, key=lambda record: str(record["relative_path"])))


def _is_optional_skipped_stage(stage_name: str, options: RebuildCorpusOptions) -> bool:
    return (stage_name == "evaluate_search" and options.queries is None) or (
        stage_name == "compare_baseline" and options.baseline_dir is None
    )


def _enforce_quality_gate(context: _PipelineContext) -> None:
    if (
        context.extraction_failed_files > 0
        or context.validation_errors > 0
        or context.duplicate_chunk_ids > 0
        or context.empty_text_chunks > 0
        or context.invalid_chunk_references > 0
    ):
        raise RebuildCorpusError("strict_quality_gate_failed")


def _stage_dir_name(stage_name: str) -> str:
    return {
        "chunk": "chunks",
        "extract": "extraction",
        "validate_chunks": "validation",
        "build_bm25": "indexes",
        "evaluate_search": "evaluation",
        "compare_baseline": "comparison",
    }.get(stage_name, stage_name)


def _skipped_stage_status(
    stage_name: str,
    input_fingerprint: str,
    settings_fingerprint: str,
) -> StageStatus:
    return StageStatus(
        name=stage_name,
        status="skipped",
        started=None,
        completed=None,
        elapsed_seconds=0.0,
        input_fingerprint=input_fingerprint,
        output_fingerprint="",
        settings_fingerprint=settings_fingerprint,
        summary_path=None,
    )


def _reused_stage_status(existing: StageStatus) -> StageStatus:
    return StageStatus(
        name=existing.name,
        status="reused",
        started=None,
        completed=_now_iso(),
        elapsed_seconds=0.0,
        input_fingerprint=existing.input_fingerprint,
        output_fingerprint=existing.output_fingerprint,
        settings_fingerprint=existing.settings_fingerprint,
        summary_path=existing.summary_path,
    )


def _failed_stage_status(
    stage_name: str,
    context: _PipelineContext,
    error: Exception,
) -> StageStatus:
    return StageStatus(
        name=stage_name,
        status="failed",
        started=None,
        completed=_now_iso(),
        elapsed_seconds=0.0,
        input_fingerprint=context.input_fingerprint(stage_name),
        output_fingerprint="",
        settings_fingerprint=context.settings_fingerprint(stage_name),
        summary_path=None,
        error_type=type(error).__name__,
        error_message=str(error),
    )


def _write_source_snapshot_root(options: RebuildCorpusOptions, scan_snapshot: Path) -> None:
    temporary_path = options.output_dir / "source_snapshot.jsonl.tmp"
    shutil.copyfile(scan_snapshot, temporary_path)
    temporary_path.replace(options.output_dir / "source_snapshot.jsonl")


def _write_manifest(
    options: RebuildCorpusOptions,
    context: _PipelineContext,
    stages: Sequence[StageStatus],
) -> None:
    manifest = {
        "schema_version": 1,
        "pipeline_name": "full_corpus_rebuild",
        "source_snapshot_sha256": context.source_snapshot_sha256,
        "ocr": _ocr_manifest_record(options, context),
        "chunking": _chunk_settings(options),
        "bm25": _bm25_settings(options),
        "dependencies": _dependency_versions(),
        "platform": _platform_record(),
        "stages": [_stage_to_record(stage) for stage in stages],
    }
    _write_json_atomic(options.output_dir / "manifest.json", manifest)


def _ocr_manifest_record(
    options: RebuildCorpusOptions,
    context: _PipelineContext,
) -> dict[str, Any]:
    return {
        "enabled": options.enable_ocr,
        "requested_device": options.ocr_device,
        "resolved_device": context.resolved_ocr_device,
        "languages": list(options.ocr_languages),
        "model_manifest_sha256": _safe_file_hash(options.ocr_model_dir / "manifest.json")
        if options.enable_ocr
        else "",
        **_torch_record(),
    }


def _chunk_settings(options: RebuildCorpusOptions) -> dict[str, int]:
    return {
        "max_chars": options.max_chars,
        "overlap_chars": options.overlap_chars,
        "table_max_rows": options.table_max_rows,
    }


def _bm25_settings(options: RebuildCorpusOptions) -> dict[str, int]:
    return {
        "top_k": options.top_k,
        "candidate_multiplier": options.candidate_multiplier,
        "rrf_k": options.rrf_k,
    }


def _torch_record() -> dict[str, Any]:
    try:
        import torch
        import torchvision  # type: ignore[import-untyped]
    except ImportError:
        return {
            "torch_version": None,
            "torchvision_version": None,
            "torch_cuda_available": False,
            "torch_cuda_version": None,
            "cuda_device_count": 0,
            "cuda_device_name": None,
        }
    cuda_available = bool(torch.cuda.is_available())
    return {
        "torch_version": str(torch.__version__),
        "torchvision_version": str(torchvision.__version__),
        "torch_cuda_available": cuda_available,
        "torch_cuda_version": None if torch.version.cuda is None else str(torch.version.cuda),
        "cuda_device_count": int(torch.cuda.device_count()),
        "cuda_device_name": torch.cuda.get_device_name(0) if cuda_available else None,
    }


def _dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package_name in (
        "docling",
        "pypdf",
        "openpyxl",
        "defusedxml",
        "easyocr",
        "pypdfium2",
        "torch",
        "torchvision",
        "bm25s",
    ):
        try:
            versions[package_name] = importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return dict(sorted(versions.items()))


def _platform_record() -> dict[str, str]:
    return {
        "python_version": platform.python_version(),
        "system": platform.system(),
        "release": platform.release(),
    }


def _write_stage_statuses(path: Path, stages: Sequence[StageStatus]) -> None:
    _write_json_atomic(path, {"stages": [_stage_to_record(stage) for stage in stages]})


def _load_stage_statuses(path: Path) -> dict[str, StageStatus]:
    if not path.is_file():
        return {}
    record = _read_json(path)
    stages_value = record.get("stages")
    if not isinstance(stages_value, list):
        return {}
    statuses: dict[str, StageStatus] = {}
    for item in stages_value:
        if isinstance(item, dict):
            status = _stage_from_record(item)
            statuses[status.name] = status
    return statuses


def _stage_to_record(stage: StageStatus) -> dict[str, Any]:
    return {
        "name": stage.name,
        "status": stage.status,
        "started": stage.started,
        "completed": stage.completed,
        "elapsed_seconds": stage.elapsed_seconds,
        "input_fingerprint": stage.input_fingerprint,
        "output_fingerprint": stage.output_fingerprint,
        "settings_fingerprint": stage.settings_fingerprint,
        "summary_path": stage.summary_path,
        "error_type": stage.error_type,
        "error_message": stage.error_message,
    }


def _stage_from_record(record: dict[str, Any]) -> StageStatus:
    return StageStatus(
        name=_string(record.get("name")),
        status=_string(record.get("status")),
        started=_optional_string(record.get("started")),
        completed=_optional_string(record.get("completed")),
        elapsed_seconds=float(record.get("elapsed_seconds", 0.0)),
        input_fingerprint=_string(record.get("input_fingerprint")),
        output_fingerprint=_string(record.get("output_fingerprint")),
        settings_fingerprint=_string(record.get("settings_fingerprint")),
        summary_path=_optional_string(record.get("summary_path")),
        error_type=_optional_string(record.get("error_type")),
        error_message=_optional_string(record.get("error_message")),
    )


def _write_report(
    options: RebuildCorpusOptions,
    context: _PipelineContext,
    stages: Sequence[StageStatus],
) -> None:
    scan_summary = _safe_read_json(options.output_dir / "scan" / "summary.json")
    extraction_summary = _safe_read_json(options.output_dir / "extraction" / "summary.json")
    audit_summary = _safe_read_json(options.output_dir / "audit" / "summary.json")
    chunk_summary = _safe_read_json(options.output_dir / "chunks" / "summary.json")
    validation_summary = _safe_read_json(options.output_dir / "validation" / "summary.json")
    index_manifest = _safe_read_json(options.output_dir / "indexes" / "bm25" / "manifest.json")
    evaluation_summary = _safe_read_json(options.output_dir / "evaluation" / "summary.json")
    comparison_summary = _safe_read_json(options.output_dir / "comparison" / "summary.json")
    lines = [
        "# 全文書コーパス再構築レポート",
        "",
        "## 実行環境",
        "",
        f"- OCR requested_device: {options.ocr_device}",
        f"- OCR resolved_device: {context.resolved_ocr_device}",
        f"- CUDA利用可否: {_torch_record()['torch_cuda_available']}",
        "",
        "## 入力スナップショット",
        "",
        f"- source_snapshot_sha256: {context.source_snapshot_sha256}",
        "",
        "## 探索結果",
        "",
        _json_block(scan_summary),
        "",
        "## 形式別抽出結果",
        "",
        _json_block(extraction_summary.get("by_suffix", {})),
        "",
        "## OCR結果",
        "",
        _json_block(
            {
                "png_documents": audit_summary.get("png_documents", 0),
                "pdf_pages_ocr_targeted": audit_summary.get("pdf_pages_ocr_targeted", 0),
                "ocr_characters": audit_summary.get("ocr_characters", 0),
            }
        ),
        "",
        "## 抽出issue",
        "",
        _json_block(audit_summary.get("issues_by_type", {})),
        "",
        "## チャンク結果",
        "",
        _json_block(chunk_summary),
        "",
        "## チャンク検証",
        "",
        _json_block(validation_summary),
        "",
        "## BM25インデックス",
        "",
        _json_block(
            {
                "chunk_count": index_manifest.get("chunk_count", 0),
                "indexed_chunk_count": index_manifest.get("indexed_chunk_count", 0),
            }
        ),
        "",
        "## 検索評価",
        "",
        _json_block(evaluation_summary),
        "",
        "## 旧ベースラインとの比較",
        "",
        _json_block(comparison_summary),
        "",
        "## 品質ゲート",
        "",
        f"- strict: {options.strict}",
        f"- stage_status: {', '.join(stage.status for stage in stages)}",
        "",
        "## 次の判断",
        "",
        "- Office・PDFが自然文質問で取得できるようになったか",
        "- XLSXやCSVが検索結果を過度に占有していないか",
        "- OCRの誤認識がTop5へ過度に入っていないか",
        "- 会社名を含む質問で対象案件が上位になったか",
        "- 識別子検索の既存精度が維持されているか",
        "",
    ]
    _write_text_atomic(options.output_dir / "report.md", "\n".join(lines))


def _json_block(value: Any) -> str:
    return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n```"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON objectが必要です: {path}")
    return value


def _safe_read_json(path: Path) -> dict[str, Any]:
    return _read_json(path) if path.is_file() else {}


def _write_json_atomic(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _write_jsonl_atomic(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as output_file:
        for record in records:
            output_file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    temporary_path.replace(path)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(text, encoding="utf-8", newline="\n")
    temporary_path.replace(path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for block in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_file_hash(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    return _file_sha256(path)


def _hash_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _relative_artifact_path(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _string_value(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key}が文字列ではありません。")
    return value


def _json_int(mapping: dict[str, Any], key: str) -> int:
    value = mapping.get(key, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None
