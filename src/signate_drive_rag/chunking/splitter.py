"""検索用チャンクの共通テキスト分割処理。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextSegment:
    """分割されたテキストと元文字位置。"""

    text: str
    start: int
    end: int


def split_text(text: str, *, max_chars: int, overlap_chars: int) -> tuple[TextSegment, ...]:
    """テキストを自然な境界を優先しながら最大文字数以下へ分割する。"""
    validate_split_options(max_chars=max_chars, overlap_chars=overlap_chars)
    if text == "":
        return ()
    if len(text) <= max_chars:
        return (TextSegment(text=text, start=0, end=len(text)),)

    segments: list[TextSegment] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        split_end = len(text) if end == len(text) else _find_split_end(text, start, end)
        if split_end <= start:
            split_end = end

        segment_text = text[start:split_end]
        if segment_text.strip() != "":
            segments.append(TextSegment(text=segment_text, start=start, end=split_end))

        if split_end >= len(text):
            break
        next_start = split_end - min(overlap_chars, split_end - start)
        start = max(next_start, start + 1)

    return tuple(segments)


def validate_split_options(*, max_chars: int, overlap_chars: int) -> None:
    """分割設定の制約を検証する。"""
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than 0")
    if overlap_chars < 0:
        raise ValueError("overlap_chars must be greater than or equal to 0")
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be less than max_chars")


def _find_split_end(text: str, start: int, hard_end: int) -> int:
    """空行、改行、最大文字数の順で分割位置を決める。"""
    blank_line_end = _find_delimiter_end(text, "\n\n", start, hard_end)
    if blank_line_end is not None:
        return blank_line_end
    newline_end = _find_delimiter_end(text, "\n", start, hard_end)
    if newline_end is not None:
        return newline_end
    return hard_end


def _find_delimiter_end(text: str, delimiter: str, start: int, hard_end: int) -> int | None:
    """最大文字数を超えない範囲で最後の区切り位置を返す。"""
    delimiter_index = text.rfind(delimiter, start + 1, hard_end)
    while delimiter_index > start:
        delimiter_end = delimiter_index + len(delimiter)
        if delimiter_end <= hard_end:
            return delimiter_end
        delimiter_index = text.rfind(delimiter, start + 1, delimiter_index)
    return None
