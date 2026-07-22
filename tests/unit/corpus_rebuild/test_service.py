"""RebuildCorpusServiceのテスト。"""

import json
from pathlib import Path

import pytest

from signate_drive_rag.corpus_rebuild import (
    RebuildCorpusError,
    RebuildCorpusOptions,
    RebuildCorpusService,
)


def test_rebuild_corpus_service_runs_required_stages_and_writes_outputs(
    tmp_path: Path,
) -> None:
    """小さな入力で探索からBM25構築まで実行し、任意工程はskipする。"""
    source = _write_source_files(tmp_path)
    output_dir = tmp_path / "out"

    result = RebuildCorpusService().rebuild(
        RebuildCorpusOptions(source=source, output_dir=output_dir, overwrite=True),
    )

    statuses = {stage.name: stage.status for stage in result.stages}
    assert statuses == {
        "scan": "success",
        "extract": "success",
        "audit": "success",
        "chunk": "success",
        "validate_chunks": "success",
        "build_bm25": "success",
        "evaluate_search": "skipped",
        "compare_baseline": "skipped",
    }
    assert (output_dir / "manifest.json").is_file()
    assert (output_dir / "stage_status.json").is_file()
    assert (output_dir / "source_snapshot.jsonl").is_file()
    assert (output_dir / "report.md").is_file()
    assert (output_dir / "scan" / "files.jsonl").is_file()
    assert (output_dir / "extraction" / "documents.jsonl").is_file()
    assert (output_dir / "audit" / "summary.json").is_file()
    assert (output_dir / "chunks" / "chunks.jsonl").is_file()
    assert (output_dir / "validation" / "errors.jsonl").is_file()
    assert (output_dir / "indexes" / "bm25" / "manifest.json").is_file()

    snapshot_text = (output_dir / "source_snapshot.jsonl").read_text(encoding="utf-8")
    assert "資料/alpha.txt" in snapshot_text
    assert "ignored_reason" in snapshot_text
    assert str(tmp_path) not in snapshot_text

    scan_summary = json.loads((output_dir / "scan" / "summary.json").read_text(encoding="utf-8"))
    assert scan_summary["discovered_files"] == 4
    assert scan_summary["ignored_files"] == 1
    assert scan_summary["processable_files"] == 3
    assert scan_summary["unsupported_files"] == 1


def test_rebuild_corpus_service_reuses_matching_completed_stages(
    tmp_path: Path,
) -> None:
    """resume時に指紋が一致する完了済み工程を再利用する。"""
    source = _write_source_files(tmp_path)
    output_dir = tmp_path / "out"
    service = RebuildCorpusService()
    service.rebuild(RebuildCorpusOptions(source=source, output_dir=output_dir, overwrite=True))

    result = service.rebuild(
        RebuildCorpusOptions(source=source, output_dir=output_dir, resume=True)
    )

    statuses = {stage.name: stage.status for stage in result.stages}
    assert statuses["scan"] == "reused"
    assert statuses["extract"] == "reused"
    assert statuses["audit"] == "reused"
    assert statuses["chunk"] == "reused"
    assert statuses["validate_chunks"] == "reused"
    assert statuses["build_bm25"] == "reused"
    assert statuses["evaluate_search"] == "skipped"


def test_rebuild_corpus_service_rejects_overwrite_and_resume_together(
    tmp_path: Path,
) -> None:
    """overwriteとresumeを同時指定した場合は明確に失敗する。"""
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(RebuildCorpusError):
        RebuildCorpusService().rebuild(
            RebuildCorpusOptions(
                source=source,
                output_dir=tmp_path / "out",
                overwrite=True,
                resume=True,
            ),
        )


def test_rebuild_corpus_service_requires_ocr_model_manifest_when_ocr_is_enabled(
    tmp_path: Path,
) -> None:
    """OCR有効化時にモデルmanifestがない場合は処理を開始しない。"""
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(RebuildCorpusError, match="OCRモデルmanifest"):
        RebuildCorpusService().rebuild(
            RebuildCorpusOptions(
                source=source,
                output_dir=tmp_path / "out",
                enable_ocr=True,
                ocr_model_dir=tmp_path / "models",
            ),
        )


def test_rebuild_corpus_service_records_quality_gate_failure_separately(
    tmp_path: Path,
) -> None:
    """strictの品質ゲート失敗を検証工程の成果物と分けて記録する。"""
    source = tmp_path / "source"
    source.mkdir()
    (source / "ok.txt").write_text("alpha", encoding="utf-8")
    (source / "broken.json").write_text("{invalid", encoding="utf-8")
    output_dir = tmp_path / "out"

    with pytest.raises(RebuildCorpusError, match="strict_quality_gate_failed"):
        RebuildCorpusService().rebuild(
            RebuildCorpusOptions(
                source=source,
                output_dir=output_dir,
                overwrite=True,
                strict=True,
            )
        )

    status_record = json.loads((output_dir / "stage_status.json").read_text(encoding="utf-8"))
    statuses = {stage["name"]: stage["status"] for stage in status_record["stages"]}
    assert statuses["validate_chunks"] == "success"
    assert statuses["quality_gate"] == "failed"
    assert (output_dir / "validation" / "summary.json").is_file()


def test_rebuild_corpus_service_raises_resume_mismatch_when_inputs_change(
    tmp_path: Path,
) -> None:
    """resume対象工程の入力指紋が変わった場合は古い成果物を混在させない。"""
    source = _write_source_files(tmp_path)
    output_dir = tmp_path / "out"
    service = RebuildCorpusService()
    service.rebuild(RebuildCorpusOptions(source=source, output_dir=output_dir, overwrite=True))
    (source / "資料" / "alpha.txt").write_text("changed", encoding="utf-8")

    with pytest.raises(RebuildCorpusError, match="resume_fingerprint_mismatch"):
        service.rebuild(RebuildCorpusOptions(source=source, output_dir=output_dir, resume=True))


def _write_source_files(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    nested = source / "資料"
    nested.mkdir(parents=True)
    (nested / "alpha.txt").write_text("alpha keyword", encoding="utf-8")
    (nested / "beta.md").write_text("# 見出し\n\n本文 keyword", encoding="utf-8")
    (nested / "unsupported.bin").write_bytes(b"\x00\x01")
    (nested / "~$temporary.docx").write_text("ignored", encoding="utf-8")
    return source
