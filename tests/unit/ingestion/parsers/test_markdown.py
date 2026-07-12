"""Markdownパーサーの単体テスト。"""

from datetime import UTC, datetime
from pathlib import Path

from signate_drive_rag.domain import SourceFile
from signate_drive_rag.ingestion.parsers import MarkdownParser


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


def test_markdown_parser_supports_md_suffix(tmp_path: Path) -> None:
    """md拡張子のファイルを処理可能と判定する。"""
    file_path = tmp_path / "sample.md"
    file_path.write_text("# title", encoding="utf-8")

    assert MarkdownParser().supports(make_source_file(file_path)) is True


def test_markdown_parser_supports_suffix_case_insensitively(tmp_path: Path) -> None:
    """拡張子の大文字小文字を区別せず処理可能と判定する。"""
    file_path = tmp_path / "sample.MD"
    file_path.write_text("# title", encoding="utf-8")

    assert MarkdownParser().supports(make_source_file(file_path)) is True


def test_markdown_parser_does_not_support_unknown_suffix(tmp_path: Path) -> None:
    """対象外拡張子では処理不可と判定する。"""
    file_path = tmp_path / "sample.txt"
    file_path.write_text("# title", encoding="utf-8")

    assert MarkdownParser().supports(make_source_file(file_path)) is False


def test_markdown_parser_extracts_heading_sections_without_duplicate_text(
    tmp_path: Path,
) -> None:
    """見出しごとに本文を重複なく抽出する。"""
    file_path = tmp_path / "sample.md"
    file_path.write_text(
        "\n".join(
            [
                "# 概要",
                "概要本文",
                "## 契約条件",
                "条件本文",
                "# 補足",
                "補足本文",
            ]
        ),
        encoding="utf-8",
    )

    document = MarkdownParser().parse(make_source_file(file_path))

    assert [unit.text for unit in document.units] == [
        "# 概要\n概要本文",
        "## 契約条件\n条件本文",
        "# 補足\n補足本文",
    ]


def test_markdown_parser_preserves_heading_path(tmp_path: Path) -> None:
    """見出し階層をheading_pathに保持する。"""
    file_path = tmp_path / "sample.md"
    file_path.write_text("# 親\n## 子\n本文", encoding="utf-8")

    document = MarkdownParser().parse(make_source_file(file_path))

    assert document.units[1].metadata["heading_path"] == ["親", "子"]


def test_markdown_parser_keeps_preamble_before_first_heading(tmp_path: Path) -> None:
    """最初の見出しより前の本文を前置き単位として保持する。"""
    file_path = tmp_path / "sample.md"
    file_path.write_text("前置き\n\n# 本文\n内容", encoding="utf-8")

    document = MarkdownParser().parse(make_source_file(file_path))

    assert document.units[0].text == "前置き\n"
    assert document.units[0].metadata["heading"] is None
    assert document.units[0].metadata["heading_path"] == []


def test_markdown_parser_ignores_hash_inside_fenced_code_block(tmp_path: Path) -> None:
    """コードフェンス内の#を見出しとして扱わない。"""
    file_path = tmp_path / "sample.md"
    file_path.write_text("# 本文\n```python\n# コメント\n```\n続き", encoding="utf-8")

    document = MarkdownParser().parse(make_source_file(file_path))

    assert len(document.units) == 1
    assert "# コメント" in document.units[0].text


def test_markdown_parser_preserves_table_and_code_block(tmp_path: Path) -> None:
    """Markdown表とコードブロックの本文を失わず保持する。"""
    file_path = tmp_path / "sample.md"
    markdown_text = "\n".join(
        [
            "# 表",
            "| A | B |",
            "|---|---|",
            "| 1 | 2 |",
            "```",
            "print('hello')",
            "```",
        ]
    )
    file_path.write_text(markdown_text, encoding="utf-8")

    document = MarkdownParser().parse(make_source_file(file_path))

    assert "| 1 | 2 |" in document.units[0].text
    assert "print('hello')" in document.units[0].text


def test_markdown_parser_sets_line_numbers_and_locator(tmp_path: Path) -> None:
    """行番号とlocatorを1始まりで保持する。"""
    file_path = tmp_path / "sample.md"
    file_path.write_text("前置き\n\n# 見出し\n本文\n## 子\n内容", encoding="utf-8")

    document = MarkdownParser().parse(make_source_file(file_path))

    assert document.units[0].locator == "line:1-2"
    assert document.units[1].locator == "line:3-4"
    assert document.units[2].metadata["start_line"] == 5
    assert document.units[2].metadata["end_line"] == 6


def test_markdown_parser_returns_no_units_for_empty_file(tmp_path: Path) -> None:
    """空のMarkdownでは空のunitsを返す。"""
    file_path = tmp_path / "empty.md"
    file_path.write_text("", encoding="utf-8")

    document = MarkdownParser().parse(make_source_file(file_path))

    assert document.units == ()


def test_markdown_parser_handles_japanese_heading_and_body(tmp_path: Path) -> None:
    """日本語の見出しと本文を抽出できる。"""
    file_path = tmp_path / "sample.md"
    file_path.write_text("# 契約条件\n支払期限は月末です。", encoding="utf-8")

    document = MarkdownParser().parse(make_source_file(file_path))

    assert document.units[0].metadata["heading"] == "契約条件"
    assert "支払期限" in document.units[0].text


def test_markdown_parser_keeps_front_matter_as_preamble(tmp_path: Path) -> None:
    """YAML Front Matterを前置き本文として保持する。"""
    file_path = tmp_path / "sample.md"
    file_path.write_text("---\ntitle: Sample\n---\n# 本文\n内容", encoding="utf-8")

    document = MarkdownParser().parse(make_source_file(file_path))

    assert document.units[0].text == "---\ntitle: Sample\n---"
    assert document.units[0].metadata["heading"] is None
