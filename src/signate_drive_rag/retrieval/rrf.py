"""Reciprocal Rank Fusionによる順位統合。"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RrfResult:
    """RRFで統合した1件分の順位情報。"""

    item_id: str
    score: float
    channel_ranks: dict[str, int]


def fuse_rankings(
    channel_rankings: Mapping[str, Sequence[str]],
    *,
    rrf_k: int = 60,
) -> tuple[RrfResult, ...]:
    """複数チャネルの順位をRRFで統合する。"""
    if rrf_k <= 0:
        raise ValueError("rrf_kは1以上である必要があります。")

    ranks_by_item: dict[str, dict[str, int]] = {}
    for channel_name in sorted(channel_rankings):
        for rank, item_id in enumerate(channel_rankings[channel_name], start=1):
            ranks_by_item.setdefault(item_id, {})
            ranks_by_item[item_id].setdefault(channel_name, rank)

    results = tuple(
        RrfResult(
            item_id=item_id,
            score=sum(1.0 / (rrf_k + rank) for rank in channel_ranks.values()),
            channel_ranks=dict(sorted(channel_ranks.items())),
        )
        for item_id, channel_ranks in ranks_by_item.items()
    )
    return tuple(sorted(results, key=_rrf_sort_key))


def _rrf_sort_key(result: RrfResult) -> tuple[float, int, int, str]:
    """同点時も再現可能な順位にするためのキーを返す。"""
    best_rank = min(result.channel_ranks.values())
    return (-result.score, best_rank, -len(result.channel_ranks), result.item_id)
