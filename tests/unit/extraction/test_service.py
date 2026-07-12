"""ExtractionServiceの単体テスト。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from signate_drive_rag.domain import ExtractedDocument, ExtractedUnit, SourceFile
from signate_drive_rag.extraction import ExtractionService
from signate_drive_rag.ingestion.parser_registry import ParserRegistry


def make_source_file(path: Path, root: Path) -> SourceFile:
    """テスト用のSourceFileを作成する。"""
    stat_result = path.stat()
    return SourceFile(
        path=path,
        relative_path=path.relative_to(root),
        name=path.name,
        suffix=path.suffix.lower(),
        mime_type=None,
        size_bytes=stat_result.st_size,
        modified_at=datetime.fromtimestamp(stat_result.st_mtime, tz=UTC),
    )


@dataclass(frozen=True, slots=True)
class FakeParser:
    """抽出サービスの分類を確認するための偽パーサー。"""

    name: str
    suffix: str
    should_fail: bool = False

    def supports(self, source_file: SourceFile) -> bool:
        """対象ファイルを処理できるか判定する。"""
        return source_file.suffix == self.suffix

    def parse(self, source_file: SourceFile) -> ExtractedDocument:
        """固定の抽出結果または例外を返す。"""
        if self.should_fail:
            raise ValueError(f"broken: {source_file.name}")
        text = source_file.path.read_text(encoding="utf-8")
        return ExtractedDocument(
            source_file=source_file,
            parser_name=self.name,
            units=(
                ExtractedUnit(
                    unit_type="text",
                    text=text,
                    locator=None,
                    metadata={"line_count": 1},
                ),
            ),
        )


def test_extraction_service_extracts_supported_files_and_sorts_results(tmp_path: Path) -> None:
    """対応ファイルを複数抽出し、documentsを相対パス順に並べる。"""
    paths = [tmp_path / "b.ok", tmp_path / "a.ok"]
    for path in paths:
        path.write_text(path.stem, encoding="utf-8")
    source_files = [make_source_file(path, tmp_path) for path in paths]
    registry = ParserRegistry()
    registry.register(FakeParser(name="ok", suffix=".ok"))

    result = ExtractionService(registry).extract(source_files)

    assert [document.source_file.relative_path.as_posix() for document in result.documents] == [
        "a.ok",
        "b.ok",
    ]
    assert result.summary.succeeded_files == 2


def test_extraction_service_classifies_unsupported_files(tmp_path: Path) -> None:
    """対応パーサーが存在しないファイルをunsupportedへ分類する。"""
    path = tmp_path / "report.pdf"
    path.write_text("pdf", encoding="utf-8")

    result = ExtractionService(ParserRegistry()).extract([make_source_file(path, tmp_path)])

    assert result.documents == ()
    assert result.failures == ()
    assert result.unsupported_files[0].relative_path.as_posix() == "report.pdf"


def test_extraction_service_continues_after_parse_failure(tmp_path: Path) -> None:
    """1ファイルの抽出失敗後も残りの処理を継続する。"""
    broken_path = tmp_path / "broken.bad"
    valid_path = tmp_path / "valid.ok"
    broken_path.write_text("broken", encoding="utf-8")
    valid_path.write_text("valid", encoding="utf-8")
    registry = ParserRegistry()
    registry.register(FakeParser(name="bad", suffix=".bad", should_fail=True))
    registry.register(FakeParser(name="ok", suffix=".ok"))

    result = ExtractionService(registry).extract(
        [make_source_file(broken_path, tmp_path), make_source_file(valid_path, tmp_path)]
    )

    assert len(result.documents) == 1
    assert len(result.failures) == 1
    assert result.failures[0].error_type == "ValueError"
    assert result.summary.succeeded_files == 1


def test_extraction_service_distinguishes_unsupported_and_failed(tmp_path: Path) -> None:
    """パーサー取得失敗と抽出失敗を別分類にする。"""
    unsupported_path = tmp_path / "unknown.bin"
    failed_path = tmp_path / "broken.bad"
    unsupported_path.write_text("unknown", encoding="utf-8")
    failed_path.write_text("broken", encoding="utf-8")
    registry = ParserRegistry()
    registry.register(FakeParser(name="bad", suffix=".bad", should_fail=True))

    result = ExtractionService(registry).extract(
        [make_source_file(unsupported_path, tmp_path), make_source_file(failed_path, tmp_path)]
    )

    assert len(result.unsupported_files) == 1
    assert len(result.failures) == 1


def test_extraction_service_builds_consistent_summary(tmp_path: Path) -> None:
    """成功・失敗・未対応の件数と単位数、文字数、内訳を集計する。"""
    ok_path = tmp_path / "日本語.ok"
    bad_path = tmp_path / "broken.bad"
    unknown_path = tmp_path / "unknown.pdf"
    ok_path.write_text("あいう", encoding="utf-8")
    bad_path.write_text("broken", encoding="utf-8")
    unknown_path.write_text("pdf", encoding="utf-8")
    registry = ParserRegistry()
    registry.register(FakeParser(name="ok", suffix=".ok"))
    registry.register(FakeParser(name="bad", suffix=".bad", should_fail=True))

    result = ExtractionService(registry).extract(
        [
            make_source_file(ok_path, tmp_path),
            make_source_file(bad_path, tmp_path),
            make_source_file(unknown_path, tmp_path),
        ]
    )

    summary = result.summary
    assert summary.discovered_files == 3
    assert summary.supported_files == summary.succeeded_files + summary.failed_files
    assert summary.discovered_files == (
        summary.succeeded_files + summary.failed_files + summary.unsupported_files
    )
    assert summary.total_units == 1
    assert summary.total_characters == 3
    assert summary.by_parser == {"ok": 1}
    assert summary.by_suffix == {".bad": 1, ".ok": 1, ".pdf": 1}
    assert result.documents[0].source_file.relative_path.as_posix() == "日本語.ok"


def test_extraction_service_sorts_failures_and_unsupported_files(tmp_path: Path) -> None:
    """failuresとunsupported_filesを相対パス順に並べる。"""
    for name in ("z.bad", "a.bad", "y.pdf", "b.pdf"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    registry = ParserRegistry()
    registry.register(FakeParser(name="bad", suffix=".bad", should_fail=True))
    source_files = [
        make_source_file(tmp_path / name, tmp_path) for name in ("z.bad", "a.bad", "y.pdf", "b.pdf")
    ]

    result = ExtractionService(registry).extract(source_files)

    assert [failure.source_file.relative_path.as_posix() for failure in result.failures] == [
        "a.bad",
        "z.bad",
    ]
    assert [source_file.relative_path.as_posix() for source_file in result.unsupported_files] == [
        "b.pdf",
        "y.pdf",
    ]


def test_extraction_service_handles_empty_input() -> None:
    """空の入力ファイル一覧を処理できる。"""
    result = ExtractionService(ParserRegistry()).extract([])

    assert result.documents == ()
    assert result.failures == ()
    assert result.unsupported_files == ()
    assert result.summary.discovered_files == 0
