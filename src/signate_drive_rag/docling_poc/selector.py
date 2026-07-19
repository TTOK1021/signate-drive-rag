"""Docling PoC対象ファイルの決定的なサンプル選択。"""

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Sequence

from signate_drive_rag.docling_poc.models import SUPPORTED_DOCLING_SUFFIXES, SelectedDocument
from signate_drive_rag.domain import SourceFile


def group_candidates_by_suffix(
    source_files: Iterable[SourceFile],
    formats: frozenset[str] = SUPPORTED_DOCLING_SUFFIXES,
) -> dict[str, tuple[SourceFile, ...]]:
    """対象形式ごとに候補ファイルを分ける。"""
    grouped: dict[str, list[SourceFile]] = defaultdict(list)
    for source_file in source_files:
        if source_file.suffix in formats:
            grouped[source_file.suffix].append(source_file)
    return {
        suffix: tuple(
            sorted(files, key=lambda file: (file.size_bytes, file.relative_path.as_posix()))
        )
        for suffix, files in sorted(grouped.items())
    }


def select_representative_documents(
    source_files: Sequence[SourceFile],
    *,
    samples_per_format: int,
    formats: frozenset[str] = SUPPORTED_DOCLING_SUFFIXES,
) -> tuple[SelectedDocument, ...]:
    """ファイルサイズ分位点から代表サンプルを決定的に選択する。"""
    if samples_per_format <= 0:
        raise ValueError("samples_per_formatは1以上である必要があります。")

    selections: list[SelectedDocument] = []
    grouped = group_candidates_by_suffix(source_files, formats)
    for suffix, candidates in grouped.items():
        for rank, (candidate, quantile) in enumerate(
            _select_by_quantiles(candidates, samples_per_format),
            start=1,
        ):
            selections.append(
                SelectedDocument(
                    sample_id=_sample_id(candidate),
                    relative_path=candidate.relative_path.as_posix(),
                    suffix=suffix,
                    size_bytes=candidate.size_bytes,
                    selection_rank=rank,
                    selection_quantile=quantile,
                )
            )
    return tuple(
        sorted(selections, key=lambda selection: (selection.suffix, selection.selection_rank))
    )


def _select_by_quantiles(
    candidates: Sequence[SourceFile],
    samples_per_format: int,
) -> tuple[tuple[SourceFile, float], ...]:
    """重複を避けつつ、分位点に最も近い候補を返す。"""
    if len(candidates) <= samples_per_format:
        denominator = max(len(candidates) - 1, 1)
        return tuple((candidate, index / denominator) for index, candidate in enumerate(candidates))

    quantiles = _quantiles(samples_per_format)
    selected_indexes: list[int] = []
    for quantile in quantiles:
        target_index = round(quantile * (len(candidates) - 1))
        selected_indexes.append(
            _nearest_unused_index(target_index, len(candidates), selected_indexes)
        )
    return tuple(
        (candidates[index], quantile)
        for index, quantile in zip(selected_indexes, quantiles, strict=True)
    )


def _quantiles(samples_per_format: int) -> tuple[float, ...]:
    """サンプル数に応じた決定的な分位点を返す。"""
    if samples_per_format == 1:
        return (0.5,)
    return tuple(index / (samples_per_format - 1) for index in range(samples_per_format))


def _nearest_unused_index(target_index: int, count: int, used_indexes: Sequence[int]) -> int:
    """丸めで同じ位置になった場合に近傍から未使用位置を選ぶ。"""
    used = set(used_indexes)
    if target_index not in used:
        return target_index
    for distance in range(1, count):
        right = target_index + distance
        if right < count and right not in used:
            return right
        left = target_index - distance
        if left >= 0 and left not in used:
            return left
    raise ValueError("選択可能な候補がありません。")


def _sample_id(source_file: SourceFile) -> str:
    """相対パス・拡張子・サイズだけから安定したIDを生成する。"""
    payload = "\n".join(
        [
            source_file.relative_path.as_posix(),
            source_file.suffix,
            str(source_file.size_bytes),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
