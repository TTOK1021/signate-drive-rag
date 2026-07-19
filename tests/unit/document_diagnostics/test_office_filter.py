"""Office一時ファイル除外のテスト。"""

from pathlib import Path

from signate_drive_rag.document_diagnostics.models import OFFICE_TEMPORARY_FILE_REASON
from signate_drive_rag.document_diagnostics.office_filter import (
    is_office_temporary_file,
    office_temporary_file_reason,
)
from signate_drive_rag.ingestion import discover_files, discover_files_with_ignored


def test_office_filter_detects_supported_temporary_file_names() -> None:
    """Office系拡張子かつファイル名が~$で始まる場合だけ一時ファイルと判定する。"""
    assert is_office_temporary_file(Path("~$資料.docx"))
    assert is_office_temporary_file(Path("~$資料.PPTX"))
    assert is_office_temporary_file(Path("~$資料.xlsm"))


def test_office_filter_does_not_match_non_office_or_parent_directory() -> None:
    """テキストファイルや親ディレクトリ名の~$は除外対象にしない。"""
    assert not is_office_temporary_file(Path("~$memo.txt"))
    assert not is_office_temporary_file(Path("~$tmp") / "資料.docx")
    assert not is_office_temporary_file(Path("資料.docx"))


def test_discover_files_excludes_office_temporary_files_and_records_reason(
    tmp_path: Path,
) -> None:
    """探索時にOffice一時ファイルを通常ファイルから除外し、理由を保持する。"""
    (tmp_path / "~$資料.docx").write_text("lock", encoding="utf-8")
    (tmp_path / "資料.docx").write_text("body", encoding="utf-8")

    source_files = discover_files(tmp_path)
    discovery_result = discover_files_with_ignored(tmp_path)

    assert [source_file.name for source_file in source_files] == ["資料.docx"]
    assert len(discovery_result.ignored_files) == 1
    assert discovery_result.ignored_files[0].reason == OFFICE_TEMPORARY_FILE_REASON
    assert office_temporary_file_reason() == OFFICE_TEMPORARY_FILE_REASON
