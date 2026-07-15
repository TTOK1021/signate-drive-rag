"""抽出済み文書から検索用チャンクを生成するサービス。"""

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from typing import cast

from signate_drive_rag.chunking.models import (
    ChunkingResult,
    ChunkingSummary,
    ChunkIssue,
    ChunkSourceDocument,
    ChunkSourceUnit,
    RetrievalChunk,
)
from signate_drive_rag.chunking.splitter import TextSegment, split_text, validate_split_options
from signate_drive_rag.domain.extracted_document import JsonValue

DEFAULT_MAX_CHARS = 4_000
DEFAULT_OVERLAP_CHARS = 200
DEFAULT_TABLE_MAX_ROWS = 25

ISSUE_TYPES = (
    "source_document_has_no_units",
    "empty_source_unit_skipped",
    "fallback_chunking_used",
    "table_metadata_missing",
    "chunk_limit_violation",
)
SEVERITIES = ("error", "warning", "info")
KNOWN_UNIT_TYPES = {
    "text",
    "markdown_section",
    "json_value",
    "notebook_cell",
    "notebook_output",
    "table_header",
    "table_row",
}


class ChunkingService:
    """抽出済み文書から検索用チャンクを生成する。"""

    def __init__(
        self,
        *,
        max_chars: int = DEFAULT_MAX_CHARS,
        overlap_chars: int = DEFAULT_OVERLAP_CHARS,
        table_max_rows: int = DEFAULT_TABLE_MAX_ROWS,
    ) -> None:
        """チャンク生成設定を受け取る。"""
        validate_split_options(max_chars=max_chars, overlap_chars=overlap_chars)
        if table_max_rows <= 0:
            raise ValueError("table_max_rows must be greater than 0")
        self._max_chars = max_chars
        self._overlap_chars = overlap_chars
        self._table_max_rows = table_max_rows

    def chunk(self, documents: Sequence[ChunkSourceDocument]) -> ChunkingResult:
        """複数文書をチャンク化する。"""
        chunks: list[RetrievalChunk] = []
        issues: list[ChunkIssue] = []
        for document in sorted(documents, key=lambda item: item.relative_path):
            document_chunks, document_issues = self._chunk_document(document)
            chunks.extend(document_chunks)
            issues.extend(document_issues)

        sorted_chunks = tuple(
            sorted(chunks, key=lambda item: (item.relative_path, item.chunk_index))
        )
        sorted_issues = tuple(sorted(issues, key=_issue_sort_key))
        summary = _build_summary(documents, sorted_chunks, sorted_issues)
        return ChunkingResult(chunks=sorted_chunks, issues=sorted_issues, summary=summary)

    def _chunk_document(
        self,
        document: ChunkSourceDocument,
    ) -> tuple[list[RetrievalChunk], list[ChunkIssue]]:
        """1文書をチャンク化し、文書内chunk_indexを付与する。"""
        if len(document.units) == 0:
            return [], [
                ChunkIssue(
                    relative_path=document.relative_path,
                    parser_name=document.parser_name,
                    issue_type="source_document_has_no_units",
                    severity="info",
                    message="抽出単位が0件のためチャンクを生成しません。",
                )
            ]

        raw_chunks: list[_RawChunk] = []
        issues: list[ChunkIssue] = []
        if document.parser_name == "delimited_text" or any(
            unit.unit_type in {"table_header", "table_row"} for unit in document.units
        ):
            table_chunks, table_issues = self._chunk_table_document(document)
            raw_chunks.extend(table_chunks)
            issues.extend(table_issues)
        else:
            for unit_index, unit in enumerate(document.units):
                unit_chunks, unit_issues = self._chunk_unit(document, unit, unit_index)
                raw_chunks.extend(unit_chunks)
                issues.extend(unit_issues)

        chunks: list[RetrievalChunk] = []
        for chunk_index, raw_chunk in enumerate(raw_chunks):
            chunk = _raw_chunk_to_retrieval_chunk(document, raw_chunk, chunk_index)
            chunks.append(chunk)
            if len(chunk.text) > self._max_chars:
                issues.append(
                    ChunkIssue(
                        relative_path=document.relative_path,
                        parser_name=document.parser_name,
                        issue_type="chunk_limit_violation",
                        severity="error",
                        message=(
                            f"チャンク文字数が上限を超えています。"
                            f"characters={len(chunk.text)}, max_chars={self._max_chars}"
                        ),
                        source_unit_index=chunk.source_unit_indices[0]
                        if chunk.source_unit_indices
                        else None,
                        locator=chunk.locator,
                    )
                )
        return chunks, issues

    def _chunk_unit(
        self,
        document: ChunkSourceDocument,
        unit: ChunkSourceUnit,
        unit_index: int,
    ) -> tuple[list["_RawChunk"], list[ChunkIssue]]:
        """表以外の抽出単位をチャンク化する。"""
        if unit.text == "":
            return [], [
                ChunkIssue(
                    relative_path=document.relative_path,
                    parser_name=document.parser_name,
                    issue_type="empty_source_unit_skipped",
                    severity="info",
                    message="空の抽出単位をスキップしました。",
                    source_unit_index=unit_index,
                    locator=unit.locator,
                )
            ]

        issues: list[ChunkIssue] = []
        if unit.unit_type not in KNOWN_UNIT_TYPES:
            issues.append(
                ChunkIssue(
                    relative_path=document.relative_path,
                    parser_name=document.parser_name,
                    issue_type="fallback_chunking_used",
                    severity="info",
                    message=(
                        f"未知のunit_typeのため汎用分割へフォールバックしました: {unit.unit_type}"
                    ),
                    source_unit_index=unit_index,
                    locator=unit.locator,
                )
            )

        segments = split_text(
            unit.text,
            max_chars=self._max_chars,
            overlap_chars=self._overlap_chars,
        )
        chunks = [
            _RawChunk(
                unit_type=unit.unit_type,
                text=segment.text,
                locator=_split_locator(unit, segment),
                source_unit_indices=(unit_index,),
                metadata=_unit_metadata(unit, segment, split_index, len(segments)),
            )
            for split_index, segment in enumerate(segments)
        ]
        return chunks, issues

    def _chunk_table_document(
        self,
        document: ChunkSourceDocument,
    ) -> tuple[list["_RawChunk"], list[ChunkIssue]]:
        """CSV・TSVのヘッダーと行をまとめてチャンク化する。"""
        issues: list[ChunkIssue] = []
        header_index = _find_table_header_index(document.units)
        if header_index is None:
            return self._fallback_table_units(document, "table_headerが見つかりません。")

        header = document.units[header_index]
        headers = _metadata_string_list(header.metadata.get("headers"))
        delimiter = _metadata_string(header.metadata.get("delimiter")) or ""
        if headers is None:
            return self._fallback_table_units(document, "table_headerのheadersが不正です。")

        rows: list[tuple[int, ChunkSourceUnit]] = [
            (unit_index, unit)
            for unit_index, unit in enumerate(document.units)
            if unit.unit_type == "table_row"
        ]
        if not rows:
            text = f"列: {' | '.join(headers)}"
            return [
                _RawChunk(
                    unit_type="table_rows",
                    text=text,
                    locator=header.locator,
                    source_unit_indices=(header_index,),
                    metadata={
                        "headers": _json_list(headers),
                        "start_row": 1,
                        "end_row": 1,
                        "row_count": 0,
                        "delimiter": delimiter,
                        "source_locator": header.locator,
                        "original_unit_indices": [header_index],
                    },
                )
            ], issues

        chunks: list[_RawChunk] = []
        group: list[tuple[int, ChunkSourceUnit]] = []
        for row_index, row in rows:
            row_line = _table_row_line(row)
            if row_line is None:
                fallback_chunks, fallback_issues = self._fallback_table_units(
                    document,
                    f"table_rowのmetadataが不正です。unit_index={row_index}",
                )
                return fallback_chunks, [*issues, *fallback_issues]

            candidate = [*group, (row_index, row)]
            candidate_text = _table_group_text(headers, candidate)
            if group and (
                len(group) >= self._table_max_rows or len(candidate_text) > self._max_chars
            ):
                chunks.extend(
                    self._table_group_chunks(header_index, header, headers, delimiter, group)
                )
                group = [(row_index, row)]
                continue
            group = candidate

        if group:
            chunks.extend(self._table_group_chunks(header_index, header, headers, delimiter, group))
        return chunks, issues

    def _table_group_chunks(
        self,
        header_index: int,
        header: ChunkSourceUnit,
        headers: list[str],
        delimiter: str,
        group: list[tuple[int, ChunkSourceUnit]],
    ) -> list["_RawChunk"]:
        """表の行グループを最大文字数以下のチャンクへ変換する。"""
        text = _table_group_text(headers, group)
        start_row = _logical_row_number(group[0][1])
        end_row = _logical_row_number(group[-1][1])
        locator = f"row:{start_row}-{end_row}"
        source_unit_indices = (header_index, *(unit_index for unit_index, _unit in group))
        metadata: dict[str, JsonValue] = {
            "headers": _json_list(headers),
            "start_row": start_row,
            "end_row": end_row,
            "row_count": len(group),
            "delimiter": delimiter,
            "source_locator": header.locator,
            "original_unit_indices": list(source_unit_indices),
        }
        if len(text) <= self._max_chars:
            return [
                _RawChunk(
                    unit_type="table_rows",
                    text=text,
                    locator=locator,
                    source_unit_indices=source_unit_indices,
                    metadata=metadata,
                )
            ]

        segments = split_text(text, max_chars=self._max_chars, overlap_chars=self._overlap_chars)
        return [
            _RawChunk(
                unit_type="table_rows",
                text=segment.text,
                locator=locator,
                source_unit_indices=source_unit_indices,
                metadata={
                    **metadata,
                    "split_index": split_index,
                    "split_count": len(segments),
                    "original_unit_characters": len(text),
                },
            )
            for split_index, segment in enumerate(segments)
        ]

    def _fallback_table_units(
        self,
        document: ChunkSourceDocument,
        message: str,
    ) -> tuple[list["_RawChunk"], list[ChunkIssue]]:
        """表metadataが不正な場合に値を失わず汎用分割へ退避する。"""
        chunks: list[_RawChunk] = []
        issues: list[ChunkIssue] = []
        for unit_index, unit in enumerate(document.units):
            if unit.unit_type not in {"table_header", "table_row"}:
                continue
            unit_chunks, unit_issues = self._chunk_unit(document, unit, unit_index)
            chunks.extend(unit_chunks)
            issues.extend(unit_issues)
            issues.append(
                ChunkIssue(
                    relative_path=document.relative_path,
                    parser_name=document.parser_name,
                    issue_type="table_metadata_missing",
                    severity="warning",
                    message=message,
                    source_unit_index=unit_index,
                    locator=unit.locator,
                )
            )
        return chunks, issues


