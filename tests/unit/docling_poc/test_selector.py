"""Docling PoCのサンプル選択テスト。"""

from datetime import UTC, datetime
from pathlib import Path

from signate_drive_rag.docling_poc.selector import (
    group_candidates_by_suffix,
    select_representative_documents,
)
from signate_drive_rag.domain import SourceFile


def make_source_file(relative_path: str, size_bytes: int) -> SourceFile:
    """テスト用SourceFileを作成する。"""
    root = Path("root").resolve()
    path = root / relative_path
    return SourceFile(
        path=path,
        relative_path=Path(relative_path),
        name=path.name,
        suffix=path.suffix.lower(),
        mime_type=None,
        size_bytes=size_bytes,
        modified_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_group_candidates_by_suffix_filters_and_sorts_files() -> None:
    """形式ごとに候補を分け、サイズと相対パス順で並ぶことを確認する。"""
    source_files = [
        make_source_file("b/資料.docx", 20),
        make_source_file("a/資料.docx", 20),
        make_source_file("c/表.xlsx", 10),
        make_source_file("d/対象外.txt", 1),
    ]

    grouped = group_candidates_by_suffix(source_files, frozenset({".docx", ".xlsx"}))

    assert [file.relative_path.as_posix() for file in grouped[".docx"]] == [
        "a/資料.docx",
        "b/資料.docx",
    ]
    assert [file.relative_path.as_posix() for file in grouped[".xlsx"]] == ["c/表.xlsx"]
    assert ".txt" not in grouped


def test_select_representative_documents_uses_five_quantiles_without_duplicates() -> None:
    """5件指定では最小・四分位・中央値・四分位・最大付近を重複なく選ぶ。"""
    source_files = [
        make_source_file(f"docs/file_{index}.pdf", size_bytes=index) for index in range(1, 10)
    ]

    selections = select_representative_documents(
        source_files,
        samples_per_format=5,
        formats=frozenset({".pdf"}),
    )

    assert [selection.size_bytes for selection in selections] == [1, 3, 5, 7, 9]
    assert len({selection.sample_id for selection in selections}) == 5
    assert [selection.selection_quantile for selection in selections] == [
        0.0,
        0.25,
        0.5,
        0.75,
        1.0,
    ]


def test_select_representative_documents_handles_three_one_and_small_candidates() -> None:
    """3件・1件・候補不足で要求どおりの位置を選ぶことを確認する。"""
    source_files = [
        make_source_file(f"slides/file_{index}.pptx", size_bytes=index) for index in range(1, 6)
    ]

    three = select_representative_documents(
        source_files,
        samples_per_format=3,
        formats=frozenset({".pptx"}),
    )
    one = select_representative_documents(
        source_files,
        samples_per_format=1,
        formats=frozenset({".pptx"}),
    )
    all_candidates = select_representative_documents(
        source_files[:2],
        samples_per_format=5,
        formats=frozenset({".pptx"}),
    )

    assert [selection.size_bytes for selection in three] == [1, 3, 5]
    assert [selection.size_bytes for selection in one] == [3]
    assert [selection.size_bytes for selection in all_candidates] == [1, 2]


def test_select_representative_documents_is_deterministic_and_keeps_japanese_paths() -> None:
    """同じ入力から同じ選択と日本語相対パスを得られることを確認する。"""
    source_files = [
        make_source_file("共有/あ.pdf", 100),
        make_source_file("共有/い.pdf", 200),
        make_source_file("共有/う.pdf", 300),
    ]

    first = select_representative_documents(
        source_files,
        samples_per_format=3,
        formats=frozenset({".pdf"}),
    )
    second = select_representative_documents(
        list(reversed(source_files)),
        samples_per_format=3,
        formats=frozenset({".pdf"}),
    )

    assert first == second
    assert first[0].relative_path == "共有/あ.pdf"
    assert all(len(selection.sample_id) == 64 for selection in first)
    assert all(set(selection.sample_id) <= set("0123456789abcdef") for selection in first)


def test_select_representative_documents_sample_id_does_not_depend_on_absolute_path() -> None:
    """sample_idが絶対パスへ依存しないことを確認する。"""
    first = make_source_file("same/file.pdf", 10)
    second = SourceFile(
        path=Path("another/root/same/file.pdf").resolve(),
        relative_path=Path("same/file.pdf"),
        name="file.pdf",
        suffix=".pdf",
        mime_type=None,
        size_bytes=10,
        modified_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    first_selection = select_representative_documents(
        [first],
        samples_per_format=1,
        formats=frozenset({".pdf"}),
    )[0]
    second_selection = select_representative_documents(
        [second],
        samples_per_format=1,
        formats=frozenset({".pdf"}),
    )[0]

    assert first_selection.sample_id == second_selection.sample_id
