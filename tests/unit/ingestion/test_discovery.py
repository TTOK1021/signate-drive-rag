"""ファイル探索処理の単体テスト。"""

from pathlib import Path

import pytest

from signate_drive_rag.ingestion import discover_files


def test_discover_files_includes_nested_japanese_paths(tmp_path: Path) -> None:
    """日本語のディレクトリ名とファイル名を含むネストしたファイルを取得できる。"""
    source_path = tmp_path / "案件資料" / "見積" / "回答.txt"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("本文", encoding="utf-8")

    source_files = discover_files(tmp_path)

    assert len(source_files) == 1
    assert source_files[0].path == source_path.resolve()
    assert source_files[0].relative_path == Path("案件資料") / "見積" / "回答.txt"


def test_discover_files_sets_file_metadata(tmp_path: Path) -> None:
    """ファイル名、相対パス、拡張子、サイズ、MIMEタイプを設定できる。"""
    source_path = tmp_path / "資料.TXT"
    source_path.write_text("abc", encoding="utf-8")

    source_file = discover_files(tmp_path)[0]

    assert source_file.name == "資料.TXT"
    assert source_file.relative_path == Path("資料.TXT")
    assert source_file.suffix == ".txt"
    assert source_file.size_bytes == 3
    assert source_file.mime_type == "text/plain"
    assert source_file.modified_at.tzinfo is not None


def test_discover_files_returns_files_sorted_by_relative_path(tmp_path: Path) -> None:
    """ファイルシステムの取得順に依存せず相対パス順で返す。"""
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "c.txt").write_text("c", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")

    source_files = discover_files(tmp_path)

    assert [source_file.relative_path.as_posix() for source_file in source_files] == [
        "a.txt",
        "a/c.txt",
        "b.txt",
    ]


def test_discover_files_excludes_default_technical_directories(tmp_path: Path) -> None:
    """デフォルト除外対象の技術ディレクトリ配下は探索しない。"""
    for directory_name in (
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    ):
        excluded_file = tmp_path / directory_name / "ignored.txt"
        excluded_file.parent.mkdir()
        excluded_file.write_text("ignored", encoding="utf-8")
    included_file = tmp_path / "included.txt"
    included_file.write_text("included", encoding="utf-8")

    source_files = discover_files(tmp_path)

    assert [source_file.relative_path.as_posix() for source_file in source_files] == [
        "included.txt"
    ]


def test_discover_files_does_not_exclude_old_directory(tmp_path: Path) -> None:
    """oldディレクトリは名前だけで除外しない。"""
    source_path = tmp_path / "old" / "archived.txt"
    source_path.parent.mkdir()
    source_path.write_text("archived", encoding="utf-8")

    source_files = discover_files(tmp_path)

    assert [source_file.relative_path.as_posix() for source_file in source_files] == [
        "old/archived.txt"
    ]


def test_discover_files_returns_empty_list_for_empty_directory(tmp_path: Path) -> None:
    """空ディレクトリでは空のリストを返す。"""
    assert discover_files(tmp_path) == []


def test_discover_files_raises_file_not_found_error_for_missing_root(tmp_path: Path) -> None:
    """存在しないルートではFileNotFoundErrorを送出する。"""
    missing_root = tmp_path / "missing"

    with pytest.raises(FileNotFoundError, match="入力ルートが存在しません"):
        discover_files(missing_root)


def test_discover_files_raises_not_a_directory_error_for_file_root(tmp_path: Path) -> None:
    """ファイルをルートとして渡すとNotADirectoryErrorを送出する。"""
    file_root = tmp_path / "file.txt"
    file_root.write_text("content", encoding="utf-8")

    with pytest.raises(NotADirectoryError, match="入力ルートがディレクトリではありません"):
        discover_files(file_root)


def test_discover_files_uses_custom_excluded_dir_names(tmp_path: Path) -> None:
    """独自の除外ディレクトリ名を指定した場合はそのディレクトリを除外する。"""
    excluded_file = tmp_path / "skip" / "ignored.txt"
    excluded_file.parent.mkdir()
    excluded_file.write_text("ignored", encoding="utf-8")
    default_excluded_file = tmp_path / ".git" / "included.txt"
    default_excluded_file.parent.mkdir()
    default_excluded_file.write_text("included", encoding="utf-8")

    source_files = discover_files(tmp_path, excluded_dir_names=frozenset({"skip"}))

    assert [source_file.relative_path.as_posix() for source_file in source_files] == [
        ".git/included.txt"
    ]
