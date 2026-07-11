"""共有ドライブ配下の原本ファイル探索処理。"""

import mimetypes
import os
from datetime import UTC, datetime
from pathlib import Path

from signate_drive_rag.domain import SourceFile

DEFAULT_EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
)


def discover_files(
    root: Path,
    excluded_dir_names: frozenset[str] | None = None,
) -> list[SourceFile]:
    """指定したルート配下から原本ファイルを再帰的に探索する。"""
    if not root.exists():
        raise FileNotFoundError(f"入力ルートが存在しません: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"入力ルートがディレクトリではありません: {root}")

    resolved_root = root.resolve()
    excluded_names = (
        DEFAULT_EXCLUDED_DIR_NAMES if excluded_dir_names is None else excluded_dir_names
    )
    source_files: list[SourceFile] = []

    for current_dir_name, dir_names, file_names in os.walk(
        resolved_root,
        topdown=True,
        followlinks=False,
    ):
        current_dir = Path(current_dir_name)

        # 探索時点で枝刈りすることで、除外対象ディレクトリ配下のstat取得も避ける。
        dir_names[:] = [
            dir_name
            for dir_name in dir_names
            if dir_name not in excluded_names and not (current_dir / dir_name).is_symlink()
        ]

        for file_name in file_names:
            file_path = current_dir / file_name
            if not file_path.is_file():
                continue

            stat_result = file_path.stat()
            relative_path = file_path.relative_to(resolved_root)
            mime_type, _encoding = mimetypes.guess_type(file_path)
            source_files.append(
                SourceFile(
                    path=file_path,
                    relative_path=relative_path,
                    name=file_path.name,
                    suffix=file_path.suffix.lower(),
                    mime_type=mime_type,
                    size_bytes=stat_result.st_size,
                    modified_at=datetime.fromtimestamp(stat_result.st_mtime, tz=UTC),
                )
            )

    return sorted(source_files, key=lambda source_file: source_file.relative_path.as_posix())
