"""Jupyter Notebookをセルとテキスト出力単位で抽出するパーサー。"""

import json
import re
from typing import Any

from signate_drive_rag.domain.extracted_document import ExtractedDocument, ExtractedUnit
from signate_drive_rag.domain.source_file import SourceFile

_ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_DISPLAY_MIME_PRIORITY = ("text/plain", "text/markdown", "application/json")


class NotebookFormatError(ValueError):
    """Notebookとして期待する構造ではない場合の例外。"""


class NotebookParser:
    """Jupyter Notebookのセル本文とテキスト出力を抽出する。"""

    SUPPORTED_SUFFIXES = frozenset({".ipynb"})
    SUPPORTED_CELL_TYPES = frozenset({"markdown", "code", "raw"})

    @property
    def name(self) -> str:
        """パーサーを識別する名前を返す。"""
        return "notebook"

    def supports(self, source_file: SourceFile) -> bool:
        """対象ファイルを処理できるか判定する。"""
        return source_file.suffix.lower() in self.SUPPORTED_SUFFIXES

    def parse(self, source_file: SourceFile) -> ExtractedDocument:
        """Notebookをセル単位と出力単位へ分解する。"""
        with source_file.path.open("r", encoding="utf-8") as source_stream:
            notebook = json.load(source_stream)

        if not isinstance(notebook, dict):
            raise NotebookFormatError("Notebookのルートはオブジェクトである必要があります。")
        cells = notebook.get("cells")
        if cells is None:
            raise NotebookFormatError("Notebookにcellsが存在しません。")
        if not isinstance(cells, list):
            raise NotebookFormatError("Notebookのcellsは配列である必要があります。")

        units: list[ExtractedUnit] = []
        for cell_index, cell in enumerate(cells):
            units.extend(_extract_cell_units(cell, cell_index))

        return ExtractedDocument(source_file=source_file, parser_name=self.name, units=tuple(units))


def _extract_cell_units(cell: Any, cell_index: int) -> list[ExtractedUnit]:
    """セル本文とコードセル出力を抽出する。"""
    if not isinstance(cell, dict):
        raise NotebookFormatError(f"セルはオブジェクトである必要があります: cell:{cell_index}")

    cell_type = cell.get("cell_type")
    if cell_type not in NotebookParser.SUPPORTED_CELL_TYPES:
        raise NotebookFormatError(f"未対応のcell_typeです: cell:{cell_index}")

    source = _source_to_text(cell.get("source"), f"cell:{cell_index}/source")
    execution_count = cell.get("execution_count") if cell_type == "code" else None
    units = [
        ExtractedUnit(
            unit_type="notebook_cell",
            text=source,
            locator=f"cell:{cell_index}",
            metadata={
                "cell_index": cell_index,
                "cell_type": cell_type,
                "execution_count": execution_count,
            },
        )
    ]

    if cell_type == "code":
        outputs = cell.get("outputs", [])
        if outputs is None:
            outputs = []
        if not isinstance(outputs, list):
            raise NotebookFormatError(f"outputsは配列である必要があります: cell:{cell_index}")
        for output_index, output in enumerate(outputs):
            output_unit = _extract_output_unit(output, cell_index, output_index)
            if output_unit is not None:
                units.append(output_unit)

    return units


def _extract_output_unit(
    output: Any,
    cell_index: int,
    output_index: int,
) -> ExtractedUnit | None:
    """Notebook出力からテキスト化できるものだけを抽出する。"""
    if not isinstance(output, dict):
        raise NotebookFormatError(
            f"outputはオブジェクトである必要があります: cell:{cell_index}/output:{output_index}"
        )

    output_type = output.get("output_type")
    locator = f"cell:{cell_index}/output:{output_index}"
    metadata = {
        "cell_index": cell_index,
        "output_index": output_index,
        "output_type": output_type,
    }

    if output_type == "stream":
        text = _source_to_text(output.get("text", ""), f"{locator}/text")
        metadata["stream_name"] = output.get("name")
        return ExtractedUnit(
            unit_type="notebook_output",
            text=text,
            locator=locator,
            metadata=metadata,
        )

    if output_type in {"execute_result", "display_data"}:
        text_and_mime = _extract_display_text(output.get("data"))
        if text_and_mime is None:
            return None
        text, mime_type = text_and_mime
        metadata["mime_type"] = mime_type
        return ExtractedUnit(
            unit_type="notebook_output",
            text=text,
            locator=locator,
            metadata=metadata,
        )

    if output_type == "error":
        return ExtractedUnit(
            unit_type="notebook_output",
            text=_error_output_to_text(output),
            locator=locator,
            metadata=metadata,
        )

    return None


def _extract_display_text(data: Any) -> tuple[str, str] | None:
    """表示データから優先順に1つだけテキスト表現を取得する。"""
    if not isinstance(data, dict):
        return None
    for mime_type in _DISPLAY_MIME_PRIORITY:
        if mime_type not in data:
            continue
        mime_value = data[mime_type]
        if mime_type == "application/json":
            return json.dumps(mime_value, ensure_ascii=False), mime_type
        return _source_to_text(mime_value, mime_type), mime_type
    return None


def _error_output_to_text(output: dict[str, Any]) -> str:
    """エラー出力をANSI制御文字なしのテキストへ変換する。"""
    ename = output.get("ename")
    evalue = output.get("evalue")
    traceback_text = _source_to_text(output.get("traceback", []), "traceback")

    lines: list[str] = []
    if isinstance(ename, str) and isinstance(evalue, str):
        lines.append(f"{ename}: {evalue}")
    elif isinstance(ename, str):
        lines.append(ename)
    elif isinstance(evalue, str):
        lines.append(evalue)
    if traceback_text:
        lines.append(traceback_text)
    return _strip_ansi_escape("\n".join(lines))


def _source_to_text(source: Any, location: str) -> str:
    """Notebookが許容する文字列または文字列配列をテキスト化する。"""
    if isinstance(source, str):
        return source
    if isinstance(source, list) and all(isinstance(item, str) for item in source):
        return "".join(source)
    raise NotebookFormatError(f"文字列または文字列配列が必要です: {location}")


def _strip_ansi_escape(text: str) -> str:
    """ANSIエスケープシーケンスを除去する。"""
    return _ANSI_ESCAPE_PATTERN.sub("", text)
