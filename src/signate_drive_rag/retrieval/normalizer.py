"""検索対象と質問文へ共通適用するテキスト正規化。"""

import re
import unicodedata

_HORIZONTAL_WHITESPACE_RE = re.compile(r"[ \t\f\v]+")


def normalize_text(text: str) -> str:
    """BM25検索で比較可能にするための正規化を行う。"""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in normalized.split("\n"):
        lines.append(_HORIZONTAL_WHITESPACE_RE.sub(" ", line).strip())
    return "\n".join(lines).strip()
