"""検索用チャンクの整合性を検証するサービス。"""

import math
import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

from signate_drive_rag.chunk_validation.models import (
    ChunkValidationError,
    ChunkValidationResult,
    ChunkValidationSummary,
)
from signate_drive_rag.chunking.models import ChunkSourceDocument, RetrievalChunk
from signate_drive_rag.domain.extracted_document import JsonValue

WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"[A-Za-z]:[\\/][^\s\"']+")
POSIX_ABSOLUTE_PATH_PATTERN = re.compile(r"(?<![\w:])/[^\s\"']+")
TABLE_UNIT_TYPES = frozenset({"table_rows", "xlsx_table_rows"})
OCR_UNIT_TYPES = frozenset({"image_ocr_text", "pdf_page_ocr"})
VALIDATION_RULESET_VERSION = 2


class ChunkValidationService:
    """検索用チャンクの参照、本文、locator、metadataを検証する。"""

    def __init__(self, *, max_chars: int) -> None:
        """チャンク文字数上限を受け取る。"""
        if max_chars <= 0:
            raise ValueError("max_charsは1以上である必要があります。")
        self._max_chars = max_chars

    def validate(
        self,
        *,
        chunks: Sequence[RetrievalChunk],
        source_documents: Sequence[ChunkSourceDocument],
    ) -> ChunkValidationResult:
        """チャンクと抽出元文書の整合性を検証する。"""
        errors: list[ChunkValidationError] = []
        document_units = {
            document.relative_path: len(document.units) for document in source_documents
        }
        errors.extend(_duplicate_id_errors(chunks))
        errors.extend(_duplicate_content_errors(chunks))

        for chunk in chunks:
            errors.extend(self._validate_chunk(chunk, document_units))

        sorted_errors = tuple(sorted(errors, key=_error_sort_key))
        summary = _build_summary(chunks, source_documents, sorted_errors)
        return ChunkValidationResult(summary=summary, errors=sorted_errors)

    def _validate_chunk(
        self,
        chunk: RetrievalChunk,
        document_units: dict[str, int],
    ) -> list[ChunkValidationError]:
        errors: list[ChunkValidationError] = []
        if chunk.text.strip() == "":
            errors.append(_chunk_error(chunk, "empty_text_chunk", "本文が空です。"))
        if "\x00" in chunk.text:
            errors.append(_chunk_error(chunk, "nul_text_chunk", "本文にNUL文字があります。"))
        if _contains_absolute_path(chunk.relative_path) or _metadata_contains_absolute_path(
            chunk.metadata
        ):
            errors.append(
                _chunk_error(chunk, "absolute_path_detected", "絶対パスが含まれています。")
            )

        unit_count = document_units.get(chunk.relative_path)
        if unit_count is None:
            errors.append(
                _chunk_error(chunk, "invalid_document_reference", "参照先文書がありません。")
            )
        elif any(index < 0 or index >= unit_count for index in chunk.source_unit_indices):
            errors.append(_chunk_error(chunk, "invalid_unit_reference", "参照先unitが不正です。"))

        if not _is_valid_locator(chunk):
            errors.append(_chunk_error(chunk, "invalid_locator", "locator形式が不正です。"))
        if not _is_json_compatible(chunk.metadata):
            errors.append(
                _chunk_error(
                    chunk,
                    "json_metadata_error",
                    "metadataがJSON互換ではありません。",
                )
            )
        if len(chunk.text) > self._max_chars and not _oversize_is_explained(chunk):
            errors.append(
                _chunk_error(
                    chunk,
                    "oversized_chunk",
                    f"チャンク文字数が上限を超えています: {len(chunk.text)}",
                )
            )
        return errors


def _duplicate_id_errors(chunks: Sequence[RetrievalChunk]) -> list[ChunkValidationError]:
    counts = Counter(chunk.chunk_id for chunk in chunks)
    return [
        ChunkValidationError(
            chunk_id=chunk_id,
            relative_path=None,
            issue_type="duplicate_chunk_id",
            severity="error",
            message="chunk_idが重複しています。",
        )
        for chunk_id, count in sorted(counts.items())
        if count > 1
    ]


def _duplicate_content_errors(chunks: Sequence[RetrievalChunk]) -> list[ChunkValidationError]:
    keys = Counter((chunk.relative_path, chunk.text) for chunk in chunks)
    return [
        ChunkValidationError(
            chunk_id=None,
            relative_path=relative_path,
            issue_type="duplicate_chunk_content",
            severity="warning",
            message="同一文書内で本文が重複しています。",
        )
        for (relative_path, _text), count in sorted(keys.items())
        if count > 1
    ]