class _RawChunk:
    """chunk_indexとchunk_idを付与する前の内部チャンク。"""

    def __init__(
        self,
        *,
        unit_type: str,
        text: str,
        locator: str | None,
        source_unit_indices: tuple[int, ...],
        metadata: dict[str, JsonValue],
    ) -> None:
        self.unit_type = unit_type
        self.text = text
        self.locator = locator
        self.source_unit_indices = source_unit_indices
        self.metadata = metadata


def _raw_chunk_to_retrieval_chunk(
    document: ChunkSourceDocument,
    raw_chunk: _RawChunk,
    chunk_index: int,
) -> RetrievalChunk:
    """内部チャンクへchunk_indexとchunk_idを付与する。"""
    chunk_id = generate_chunk_id(
        relative_path=document.relative_path,
        parser_name=document.parser_name,
        unit_type=raw_chunk.unit_type,
        locator=raw_chunk.locator,
        source_unit_indices=raw_chunk.source_unit_indices,
        chunk_index=chunk_index,
        text=raw_chunk.text,
    )
    return RetrievalChunk(
        chunk_id=chunk_id,
        relative_path=document.relative_path,
        parser_name=document.parser_name,
        unit_type=raw_chunk.unit_type,
        text=raw_chunk.text,
        locator=raw_chunk.locator,
        source_unit_indices=raw_chunk.source_unit_indices,
        chunk_index=chunk_index,
        metadata=raw_chunk.metadata,
    )


