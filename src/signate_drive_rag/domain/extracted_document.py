"""原本ファイルから抽出した内容を表すドメインモデル。"""

from dataclasses import dataclass
from typing import TypeAlias

from signate_drive_rag.domain.source_file import SourceFile

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class ExtractedUnit:
    """原本ファイルから抽出した位置情報付きのデータ。"""

    unit_type: str
    text: str
    locator: str | None
    metadata: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ExtractionIssue:
    """原本ファイルからの抽出時に検出した問題。"""

    issue_type: str
    severity: str
    message: str
    locator: str | None
    metadata: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    """1つの原本ファイルから抽出した文書。"""

    source_file: SourceFile
    parser_name: str
    units: tuple[ExtractedUnit, ...]
    issues: tuple[ExtractionIssue, ...] = ()
