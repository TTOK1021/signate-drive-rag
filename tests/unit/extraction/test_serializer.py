"""抽出結果シリアライザーの単体テスト。"""

import json
from datetime import UTC, datetime
from pathlib import Path

from signate_drive_rag.domain import ExtractedDocument, ExtractedUnit, SourceFile
from signate_drive_rag.extraction.models import (
    BatchExtractionResult,
    ExtractionFailure,
    ExtractionSummary,
)
from signate_drive_rag.extraction.serializer import save_extraction_result


def make_source_file(path: Path, root: Path) -> SourceFile:
    """テスト用のSourceFileを作成する。"""
    path.write_text("source", encoding="utf-8")
    stat_result = path.stat()
    return SourceFile(
        path=path,
        relative_path=path.relative_to(root),
        name=path.name,
        suffix=path.suffix.lower(),
        mime_type="text/plain",
        size_bytes=stat_result.st_size,
        modified_at=datetime(2026, 7, 11, 12, 0, tzinfo=UTC),
    )


def make_result(tmp_path: Path, *, include_failure: bool = True) -> BatchExtractionResult:
    """テスト用の一括抽出結果を作成する。"""
    source_file = make_source_file(tmp_path / "日本語.txt", tmp_path)
    unsupported_file = make_source_file(tmp_path / "report.pdf", tmp_path)
    document = ExtractedDocument(
        source_file=source_file,
        parser_name="plain_text",
        units=(
            ExtractedUnit(
                unit_type="text",
                text="本文\n日本語",
                locator=None,
                metadata={"encoding": "utf-8", "line_count": 2},
            ),
        ),
    )
    failures = (
        (
            ExtractionFailure(
                source_file=source_file,
                parser_name="plain_text",
                error_type="ValueError",
                error_message="broken",
            ),
        )
        if include_failure
        else ()
    )
    summary = ExtractionSummary(
        discovered_files=2,
        supported_files=1 + len(failures),
        succeeded_files=1,
        failed_files=len(failures),
        unsupported_files=1,
        total_units=1,
        total_characters=len("本文\n日本語"),
        by_parser={"plain_text": 1},
        by_suffix={".pdf": 1, ".txt": 1},
    )
    return BatchExtractionResult(
        documents=(document,),
        failures=failures,
        unsupported_files=(unsupported_file,),
        summary=summary,
    )


def test_save_extraction_result_writes_valid_documents_jsonl(tmp_path: Path) -> None:
    """documents.jsonlを1行ずつ有効なJSONとして保存する。"""
    output_dir = tmp_path / "out"

    save_extraction_result(make_result(tmp_path), output_dir)

    lines = (output_dir / "documents.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert len(records) == 1
    assert records[0]["units"][0]["text"] == "本文\n日本語"
    assert records[0]["source"]["relative_path"] == "日本語.txt"
    assert str(tmp_path) not in lines[0]
    assert records[0]["source"]["modified_at"] == "2026-07-11T12:00:00+00:00"


def test_save_extraction_result_writes_empty_failure_file_when_no_failures(
    tmp_path: Path,
) -> None:
    """failuresが0件でも空のfailures.jsonlを生成する。"""
    output_dir = tmp_path / "out"

    save_extraction_result(make_result(tmp_path, include_failure=False), output_dir)

    assert (output_dir / "failures.jsonl").read_text(encoding="utf-8") == ""


def test_save_extraction_result_writes_unsupported_jsonl(tmp_path: Path) -> None:
    """unsupported.jsonlへ未対応ファイル情報を保存する。"""
    output_dir = tmp_path / "out"

    save_extraction_result(make_result(tmp_path), output_dir)

    record = json.loads((output_dir / "unsupported.jsonl").read_text(encoding="utf-8"))
    assert record["relative_path"] == "report.pdf"
    assert "path" not in record


def test_save_extraction_result_writes_summary_json(tmp_path: Path) -> None:
    """summary.jsonへsummaryの値を保存する。"""
    output_dir = tmp_path / "out"

    save_extraction_result(make_result(tmp_path), output_dir)

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["discovered_files"] == 2
    assert summary["by_parser"] == {"plain_text": 1}


def test_save_extraction_result_creates_output_directory_and_replaces_existing_files(
    tmp_path: Path,
) -> None:
    """出力ディレクトリを作成し、既存ファイルを正常に置き換える。"""
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "summary.json").write_text("old", encoding="utf-8")

    save_extraction_result(make_result(tmp_path), output_dir)

    assert (
        json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))["succeeded_files"]
        == 1
    )


def test_save_extraction_result_leaves_no_temporary_files(tmp_path: Path) -> None:
    """正常終了後に一時ファイルを残さない。"""
    output_dir = tmp_path / "out"

    save_extraction_result(make_result(tmp_path), output_dir)

    assert list(output_dir.glob("*.tmp")) == []


def test_save_extraction_result_keeps_deterministic_output_order(tmp_path: Path) -> None:
    """同じ入力を2回保存しても出力順が変わらない。"""
    output_dir = tmp_path / "out"
    result = make_result(tmp_path)

    save_extraction_result(result, output_dir)
    first_output = (output_dir / "documents.jsonl").read_text(encoding="utf-8")
    save_extraction_result(result, output_dir)
    second_output = (output_dir / "documents.jsonl").read_text(encoding="utf-8")

    assert first_output == second_output