def _chunk_error(chunk: RetrievalChunk, issue_type: str, message: str) -> ChunkValidationError:
    return ChunkValidationError(
        chunk_id=chunk.chunk_id,
        relative_path=chunk.relative_path,
        issue_type=issue_type,
        severity="error",
        message=message,
        locator=chunk.locator,
    )


def _contains_absolute_path(text: str) -> bool:
    if WINDOWS_ABSOLUTE_PATH_PATTERN.search(text) is not None:
        return True
    return POSIX_ABSOLUTE_PATH_PATTERN.search(text) is not None


def _metadata_contains_absolute_path(metadata: dict[str, JsonValue]) -> bool:
    return any(
        _metadata_field_contains_absolute_path(key, value) for key, value in metadata.items()
    )


def _metadata_field_contains_absolute_path(key: str, value: JsonValue) -> bool:
    if isinstance(value, str):
        # JSON Pointerなど、パスではない位置表現の先頭スラッシュを誤検出しない。
        return "path" in key.lower() and _contains_absolute_path(value)
    if isinstance(value, list):
        return any(_metadata_field_contains_absolute_path(key, item) for item in value)
    if isinstance(value, dict):
        return any(
            _metadata_field_contains_absolute_path(child_key, item)
            for child_key, item in value.items()
        )
    return False


def _is_valid_locator(chunk: RetrievalChunk) -> bool:
    if chunk.locator is None:
        return True
    if chunk.unit_type.startswith("pdf_"):
        return chunk.locator.startswith("page:")
    if chunk.unit_type.startswith("pptx_"):
        return chunk.locator.startswith("slide:")
    if chunk.unit_type.startswith("xlsx_"):
        if chunk.unit_type == "xlsx_workbook_summary":
            return chunk.locator == "workbook"
        if chunk.unit_type == "xlsx_sheet_summary":
            return chunk.locator.startswith("sheet:")
        return chunk.locator.startswith("sheet:") and "range:" in chunk.locator
    if chunk.unit_type == "image_ocr_text":
        return chunk.locator.startswith("image:")
    return True


def _is_json_compatible(value: JsonValue | dict[str, JsonValue]) -> bool:
    return _is_json_value(value)


def _is_json_value(value: Any) -> bool:
    if value is None or isinstance(value, str | bool | int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    return False


def _oversize_is_explained(chunk: RetrievalChunk) -> bool:
    return "original_unit_characters" in chunk.metadata or "source_quality" in chunk.metadata


def _build_summary(
    chunks: Sequence[RetrievalChunk],
    source_documents: Sequence[ChunkSourceDocument],
    errors: Sequence[ChunkValidationError],
) -> ChunkValidationSummary:
    lengths = sorted(len(chunk.text) for chunk in chunks)
    error_counts = Counter(error.issue_type for error in errors)
    severity_counts = Counter(error.severity for error in errors)
    return ChunkValidationSummary(
        chunks=len(chunks),
        source_documents=len(source_documents),
        source_units=sum(len(document.units) for document in source_documents),
        errors=severity_counts["error"],
        warnings=severity_counts["warning"],
        duplicate_chunk_ids=error_counts["duplicate_chunk_id"],
        duplicate_chunk_contents=error_counts["duplicate_chunk_content"],
        empty_text_chunks=error_counts["empty_text_chunk"],
        nul_text_chunks=error_counts["nul_text_chunk"],
        invalid_document_references=error_counts["invalid_document_reference"],
        invalid_unit_references=error_counts["invalid_unit_reference"],
        absolute_path_violations=error_counts["absolute_path_detected"],
        invalid_locator_count=error_counts["invalid_locator"],
        json_metadata_errors=error_counts["json_metadata_error"],
        oversized_chunks=error_counts["oversized_chunk"],
        maximum_chunk_characters=max(lengths, default=0),
        mean_chunk_characters=sum(lengths) / len(lengths) if lengths else 0.0,
        median_chunk_characters=_percentile(lengths, 0.50),
        p95_chunk_characters=_percentile(lengths, 0.95),
        text_chunks=sum(
            1 for chunk in chunks if chunk.unit_type not in TABLE_UNIT_TYPES | OCR_UNIT_TYPES
        ),
        table_chunks=sum(1 for chunk in chunks if chunk.unit_type in TABLE_UNIT_TYPES),
        ocr_chunks=sum(1 for chunk in chunks if chunk.unit_type in OCR_UNIT_TYPES),
    )


def _percentile(sorted_values: Sequence[int], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _error_sort_key(error: ChunkValidationError) -> tuple[str, str, str]:
    return (error.relative_path or "", error.chunk_id or "", error.issue_type)
