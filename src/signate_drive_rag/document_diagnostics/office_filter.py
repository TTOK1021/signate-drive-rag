"""Office一時ファイルを通常資料から除外する判定。"""

from pathlib import Path

from signate_drive_rag.document_diagnostics.models import OFFICE_TEMPORARY_FILE_REASON

OFFICE_TEMPORARY_SUFFIXES = frozenset({".docx", ".pptx", ".xlsx", ".xlsm", ".doc", ".ppt", ".xls"})


def is_office_temporary_file(path: Path) -> bool:
    """Officeが生成するロック・一時ファイルか判定する。"""
    return path.name.startswith("~$") and path.suffix.lower() in OFFICE_TEMPORARY_SUFFIXES


def office_temporary_file_reason() -> str:
    """除外理由名を一箇所で共有する。"""
    return OFFICE_TEMPORARY_FILE_REASON
