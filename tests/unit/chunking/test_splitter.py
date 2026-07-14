"""共通テキスト分割処理の単体テスト。"""

import pytest

from signate_drive_rag.chunking.splitter import split_text


def texts(value: str, *, max_chars: int, overlap_chars: int = 0) -> list[str]:
    """分割結果の本文だけを返す。"""
    return [
        segment.text
        for segment in split_text(value, max_chars=max_chars, overlap_chars=overlap_chars)
    ]


def test_split_text_does_not_split_short_text() -> None:
    """max_chars以下のテキストを分割しない。"""
    assert texts("abc", max_chars=3) == ["abc"]


def test_split_text_prefers_blank_line_then_newline() -> None:
    """空行を改行より優先して分割する。"""
    assert texts("aa\n\nbb\ncc", max_chars=6) == ["aa\n\n", "bb\ncc"]
    assert texts("aa\nbbcc", max_chars=5) == ["aa\n", "bbcc"]


def test_split_text_force_splits_without_boundaries() -> None:
    """境界がない長文を強制分割できる。"""
    chunks = texts("abcdef", max_chars=2)

    assert chunks == ["ab", "cd", "ef"]
    assert all(len(chunk) <= 2 for chunk in chunks)


def test_split_text_does_not_include_delimiter_beyond_max_chars() -> None:
    """上限位置の区切り文字を含めてmax_charsを超えない。"""
    chunks = texts("abcd\nef", max_chars=4)

    assert chunks == ["abcd", "\nef"]
    assert all(len(chunk) <= 4 for chunk in chunks)


def test_split_text_adds_overlap_without_losing_text() -> None:
    """前チャンク末尾から指定文字数を次チャンクへ含める。"""
    chunks = texts("abcdef", max_chars=4, overlap_chars=1)

    assert chunks == ["abcd", "def"]
    assert "abc" in "".join(chunks)


def test_split_text_handles_empty_one_character_and_japanese() -> None:
    """空文字、1文字、日本語を文字単位で処理する。"""
    assert texts("", max_chars=3) == []
    assert texts("あ", max_chars=3) == ["あ"]
    assert texts("あいうえ", max_chars=2) == ["あい", "うえ"]


def test_split_text_accepts_zero_overlap_and_is_deterministic() -> None:
    """overlap_chars=0を扱い、同じ入力では同じ結果になる。"""
    first = split_text("a\nb\nc", max_chars=3, overlap_chars=0)
    second = split_text("a\nb\nc", max_chars=3, overlap_chars=0)

    assert first == second


@pytest.mark.parametrize(
    ("max_chars", "overlap_chars"),
    [(0, 0), (4, -1), (4, 4), (4, 5)],
)
def test_split_text_rejects_invalid_options(max_chars: int, overlap_chars: int) -> None:
    """不正な分割設定では例外になる。"""
    with pytest.raises(ValueError):
        split_text("abc", max_chars=max_chars, overlap_chars=overlap_chars)
