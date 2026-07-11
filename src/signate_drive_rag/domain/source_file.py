"""共有ドライブ上の原本ファイルを表すドメインモデル。"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SourceFile:
    """共有ドライブから検出した原本ファイルの情報。"""

    path: Path
    relative_path: Path
    name: str
    suffix: str
    mime_type: str | None
    size_bytes: int
    modified_at: datetime
