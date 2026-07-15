"""BM25検索で使用する決定的なTokenizer。"""

import re
from pathlib import PurePosixPath
from typing import cast

from signate_drive_rag.domain.extracted_document import JsonValue
from signate_drive_rag.retrieval.models import LexicalRecord
from signate_drive_rag.retrieval.normalizer import normalize_text

_WORD_TOKEN_RE = re.compile(
    r"""
    \d{1,3}(?:,\d{3})+(?:\.\d+)?
    |[a-z0-9]+(?:[._/-][a-z0-9]+)*
    |[ぁ-んァ-ンー一-龯々〆ヶ]+
    """,
    re.VERBOSE,
)
_TOKEN_PART_RE = re.compile(r"[a-z0-9]+")
_JAPANESE_SEQUENCE_RE = re.compile(r"[ぁ-んァ-ンー一-龯々〆ヶ]+")
_CONTEXT_METADATA_KEYS = (
    "heading",
    "heading_path",
    "json_pointer",
    "headers",
    "cell_type",
    "output_type",
)


class WordTokenizer:
    """単語・識別子・日本語連続文字列を抽出するTokenizer。"""

    def tokenize(self, text: str) -> tuple[str, ...]:
        """正規化後のテキストから検索用トークンを生成する。"""
        normalized = normalize_text(text)
        tokens: list[str] = []
        for match in _WORD_TOKEN_RE.finditer(normalized):
            token = match.group(0)
            tokens.append(token)
            if "," in token and re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", token):
                tokens.append(token.replace(",", ""))
            for part in _TOKEN_PART_RE.findall(token):
                if part != token:
                    tokens.append(part)
        return tuple(tokens)


class JapaneseNgramTokenizer:
    """日本語文字N-gramを生成するTokenizer。"""

    def __init__(self, ngram_min: int = 2, ngram_max: int = 3) -> None:
        """N-gram長の範囲を検証して保持する。"""
        if ngram_min <= 0:
            raise ValueError("ngram_minは1以上である必要があります。")
        if ngram_max < ngram_min:
            raise ValueError("ngram_maxはngram_min以上である必要があります。")
        self.ngram_min = ngram_min
        self.ngram_max = ngram_max

    def tokenize(self, text: str) -> tuple[str, ...]:
        """正規化後の日本語連続文字列からN-gramを生成する。"""
        normalized = normalize_text(text)
        tokens: list[str] = []
        for match in _JAPANESE_SEQUENCE_RE.finditer(normalized):
            sequence = match.group(0)
            for ngram_size in range(self.ngram_min, self.ngram_max + 1):
                if len(sequence) < ngram_size:
                    continue
                for start in range(0, len(sequence) - ngram_size + 1):
                    tokens.append(sequence[start : start + ngram_size])
        return tuple(tokens)


def build_context_text(record: LexicalRecord) -> str:
    """検索結果の周辺情報だけを決定的なコンテキスト文字列にする。"""
    parts = [
        f"file={PurePosixPath(record.relative_path).name}",
        f"path={record.relative_path}",
        f"parser={record.parser_name}",
        f"unit={record.unit_type}",
    ]
    if record.locator is not None:
        parts.append(f"locator={record.locator}")

    for key in _CONTEXT_METADATA_KEYS:
        if key not in record.metadata:
            continue
        value = record.metadata[key]
        formatted_value = _format_context_value(value)
        if formatted_value != "":
            parts.append(f"{key}={formatted_value}")
    return "\n".join(parts)


def _format_context_value(value: JsonValue) -> str:
    """巨大な値の流入を避けるため、検索文脈に使う型を限定する。"""
    if isinstance(value, str):
        return value
    if isinstance(value, int | float | bool):
        return str(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return " ".join(cast(list[str], value))
    return ""
