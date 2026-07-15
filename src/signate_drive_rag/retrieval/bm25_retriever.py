"""保存済みBM25インデックスを用いた検索処理。"""

from typing import Protocol

from signate_drive_rag.retrieval.models import (
    CONTENT_NGRAM_CHANNEL,
    CONTENT_WORD_CHANNEL,
    CONTEXT_WORD_CHANNEL,
    LoadedBm25Index,
    SearchResult,
)
from signate_drive_rag.retrieval.rrf import fuse_rankings
from signate_drive_rag.retrieval.tokenizer import JapaneseNgramTokenizer, WordTokenizer


class SearchInputError(ValueError):
    """検索クエリや検索設定が不正な場合の例外。"""


class Retriever(Protocol):
    """質問文に関連する検索用チャンクを取得する。"""

    def search(self, query: str, top_k: int) -> tuple[SearchResult, ...]:
        """質問文に対する上位検索結果を返す。"""
        ...


class Bm25Retriever:
    """BM25の3チャネル検索結果をRRFで統合するRetriever。"""

    def __init__(
        self,
        index: LoadedBm25Index,
        *,
        candidate_multiplier: int = 5,
        rrf_k: int = 60,
    ) -> None:
        """検索設定を検証して保持する。"""
        if candidate_multiplier <= 0:
            raise ValueError("candidate_multiplierは1以上である必要があります。")
        if rrf_k <= 0:
            raise ValueError("rrf_kは1以上である必要があります。")
        self._index = index
        self._candidate_multiplier = candidate_multiplier
        self._rrf_k = rrf_k
        tokenizer_settings = index.manifest.get("tokenizer")
        ngram_min = 2
        ngram_max = 3
        if isinstance(tokenizer_settings, dict):
            min_value = tokenizer_settings.get("ngram_min")
            max_value = tokenizer_settings.get("ngram_max")
            if isinstance(min_value, int) and isinstance(max_value, int):
                ngram_min = min_value
                ngram_max = max_value
        self._word_tokenizer = WordTokenizer()
        self._ngram_tokenizer = JapaneseNgramTokenizer(ngram_min=ngram_min, ngram_max=ngram_max)

    def search(self, query: str, top_k: int) -> tuple[SearchResult, ...]:
        """質問文を3チャネルで検索し、RRF統合結果を返す。"""
        if top_k <= 0:
            raise ValueError("top_kは1以上である必要があります。")
        if query.strip() == "":
            raise SearchInputError("queryは空にできません。")
        if not self._index.records:
            return ()

        query_tokens = {
            CONTENT_WORD_CHANNEL: self._word_tokenizer.tokenize(query),
            CONTENT_NGRAM_CHANNEL: self._ngram_tokenizer.tokenize(query),
            CONTEXT_WORD_CHANNEL: self._word_tokenizer.tokenize(query),
        }
        if all(len(tokens) == 0 for tokens in query_tokens.values()):
            raise SearchInputError("検索に使用できるトークンがありません。")

        candidate_count = max(top_k * self._candidate_multiplier, top_k)
        channel_rankings = {
            channel_name: self._search_channel(channel_name, tokens, candidate_count)
            for channel_name, tokens in query_tokens.items()
            if tokens
        }
        fused_results = fuse_rankings(channel_rankings, rrf_k=self._rrf_k)
        record_by_chunk_id = {record.chunk_id: record for record in self._index.records}
        search_results = []
        for rank, fused_result in enumerate(fused_results[:top_k], start=1):
            record = record_by_chunk_id[fused_result.item_id]
            search_results.append(
                SearchResult(
                    rank=rank,
                    chunk_id=record.chunk_id,
                    relative_path=record.relative_path,
                    locator=record.locator,
                    parser_name=record.parser_name,
                    unit_type=record.unit_type,
                    score=fused_result.score,
                    channel_ranks=fused_result.channel_ranks,
                    text=record.text,
                    metadata=record.metadata,
                )
            )
        return tuple(search_results)

    def _search_channel(
        self,
        channel_name: str,
        query_tokens: tuple[str, ...],
        candidate_count: int,
    ) -> tuple[str, ...]:
        """1チャネルのBM25順位をchunk_id列に変換する。"""
        channel_index = self._index.channel_indexes.get(channel_name)
        if channel_index is None:
            return ()
        retrieval_count = min(candidate_count, len(self._index.records))
        raw_results = channel_index.retrieve(
            [list(query_tokens)],
            k=retrieval_count,
            show_progress=False,
        )
        document_indices = raw_results.documents[0].tolist()
        scores = raw_results.scores[0].tolist()
        chunk_ids = []
        for document_index, score in zip(document_indices, scores, strict=True):
            if score <= 0:
                continue
            chunk_ids.append(self._index.records[int(document_index)].chunk_id)
        return tuple(chunk_ids)
