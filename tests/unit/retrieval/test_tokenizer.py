"""検索Tokenizerのテスト。"""

import pytest

from signate_drive_rag.retrieval.models import LexicalRecord
from signate_drive_rag.retrieval.tokenizer import (
    JapaneseNgramTokenizer,
    WordTokenizer,
    build_context_text,
)


def test_word_tokenizer_extracts_words_identifiers_numbers_and_japanese() -> None:
    """単語、識別子、数値、日本語連続文字列を決定的に抽出する。"""
    tokens = WordTokenizer().tokenize(
        "Contract TASK-001 customer_id version1.2 2026/07 5,000,000 1.5 契約金額"
    )

    assert "contract" in tokens
    assert "task-001" in tokens
    assert "task" in tokens
    assert "001" in tokens
    assert "customer_id" in tokens
    assert "customer" in tokens
    assert "id" in tokens
    assert "version1.2" in tokens
    assert "2026/07" in tokens
    assert "5,000,000" in tokens
    assert "5000000" in tokens
    assert "1.5" in tokens
    assert "契約金額" in tokens
    assert tokens == WordTokenizer().tokenize(
        "Contract TASK-001 customer_id version1.2 2026/07 5,000,000 1.5 契約金額"
    )


def test_word_tokenizer_returns_empty_for_empty_text_and_preserves_frequency() -> None:
    """空文字列では空になり、別位置の同一語頻度は保持する。"""
    assert WordTokenizer().tokenize("") == ()
    assert WordTokenizer().tokenize("alpha alpha").count("alpha") == 2


def test_japanese_ngram_tokenizer_generates_2gram_and_3gram_without_crossing_symbols() -> None:
    """日本語文字N-gramを句読点や空白をまたがず生成する。"""
    tokens = JapaneseNgramTokenizer(2, 3).tokenize("契約金額 顧客。サポート かな")

    assert "契約" in tokens
    assert "約金" in tokens
    assert "金額" in tokens
    assert "契約金" in tokens
    assert "約金額" in tokens
    assert "顧客" in tokens
    assert "サポ" in tokens
    assert "ート" in tokens
    assert "かな" in tokens
    assert "額顧" not in tokens
    assert "客サ" not in tokens
    assert all("abc" not in token for token in JapaneseNgramTokenizer().tokenize("abc123"))


def test_japanese_ngram_tokenizer_rejects_invalid_range_and_short_text() -> None:
    """不正なN-gram設定を拒否し、短すぎる日本語列は空にする。"""
    assert JapaneseNgramTokenizer(2, 3).tokenize("契") == ()
    with pytest.raises(ValueError):
        JapaneseNgramTokenizer(0, 3)
    with pytest.raises(ValueError):
        JapaneseNgramTokenizer(3, 2)


def test_build_context_text_uses_selected_metadata_only_deterministically() -> None:
    """検索文脈に必要なmetadataだけを決定的な文字列へ変換する。"""
    record = LexicalRecord(
        record_index=0,
        chunk_id="chunk",
        relative_path="プロジェクト/資料/契約一覧.csv",
        parser_name="delimited_text",
        unit_type="table_rows",
        text="本文",
        locator="row:2-3",
        metadata={
            "headers": ["顧客名", "契約金額"],
            "heading_path": ["ignored"],
            "json_pointer": "/root/value",
            "cell_type": "markdown",
            "huge_values": ["本文を重複させない"],
        },
    )

    context = build_context_text(record)

    assert "file=契約一覧.csv" in context
    assert "path=プロジェクト/資料/契約一覧.csv" in context
    assert "headers=顧客名 契約金額" in context
    assert "json_pointer=/root/value" in context
    assert "cell_type=markdown" in context
    assert "huge_values" not in context
    assert context == build_context_text(record)
