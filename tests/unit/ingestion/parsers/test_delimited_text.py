"""区切り文字付きテキストパーサーの単体テスト。"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from signate_drive_rag.domain import SourceFile
from signate_drive_rag.ingestion.parsers import DelimitedTextParser


def make_source_file(path: Path) -> SourceFile:
    """テスト用のSourceFileを作成する。"""
    stat_result = path.stat()
    return SourceFile(
        path=path,
        relative_path=Path(path.name),
        name=path.name,
        suffix=path.suffix,
        mime_type=None,
        size_bytes=stat_result.st_size,
        modified_at=datetime.fromtimestamp(stat_result.st_mtime, tz=UTC),
    )


@pytest.mark.parametrize("suffix", [".csv", ".tsv"])
def test_delimited_text_parser_supports_delimited_suffixes(
    tmp_path: Path,
    suffix: str,
) -> None:
    """CSVとTSVを処理可能と判定する。"""
    file_path = tmp_path / f"sample{suffix}"
    file_path.write_text("a,b\n1,2", encoding="utf-8")

    assert DelimitedTextParser().supports(make_source_file(file_path)) is True


def test_delimited_text_parser_supports_suffix_case_insensitively(tmp_path: Path) -> None:
    """拡張子の大文字小文字を区別せず処理可能と判定する。"""
    file_path = tmp_path / "sample.CSV"
    file_path.write_text("a,b\n1,2", encoding="utf-8")

    assert DelimitedTextParser().supports(make_source_file(file_path)) is True


def test_delimited_text_parser_does_not_support_unknown_suffix(tmp_path: Path) -> None:
    """対象外拡張子では処理不可と判定する。"""
    file_path = tmp_path / "sample.txt"
    file_path.write_text("a,b\n1,2", encoding="utf-8")

    assert DelimitedTextParser().supports(make_source_file(file_path)) is False


def test_delimited_text_parser_extracts_japanese_utf8_csv(tmp_path: Path) -> None:
    """日本語のUTF-8 CSVをヘッダーとデータ行として抽出する。"""
    file_path = tmp_path / "sample.csv"
    file_path.write_text("顧客名,状態\nサンプル株式会社,承認済み\n", encoding="utf-8")

    document = DelimitedTextParser().parse(make_source_file(file_path))

    assert document.parser_name == "delimited_text"
    assert document.source_file == make_source_file(file_path)
    assert len(document.units) == 2
    assert document.units[0].unit_type == "table_header"
    assert document.units[0].text == "顧客名 | 状態"
    assert document.units[0].locator == "row:1"
    assert document.units[0].metadata["raw_headers"] == ["顧客名", "状態"]
    assert document.units[0].metadata["headers"] == ["顧客名", "状態"]
    assert document.units[1].unit_type == "table_row"
    assert document.units[1].text == "顧客名=サンプル株式会社 | 状態=承認済み"
    assert document.units[1].metadata["values"] == ["サンプル株式会社", "承認済み"]


def test_delimited_text_parser_extracts_utf8_bom_csv(tmp_path: Path) -> None:
    """UTF-8 BOM付きCSVをBOMなしのヘッダーとして抽出する。"""
    file_path = tmp_path / "sample.csv"
    file_path.write_text("顧客名,状態\n山田,対応中", encoding="utf-8-sig")

    document = DelimitedTextParser().parse(make_source_file(file_path))

    assert document.units[0].metadata["headers"] == ["顧客名", "状態"]


def test_delimited_text_parser_uses_tab_delimiter_for_tsv(tmp_path: Path) -> None:
    """TSVのタブ区切りを列として扱う。"""
    file_path = tmp_path / "sample.tsv"
    file_path.write_text("顧客名\t状態\n山田\t対応中", encoding="utf-8")

    document = DelimitedTextParser().parse(make_source_file(file_path))

    assert document.units[0].metadata["delimiter"] == "\t"
    assert document.units[1].text == "顧客名=山田 | 状態=対応中"


def test_delimited_text_parser_keeps_quoted_comma_as_one_cell(tmp_path: Path) -> None:
    """引用符内のカンマを1セルとして扱う。"""
    file_path = tmp_path / "sample.csv"
    file_path.write_text(
        '顧客名,備考\nサンプル株式会社,"京都、大阪、東京で事業を展開"',
        encoding="utf-8",
    )

    document = DelimitedTextParser().parse(make_source_file(file_path))

    assert document.units[1].metadata["values"] == [
        "サンプル株式会社",
        "京都、大阪、東京で事業を展開",
    ]


def test_delimited_text_parser_keeps_quoted_tab_as_one_tsv_cell(tmp_path: Path) -> None:
    """引用符内のタブをTSVの1セルとして扱う。"""
    file_path = tmp_path / "sample.tsv"
    file_path.write_text('顧客名\t備考\nサンプル株式会社\t"京都\t大阪"', encoding="utf-8")

    document = DelimitedTextParser().parse(make_source_file(file_path))

    assert document.units[1].metadata["values"] == ["サンプル株式会社", "京都\t大阪"]


def test_delimited_text_parser_tracks_physical_lines_for_multiline_cell(
    tmp_path: Path,
) -> None:
    """セル内改行を1つの論理行として扱い、物理行範囲を保持する。"""
    file_path = tmp_path / "sample.csv"
    file_path.write_bytes('顧客名,備考\nサンプル株式会社,"1行目\n2行目"'.encode())

    document = DelimitedTextParser().parse(make_source_file(file_path))

    data_unit = document.units[1]
    assert data_unit.locator == "row:2"
    assert data_unit.metadata["logical_row_number"] == 2
    assert data_unit.metadata["start_line"] == 2
    assert data_unit.metadata["end_line"] == 3
    assert data_unit.metadata["values"] == ["サンプル株式会社", "1行目\n2行目"]


def test_delimited_text_parser_preserves_empty_cells(tmp_path: Path) -> None:
    """空セルを空文字列として保持する。"""
    file_path = tmp_path / "sample.csv"
    file_path.write_text("A,B,C\n1,,3", encoding="utf-8")

    document = DelimitedTextParser().parse(make_source_file(file_path))

    assert document.units[1].text == "A=1 | B= | C=3"
    assert document.units[1].metadata["values"] == ["1", "", "3"]


def test_delimited_text_parser_returns_no_units_for_empty_file(tmp_path: Path) -> None:
    """空ファイルでは空のunitsを返す。"""
    file_path = tmp_path / "empty.csv"
    file_path.write_text("", encoding="utf-8")

    document = DelimitedTextParser().parse(make_source_file(file_path))

    assert document.units == ()


def test_delimited_text_parser_handles_header_only_file(tmp_path: Path) -> None:
    """ヘッダーだけのファイルをヘッダー単位1件として抽出する。"""
    file_path = tmp_path / "sample.csv"
    file_path.write_text("A,B,C\n", encoding="utf-8")

    document = DelimitedTextParser().parse(make_source_file(file_path))

    assert len(document.units) == 1
    assert document.units[0].unit_type == "table_header"


def test_delimited_text_parser_keeps_empty_line_as_data_row(tmp_path: Path) -> None:
    """空行を位置情報付きのデータ行として保持する。"""
    file_path = tmp_path / "sample.csv"
    file_path.write_text("A,B\n\n1,2", encoding="utf-8")

    document = DelimitedTextParser().parse(make_source_file(file_path))

    empty_row = document.units[1]
    assert empty_row.locator == "row:2"
    assert empty_row.metadata["start_line"] == 2
    assert empty_row.metadata["end_line"] == 2
    assert empty_row.metadata["values"] == ["", ""]
    assert empty_row.metadata["actual_column_count"] == 0
    assert empty_row.metadata["expected_column_count"] == 2
    assert empty_row.metadata["width_mismatch"] is True


def test_delimited_text_parser_normalizes_empty_and_duplicate_headers(
    tmp_path: Path,
) -> None:
    """空ヘッダーと重複ヘッダーを一意な列名へ正規化する。"""
    file_path = tmp_path / "sample.csv"
    file_path.write_text("名前,,名前,column_2\nA,B,C,D", encoding="utf-8")

    document = DelimitedTextParser().parse(make_source_file(file_path))

    assert document.units[0].metadata["raw_headers"] == ["名前", "", "名前", "column_2"]
    assert document.units[0].metadata["headers"] == [
        "名前",
        "column_2",
        "名前_2",
        "column_2_2",
    ]
    assert document.units[1].text == "名前=A | column_2=B | 名前_2=C | column_2_2=D"


def test_delimited_text_parser_pads_missing_columns(tmp_path: Path) -> None:
    """列数が不足した行を空文字列で補完する。"""
    file_path = tmp_path / "sample.csv"
    file_path.write_text("A,B,C\n1,2", encoding="utf-8")

    document = DelimitedTextParser().parse(make_source_file(file_path))

    row = document.units[1]
    assert row.metadata["values"] == ["1", "2", ""]
    assert row.metadata["actual_column_count"] == 2
    assert row.metadata["expected_column_count"] == 3
    assert row.metadata["width_mismatch"] is True
    assert row.text == "A=1 | B=2 | C="


def test_delimited_text_parser_keeps_extra_columns_with_generated_headers(
    tmp_path: Path,
) -> None:
    """列数が多い行の余分な値を失わず一意な列名を付ける。"""
    file_path = tmp_path / "sample.csv"
    file_path.write_text("A,column_3\n1,2,3,4", encoding="utf-8")

    document = DelimitedTextParser().parse(make_source_file(file_path))

    row = document.units[1]
    assert row.metadata["headers"] == ["A", "column_3", "column_3_2", "column_4"]
    assert row.metadata["values"] == ["1", "2", "3", "4"]
    assert row.metadata["actual_column_count"] == 4
    assert row.metadata["expected_column_count"] == 2
    assert row.metadata["width_mismatch"] is True
    assert row.text == "A=1 | column_3=2 | column_3_2=3 | column_4=4"


def test_delimited_text_parser_sets_logical_row_locator(tmp_path: Path) -> None:
    """locatorに論理行番号を保持する。"""
    file_path = tmp_path / "sample.csv"
    file_path.write_text("A\n1\n2", encoding="utf-8")

    document = DelimitedTextParser().parse(make_source_file(file_path))

    assert [unit.locator for unit in document.units] == ["row:1", "row:2", "row:3"]


def test_delimited_text_parser_raises_decode_error_for_invalid_utf8(tmp_path: Path) -> None:
    """UTF-8として不正なファイルでは読み込みエラーを送出する。"""
    file_path = tmp_path / "invalid.csv"
    file_path.write_bytes(b"\xff\xfe")

    with pytest.raises(UnicodeDecodeError):
        DelimitedTextParser().parse(make_source_file(file_path))
