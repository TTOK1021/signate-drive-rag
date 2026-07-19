"""共有ドライブ配下の原本ファイル探索処理。"""

import mimetypes
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from signate_drive_rag.document_diagnostics.models import IgnoredFile
from signate_drive_rag.document_diagnostics.office_filter import (
    is_office_temporary_file,
    office_temporary_file_reason,
)
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


@dataclass(frozen=True, slots=True)
class FileDiscoveryResult:
    """探索結果と除外されたファイルをまとめた情報。"""

    source_files: tuple[SourceFile, ...]
    ignored_files: tuple[IgnoredFile, ...]
    ignored_by_reason: dict[str, int]


def discover_files(
    root: Path,
    excluded_dir_names: frozenset[str] | None = None,
) -> list[SourceFile]:
    """指定したルート配下から原本ファイルを再帰的に探索する。"""
    return list(discover_files_with_ignored(root, excluded_dir_names).source_files)


def discover_files_with_ignored(
    root: Path,
    excluded_dir_names: frozenset[str] | None = None,
) -> FileDiscoveryResult:
    """指定したルート配下から原本ファイルを探索し、除外結果も返す。"""
    if not root.exists():
        raise FileNotFoundError(f"入力ルートが存在しません: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"入力ルートがディレクトリではありません: {root}")

    resolved_root = root.resolve()
    excluded_names = (
        DEFAULT_EXCLUDED_DIR_NAMES if excluded_dir_names is None else excluded_dir_names
    )
    source_files: list[SourceFile] = []
    ignored_files: list[IgnoredFile] = []

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
            suffix = file_path.suffix.lower()
            if is_office_temporary_file(file_path):
                ignored_files.append(
                    IgnoredFile(
                        relative_path=relative_path.as_posix(),
                        suffix=suffix,
                        size_bytes=stat_result.st_size,
                        reason=office_temporary_file_reason(),
                    )
                )
                continue

            mime_type, _encoding = mimetypes.guess_type(file_path)
            source_files.append(
                SourceFile(
                    path=file_path,
                    relative_path=relative_path,
                    name=file_path.name,
                    suffix=suffix,
                    mime_type=mime_type,
                    size_bytes=stat_result.st_size,
                    modified_at=datetime.fromtimestamp(stat_result.st_mtime, tz=UTC),
                )
            )

    sorted_source_files = tuple(
        sorted(source_files, key=lambda source_file: source_file.relative_path.as_posix())
    )
    sorted_ignored_files = tuple(
        sorted(ignored_files, key=lambda ignored_file: ignored_file.relative_path)
    )
    ignored_by_reason: dict[str, int] = {}
    for ignored_file in sorted_ignored_files:
        ignored_by_reason[ignored_file.reason] = ignored_by_reason.get(ignored_file.reason, 0) + 1
    return FileDiscoveryResult(
        source_files=sorted_source_files,
        ignored_files=sorted_ignored_files,
        ignored_by_reason=dict(sorted(ignored_by_reason.items())),
    )
