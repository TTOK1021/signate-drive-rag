"""チャンク検証結果シリアライザーのテスト。"""

import json
from pathlib import Path

from signate_drive_rag.chunk_validation import (
    ChunkValidationError,
    ChunkValidationResult,
    ChunkValidationSummary,
    save_chunk_validation_result,
)


def test_chunk_validation_serializer_writes_jsonl_and_replaces_files(tmp_path: Path) -> None:
    """JSON/JSONL/Markdownを生成し、既存ファイルを置換して一時ファイルを残さない。"""
    output_dir = tmp_path / "validation"
    output_dir.mkdir()
    (output_dir / "summary.json").write_text("old", encoding="utf-8")
    result = ChunkValidationResult(
        summary=ChunkValidationSummary(
            chunks=1,
            source_documents=1,
            source_units=1,
            errors=1,
            warnings=0,
            duplicate_chunk_ids=0,
            duplicate_chunk_contents=0,
            empty_text_chunks=1,
            nul_text_chunks=0,
            invalid_document_references=0,
            invalid_unit_references=0,
            absolute_path_violations=0,
            invalid_locator_count=0,
            json_metadata_errors=0,
            oversized_chunks=0,
            maximum_chunk_characters=0,
            mean_chunk_characters=0.0,
            median_chunk_characters=0.0,
            p95_chunk_characters=0.0,
            text_chunks=1,
            table_chunks=0,
            ocr_chunks=0,
        ),
        errors=(
            ChunkValidationError(
                chunk_id="c1",
                relative_path="資料/a.txt",
                issue_type="empty_text_chunk",
                severity="error",
                message="本文が空です。",
            ),
        ),
    )

    save_chunk_validation_result(result, output_dir)

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    errors = [
        json.loads(line)
        for line in (output_dir / "errors.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert summary["errors"] == 1
    assert errors[0]["relative_path"] == "資料/a.txt"
    assert (output_dir / "report.md").exists()
    assert not list(output_dir.glob("*.tmp"))
