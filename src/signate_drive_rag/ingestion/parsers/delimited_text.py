"""CSV・TSVを表形式の抽出単位へ変換するパーサー。"""

import csv
from typing import ClassVar

from signate_drive_rag.domain.extracted_document import ExtractedDocument, ExtractedUnit, JsonValue
from signate_drive_rag.domain.source_file import SourceFile


class DelimitedTextParser:
    """区切り文字付きテキストを論理行単位で抽出する。"""

    SUPPORTED_SUFFIXES: ClassVar[frozenset[str]] = frozenset({".csv", ".tsv"})
    DELIMITERS_BY_SUFFIX: ClassVar[dict[str, str]] = {
        ".csv": ",",
        ".tsv": "\t",
    }

    @property
    def name(self) -> str:
        """パーサーを識別する名前を返す。"""
        return "delimited_text"

    def supports(self, source_file: SourceFile) -> bool:
        """対象ファイルを処理できるか判定する。"""
        return source_file.suffix.lower() in self.SUPPORTED_SUFFIXES

    def parse(self, source_file: SourceFile) -> ExtractedDocument:
        """CSV・TSVをヘッダーとデータ行へ分解する。"""
        delimiter = self._delimiter_for(source_file)
        units: list[ExtractedUnit] = []

        with source_file.path.open(
            mode="r",
            encoding="utf-8-sig",
            newline="",
        ) as source_stream:
            reader = csv.reader(source_stream, delimiter=delimiter)
            previous_end_line = 0
            headers: list[str] | None = None

            for logical_row_number, row in enumerate(reader, start=1):
                start_line = previous_end_line + 1
                end_line = reader.line_num
                previous_end_line = end_line

                if headers is None:
                    headers = _normalize_headers(row)
                    units.append(
                        _header_unit(
                            raw_headers=row,
                            headers=headers,
                            delimiter=delimiter,
                            logical_row_number=logical_row_number,
                            start_line=start_line,
                            end_line=end_line,
                        )
                    )
                    continue

                units.append(
                    _row_unit(
                        raw_values=row,
                        headers=headers,
                        delimiter=delimiter,
                        logical_row_number=logical_row_number,
                        start_line=start_line,
                        end_line=end_line,
                    )
                )

        return ExtractedDocument(
            source_file=source_file,
            parser_name=self.name,
            units=tuple(units),
        )

    def _delimiter_for(self, source_file: SourceFile) -> str:
        """拡張子から区切り文字を決定する。"""
        suffix = source_file.suffix.lower()
        return self.DELIMITERS_BY_SUFFIX[suffix]


def _normalize_headers(raw_headers: list[str]) -> list[str]:
    """ヘッダー名を決定的な一意名へ正規化する。"""
    normalized_headers: list[str] = []
    used_names: set[str] = set()
    for index, raw_header in enumerate(raw_headers, start=1):
        base_name = raw_header.strip() or f"column_{index}"
        normalized_headers.append(_unique_name(base_name, used_names))
    return normalized_headers


def _effective_headers(headers: list[str], actual_column_count: int) -> list[str]:
    """行幅に合わせて、余剰列にも一意なヘッダー名を付与する。"""
    if actual_column_count <= len(headers):
        return headers

    effective_headers = list(headers)
    used_names = set(effective_headers)
    for index in range(len(headers) + 1, actual_column_count + 1):
        effective_headers.append(_unique_name(f"column_{index}", used_names))
    return effective_headers


def _unique_name(base_name: str, used_names: set[str]) -> str:
    """既存名と衝突しない列名を返す。"""
    candidate = base_name
    serial_number = 2
    while candidate in used_names:
        candidate = f"{base_name}_{serial_number}"
        serial_number += 1
    used_names.add(candidate)
    return candidate


def _header_unit(
    *,
    raw_headers: list[str],
    headers: list[str],
    delimiter: str,
    logical_row_number: int,
    start_line: int,
    end_line: int,
) -> ExtractedUnit:
    """ヘッダー行を抽出単位へ変換する。"""
    return ExtractedUnit(
        unit_type="table_header",
        text=" | ".join(headers),
        locator=f"row:{logical_row_number}",
        metadata={
            "logical_row_number": logical_row_number,
            "start_line": start_line,
            "end_line": end_line,
            "delimiter": delimiter,
            "raw_headers": _json_string_list(raw_headers),
            "headers": _json_string_list(headers),
            "column_count": len(headers),
        },
    )


def _row_unit(
    *,
    raw_values: list[str],
    headers: list[str],
    delimiter: str,
    logical_row_number: int,
    start_line: int,
    end_line: int,
) -> ExtractedUnit:
    """データ行を抽出単位へ変換する。"""
    actual_column_count = len(raw_values)
    expected_column_count = len(headers)
    effective_headers = _effective_headers(headers, actual_column_count)
    values = _fit_values(raw_values, expected_column_count)
    text = " | ".join(
        f"{header}={value}" for header, value in zip(effective_headers, values, strict=True)
    )

    return ExtractedUnit(
        unit_type="table_row",
        text=text,
        locator=f"row:{logical_row_number}",
        metadata={
            "logical_row_number": logical_row_number,
            "start_line": start_line,
            "end_line": end_line,
            "delimiter": delimiter,
            "headers": _json_string_list(effective_headers),
            "values": _json_string_list(values),
            "actual_column_count": actual_column_count,
            "expected_column_count": expected_column_count,
            "width_mismatch": actual_column_count != expected_column_count,
        },
    )


def _fit_values(raw_values: list[str], expected_column_count: int) -> list[str]:
    """不足列だけを空文字で補い、余剰列は保持する。"""
    if len(raw_values) >= expected_column_count:
        return list(raw_values)
    return [*raw_values, *([""] * (expected_column_count - len(raw_values)))]


def _json_string_list(values: list[str]) -> list[JsonValue]:
    """JSON互換型として扱える文字列配列へ変換する。"""
    return list(values)