def generate_chunk_id(
    *,
    relative_path: str,
    parser_name: str,
    unit_type: str,
    locator: str | None,
    source_unit_indices: tuple[int, ...],
    chunk_index: int,
    text: str,
) -> str:
    """チャンクを決定的に識別するSHA-256を生成する。"""
    payload = json.dumps(
        {
            "relative_path": relative_path,
            "parser_name": parser_name,
            "unit_type": unit_type,
            "locator": locator,
            "source_unit_indices": list(source_unit_indices),
            "chunk_index": chunk_index,
            "text": text,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _unit_metadata(
    unit: ChunkSourceUnit,
    segment: TextSegment,
    split_index: int,
    split_count: int,
) -> dict[str, JsonValue]:
    """元metadataへ分割情報を追加する。"""
    metadata = dict(unit.metadata)
    metadata.update(
        {
            "source_locator": unit.locator,
            "split_index": split_index,
            "split_count": split_count,
            "original_unit_characters": len(unit.text),
            "start_character": segment.start,
            "end_character": segment.end,
        }
    )
    return metadata


def _split_locator(unit: ChunkSourceUnit, segment: TextSegment) -> str | None:
    """locatorがないテキストunitには概算の行範囲を付与する。"""
    if unit.locator is not None:
        return unit.locator
    if unit.unit_type != "text":
        return None
    start_line = unit.text[: segment.start].count("\n") + 1
    end_line = unit.text[: segment.end].count("\n") + 1
    return f"line:{start_line}-{end_line}"


def _find_table_header_index(units: Sequence[ChunkSourceUnit]) -> int | None:
    """表ヘッダーunitの位置を取得する。"""
    for unit_index, unit in enumerate(units):
        if unit.unit_type == "table_header":
            return unit_index
    return None


def _table_group_text(headers: list[str], group: list[tuple[int, ChunkSourceUnit]]) -> str:
    """表の行グループを検索しやすいテキストへ変換する。"""
    lines = [f"列: {' | '.join(headers)}"]
    for _unit_index, unit in group:
        row_number = _logical_row_number(unit)
        values = _metadata_string_list(unit.metadata.get("values"))
        if values is None:
            values = [unit.text]
        lines.append(f"行{row_number}: {' | '.join(values)}")
    return "\n".join(lines)


def _table_row_line(unit: ChunkSourceUnit) -> str | None:
    """表行metadataから行テキストを組み立てられるか確認する。"""
    values = _metadata_string_list(unit.metadata.get("values"))
    if values is None or _logical_row_number(unit) <= 0:
        return None
    return f"行{_logical_row_number(unit)}: {' | '.join(values)}"


def _logical_row_number(unit: ChunkSourceUnit) -> int:
    """metadataの論理行番号を整数として取得する。"""
    value = unit.metadata.get("logical_row_number")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _metadata_string(value: JsonValue | None) -> str | None:
    """metadata値を文字列として取得する。"""
    return value if isinstance(value, str) else None


def _metadata_string_list(value: JsonValue | None) -> list[str] | None:
    """metadata値を文字列配列として取得する。"""
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(cast(list[str], value))
    return None


def _json_list(values: list[str]) -> list[JsonValue]:
    """文字列配列をJSON互換型として返す。"""
    return list(values)


def _build_summary(
    documents: Sequence[ChunkSourceDocument],
    chunks: Sequence[RetrievalChunk],
    issues: Sequence[ChunkIssue],
) -> ChunkingSummary:
    """チャンク生成結果の集計を作成する。"""
    source_characters = sum(len(unit.text) for document in documents for unit in document.units)
    chunk_characters = sum(len(chunk.text) for chunk in chunks)
    issue_type_counts = _count_with_keys([issue.issue_type for issue in issues], ISSUE_TYPES)
    severity_counts = _count_with_keys([issue.severity for issue in issues], SEVERITIES)
    return ChunkingSummary(
        source_documents=len(documents),
        source_units=sum(len(document.units) for document in documents),
        source_characters=source_characters,
        generated_chunks=len(chunks),
        chunk_characters=chunk_characters,
        maximum_chunk_characters=max((len(chunk.text) for chunk in chunks), default=0),
        average_chunk_characters=chunk_characters / len(chunks) if chunks else 0.0,
        character_reduction_rate=(
            0.0 if source_characters == 0 else 1 - chunk_characters / source_characters
        ),
        empty_units_skipped=issue_type_counts["empty_source_unit_skipped"],
        fallback_units=issue_type_counts["fallback_chunking_used"],
        total_issues=len(issues),
        issues_by_severity=severity_counts,
        issues_by_type=issue_type_counts,
        by_parser=_build_by_parser(documents, chunks),
        by_unit_type=_build_by_unit_type(documents, chunks),
    )


def _build_by_parser(
    documents: Sequence[ChunkSourceDocument],
    chunks: Sequence[RetrievalChunk],
) -> dict[str, JsonValue]:
    """パーサー別のチャンク集計を作成する。"""
    parser_names = sorted(
        {document.parser_name for document in documents} | {chunk.parser_name for chunk in chunks}
    )
    return {
        parser_name: _parser_summary(parser_name, documents, chunks) for parser_name in parser_names
    }


def _parser_summary(
    parser_name: str,
    documents: Sequence[ChunkSourceDocument],
    chunks: Sequence[RetrievalChunk],
) -> dict[str, JsonValue]:
    """1パーサー分の集計を作成する。"""
    parser_documents = [document for document in documents if document.parser_name == parser_name]
    parser_chunks = [chunk for chunk in chunks if chunk.parser_name == parser_name]
    return {
        "source_documents": len(parser_documents),
        "source_units": sum(len(document.units) for document in parser_documents),
        "source_characters": sum(
            len(unit.text) for document in parser_documents for unit in document.units
        ),
        "generated_chunks": len(parser_chunks),
        "chunk_characters": sum(len(chunk.text) for chunk in parser_chunks),
        "maximum_chunk_characters": max((len(chunk.text) for chunk in parser_chunks), default=0),
    }


def _build_by_unit_type(
    documents: Sequence[ChunkSourceDocument],
    chunks: Sequence[RetrievalChunk],
) -> dict[str, JsonValue]:
    """unit_type別のチャンク集計を作成する。"""
    source_unit_types = {unit.unit_type for document in documents for unit in document.units}
    chunk_unit_types = {chunk.unit_type for chunk in chunks}
    return {
        unit_type: _unit_type_summary(unit_type, documents, chunks)
        for unit_type in sorted(source_unit_types | chunk_unit_types)
    }


def _unit_type_summary(
    unit_type: str,
    documents: Sequence[ChunkSourceDocument],
    chunks: Sequence[RetrievalChunk],
) -> dict[str, JsonValue]:
    """1 unit_type分の集計を作成する。"""
    source_units = [
        unit for document in documents for unit in document.units if unit.unit_type == unit_type
    ]
    unit_chunks = [chunk for chunk in chunks if chunk.unit_type == unit_type]
    return {
        "source_units": len(source_units),
        "source_characters": sum(len(unit.text) for unit in source_units),
        "generated_chunks": len(unit_chunks),
        "chunk_characters": sum(len(chunk.text) for chunk in unit_chunks),
        "maximum_chunk_characters": max((len(chunk.text) for chunk in unit_chunks), default=0),
    }


def _count_with_keys(values: Sequence[str], keys: Sequence[str]) -> dict[str, int]:
    """既知キーを0件でも含めて集計する。"""
    counter = Counter(values)
    return {key: counter[key] for key in keys}


def _issue_sort_key(issue: ChunkIssue) -> tuple[str, int, str]:
    """issueを決定的に並べるキーを返す。"""
    source_unit_index = -1 if issue.source_unit_index is None else issue.source_unit_index
    return (issue.relative_path, source_unit_index, issue.issue_type)
