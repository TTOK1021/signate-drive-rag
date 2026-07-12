"""Markdownファイルを見出し単位で抽出するパーサー。"""

import re
from dataclasses import dataclass

from signate_drive_rag.domain.extracted_document import ExtractedDocument, ExtractedUnit
from signate_drive_rag.domain.source_file import SourceFile

_ATX_HEADING_PATTERN = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")


@dataclass(frozen=True, slots=True)
class _MarkdownBlock:
    """Markdown抽出単位を組み立てるための内部表現。"""

    start_line: int
    end_line: int
    heading: str | None
    heading_level: int | None
    heading_path: tuple[str, ...]


class MarkdownParser:
    """MarkdownをATX見出し単位で抽出する。"""

    SUPPORTED_SUFFIXES = frozenset({".md"})

    @property
    def name(self) -> str:
        """パーサーを識別する名前を返す。"""
        return "markdown"

    def supports(self, source_file: SourceFile) -> bool:
        """対象ファイルを処理できるか判定する。"""
        return source_file.suffix.lower() in self.SUPPORTED_SUFFIXES

    def parse(self, source_file: SourceFile) -> ExtractedDocument:
        """Markdownを見出し構造と行番号付きで抽出する。"""
        with source_file.path.open("r", encoding="utf-8", newline="") as source_stream:
            raw_text = source_stream.read()

        lines = raw_text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
        if not lines:
            return ExtractedDocument(source_file=source_file, parser_name=self.name, units=())

        blocks = _build_markdown_blocks(lines)
        units = tuple(_block_to_unit(block, lines) for block in blocks)
        return ExtractedDocument(source_file=source_file, parser_name=self.name, units=units)


def _build_markdown_blocks(lines: list[str]) -> list[_MarkdownBlock]:
    """Markdownの本文を重複しない抽出範囲へ分割する。"""
    blocks: list[_MarkdownBlock] = []
    heading_stack: list[tuple[int, str]] = []
    current_block_start = 1
    current_heading: str | None = None
    current_heading_level: int | None = None
    current_heading_path: tuple[str, ...] = ()
    is_in_fence = False

    for line_index, line in enumerate(lines, start=1):
        if line.strip().startswith("```"):
            is_in_fence = not is_in_fence
            continue

        heading_match = None if is_in_fence else _ATX_HEADING_PATTERN.match(line)
        if heading_match is None:
            continue

        if current_block_start <= line_index - 1:
            blocks.append(
                _MarkdownBlock(
                    start_line=current_block_start,
                    end_line=line_index - 1,
                    heading=current_heading,
                    heading_level=current_heading_level,
                    heading_path=current_heading_path,
                )
            )

        heading_level = len(heading_match.group(1))
        heading = heading_match.group(2).strip()
        heading_stack = [
            (stack_level, stack_heading)
            for stack_level, stack_heading in heading_stack
            if stack_level < heading_level
        ]
        heading_stack.append((heading_level, heading))
        current_block_start = line_index
        current_heading = heading
        current_heading_level = heading_level
        current_heading_path = tuple(stack_heading for _level, stack_heading in heading_stack)

    if current_block_start <= len(lines):
        blocks.append(
            _MarkdownBlock(
                start_line=current_block_start,
                end_line=len(lines),
                heading=current_heading,
                heading_level=current_heading_level,
                heading_path=current_heading_path,
            )
        )

    return [
        block
        for block in blocks
        if block.heading is not None or _section_text(lines, block.start_line, block.end_line) != ""
    ]


def _block_to_unit(block: _MarkdownBlock, lines: list[str]) -> ExtractedUnit:
    """内部表現を共通抽出モデルへ変換する。"""
    locator = f"line:{block.start_line}-{block.end_line}"
    return ExtractedUnit(
        unit_type="markdown_section",
        text=_section_text(lines, block.start_line, block.end_line),
        locator=locator,
        metadata={
            "heading": block.heading,
            "heading_level": block.heading_level,
            "heading_path": list(block.heading_path),
            "start_line": block.start_line,
            "end_line": block.end_line,
        },
    )


def _section_text(lines: list[str], start_line: int, end_line: int) -> str:
    """行番号範囲に対応する本文を復元する。"""
    return "\n".join(lines[start_line - 1 : end_line])
