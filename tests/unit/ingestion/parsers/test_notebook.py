"""Notebookパーサーの単体テスト。"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from signate_drive_rag.domain import SourceFile
from signate_drive_rag.ingestion.parsers import NotebookFormatError, NotebookParser


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


def write_notebook(path: Path, cells: list[dict[str, object]]) -> None:
    """テスト用NotebookをUTF-8 JSONとして書き込む。"""
    notebook = {
        "cells": cells,
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path.write_text(json.dumps(notebook, ensure_ascii=False), encoding="utf-8")


def test_notebook_parser_supports_ipynb_suffix(tmp_path: Path) -> None:
    """ipynb拡張子のファイルを処理可能と判定する。"""
    file_path = tmp_path / "sample.ipynb"
    write_notebook(file_path, [])

    assert NotebookParser().supports(make_source_file(file_path)) is True


def test_notebook_parser_extracts_markdown_cell(tmp_path: Path) -> None:
    """Markdownセルを抽出できる。"""
    file_path = tmp_path / "sample.ipynb"
    write_notebook(file_path, [{"cell_type": "markdown", "source": "# Title"}])

    document = NotebookParser().parse(make_source_file(file_path))

    assert document.units[0].unit_type == "notebook_cell"
    assert document.units[0].text == "# Title"
    assert document.units[0].metadata["cell_type"] == "markdown"


def test_notebook_parser_extracts_code_cell(tmp_path: Path) -> None:
    """コードセルを抽出できる。"""
    file_path = tmp_path / "sample.ipynb"
    write_notebook(
        file_path,
        [{"cell_type": "code", "source": "print(1)", "execution_count": 7}],
    )

    document = NotebookParser().parse(make_source_file(file_path))

    assert document.units[0].text == "print(1)"
    assert document.units[0].metadata["cell_type"] == "code"


def test_notebook_parser_extracts_raw_cell(tmp_path: Path) -> None:
    """rawセルを抽出できる。"""
    file_path = tmp_path / "sample.ipynb"
    write_notebook(file_path, [{"cell_type": "raw", "source": "raw text"}])

    document = NotebookParser().parse(make_source_file(file_path))

    assert document.units[0].text == "raw text"
    assert document.units[0].metadata["cell_type"] == "raw"


def test_notebook_parser_joins_source_lines(tmp_path: Path) -> None:
    """文字列配列形式のsourceを順番どおり連結する。"""
    file_path = tmp_path / "sample.ipynb"
    write_notebook(file_path, [{"cell_type": "markdown", "source": ["a\n", "b"]}])

    document = NotebookParser().parse(make_source_file(file_path))

    assert document.units[0].text == "a\nb"


def test_notebook_parser_keeps_empty_cell(tmp_path: Path) -> None:
    """空セルもNotebook構造として保持する。"""
    file_path = tmp_path / "sample.ipynb"
    write_notebook(file_path, [{"cell_type": "markdown", "source": ""}])

    document = NotebookParser().parse(make_source_file(file_path))

    assert document.units[0].text == ""


def test_notebook_parser_preserves_execution_count(tmp_path: Path) -> None:
    """コードセルのexecution_countを保持する。"""
    file_path = tmp_path / "sample.ipynb"
    write_notebook(
        file_path,
        [{"cell_type": "code", "source": "x = 1", "execution_count": 3}],
    )

    document = NotebookParser().parse(make_source_file(file_path))

    assert document.units[0].metadata["execution_count"] == 3


def test_notebook_parser_extracts_stream_output(tmp_path: Path) -> None:
    """stream出力のtextを抽出できる。"""
    file_path = tmp_path / "sample.ipynb"
    write_notebook(
        file_path,
        [
            {
                "cell_type": "code",
                "source": "print('hi')",
                "outputs": [{"output_type": "stream", "name": "stdout", "text": "hi\n"}],
            }
        ],
    )

    document = NotebookParser().parse(make_source_file(file_path))

    assert document.units[1].text == "hi\n"
    assert document.units[1].metadata["stream_name"] == "stdout"


def test_notebook_parser_extracts_execute_result_text_plain(tmp_path: Path) -> None:
    """execute_resultのtext/plainを抽出できる。"""
    file_path = tmp_path / "sample.ipynb"
    write_notebook(
        file_path,
        [
            {
                "cell_type": "code",
                "source": "1",
                "outputs": [{"output_type": "execute_result", "data": {"text/plain": "1"}}],
            }
        ],
    )

    document = NotebookParser().parse(make_source_file(file_path))

    assert document.units[1].text == "1"
    assert document.units[1].metadata["mime_type"] == "text/plain"


def test_notebook_parser_extracts_one_display_data_by_mime_priority(tmp_path: Path) -> None:
    """display_dataでは優先MIMEタイプを1つだけ抽出する。"""
    file_path = tmp_path / "sample.ipynb"
    write_notebook(
        file_path,
        [
            {
                "cell_type": "code",
                "source": "display(value)",
                "outputs": [
                    {
                        "output_type": "display_data",
                        "data": {
                            "text/markdown": "**value**",
                            "text/plain": "value",
                        },
                    }
                ],
            }
        ],
    )

    document = NotebookParser().parse(make_source_file(file_path))

    assert len(document.units) == 2
    assert document.units[1].text == "value"
    assert document.units[1].metadata["mime_type"] == "text/plain"


def test_notebook_parser_serializes_application_json_with_japanese_text(
    tmp_path: Path,
) -> None:
    """application/json出力を日本語を保って文字列化する。"""
    file_path = tmp_path / "sample.ipynb"
    write_notebook(
        file_path,
        [
            {
                "cell_type": "code",
                "source": "data",
                "outputs": [
                    {
                        "output_type": "display_data",
                        "data": {"application/json": {"message": "こんにちは"}},
                    }
                ],
            }
        ],
    )

    document = NotebookParser().parse(make_source_file(file_path))

    assert document.units[1].text == '{"message": "こんにちは"}'


def test_notebook_parser_extracts_error_output(tmp_path: Path) -> None:
    """error出力をename、evalue、tracebackから抽出できる。"""
    file_path = tmp_path / "sample.ipynb"
    write_notebook(
        file_path,
        [
            {
                "cell_type": "code",
                "source": "raise ValueError()",
                "outputs": [
                    {
                        "output_type": "error",
                        "ename": "ValueError",
                        "evalue": "invalid value",
                        "traceback": ["Traceback line"],
                    }
                ],
            }
        ],
    )

    document = NotebookParser().parse(make_source_file(file_path))

    assert document.units[1].text == "ValueError: invalid value\nTraceback line"


def test_notebook_parser_strips_ansi_escape_from_error_output(tmp_path: Path) -> None:
    """error出力からANSIエスケープシーケンスを除去する。"""
    file_path = tmp_path / "sample.ipynb"
    write_notebook(
        file_path,
        [
            {
                "cell_type": "code",
                "source": "raise ValueError()",
                "outputs": [
                    {
                        "output_type": "error",
                        "ename": "ValueError",
                        "evalue": "\u001b[31minvalid\u001b[0m",
                        "traceback": ["\u001b[32mTraceback\u001b[0m"],
                    }
                ],
            }
        ],
    )

    document = NotebookParser().parse(make_source_file(file_path))

    assert "\u001b[" not in document.units[1].text
    assert document.units[1].text == "ValueError: invalid\nTraceback"


def test_notebook_parser_skips_image_only_output(tmp_path: Path) -> None:
    """画像だけの出力は抽出しない。"""
    file_path = tmp_path / "sample.ipynb"
    write_notebook(
        file_path,
        [
            {
                "cell_type": "code",
                "source": "plot()",
                "outputs": [
                    {
                        "output_type": "display_data",
                        "data": {"image/png": "encoded"},
                    }
                ],
            }
        ],
    )

    document = NotebookParser().parse(make_source_file(file_path))

    assert len(document.units) == 1


@pytest.mark.parametrize(
    "notebook_value",
    [
        [],
        {},
        {"cells": {}},
        {"cells": [None]},
        {"cells": [{"cell_type": "html", "source": ""}]},
        {"cells": [{"cell_type": "markdown", "source": {"bad": "value"}}]},
    ],
)
def test_notebook_parser_raises_for_invalid_notebook_structure(
    tmp_path: Path,
    notebook_value: object,
) -> None:
    """不正なNotebook構造では明確な例外を送出する。"""
    file_path = tmp_path / "invalid.ipynb"
    file_path.write_text(json.dumps(notebook_value), encoding="utf-8")

    with pytest.raises(NotebookFormatError):
        NotebookParser().parse(make_source_file(file_path))


def test_notebook_parser_sets_cell_and_output_locators(tmp_path: Path) -> None:
    """セルと出力のlocatorを0始まりインデックスで保持する。"""
    file_path = tmp_path / "sample.ipynb"
    write_notebook(
        file_path,
        [
            {"cell_type": "markdown", "source": "first"},
            {
                "cell_type": "code",
                "source": "print('second')",
                "outputs": [{"output_type": "stream", "name": "stdout", "text": "second"}],
            },
        ],
    )

    document = NotebookParser().parse(make_source_file(file_path))

    assert [unit.locator for unit in document.units] == ["cell:0", "cell:1", "cell:1/output:0"]
