"""Docling PoCサービスのテスト。"""

from datetime import UTC, datetime
from pathlib import Path

from signate_drive_rag.docling_poc.models import ConversionOutput
from signate_drive_rag.docling_poc.service import (
    DoclingPocService,
    parse_formats,
    parse_profiles,
)
from signate_drive_rag.document_diagnostics.models import OcrEnvironmentDiagnostic
from signate_drive_rag.domain import SourceFile
from signate_drive_rag.domain.extracted_document import JsonValue


class FakeAdapter:
    """実Doclingを起動しない変換アダプター。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def convert(
        self,
        source_path: Path,
        *,
        profile: str,
        timeout_seconds: int,
    ) -> ConversionOutput:
        """拡張子とprofileから決定的な偽結果を返す。"""
        self.calls.append((source_path.name, profile, timeout_seconds))
        if source_path.name == "broken.pdf":
            raise ValueError("broken")
        status = "partial_success" if source_path.name == "partial.pdf" else "success"
        json_document: dict[str, JsonValue] = {"name": source_path.name, "profile": profile}
        return ConversionOutput(
            status=status,
            markdown=f"# {source_path.name}",
            text=f"text {source_path.name}",
            json_document=json_document,
            document=None,
            warnings=(),
            errors=(),
        )


class TimeoutAdapter(FakeAdapter):
    """タイムアウトを返す偽アダプター。"""

    def convert(
        self,
        source_path: Path,
        *,
        profile: str,
        timeout_seconds: int,
    ) -> ConversionOutput:
        """常にTimeoutErrorを発生させる。"""
        raise TimeoutError("timeout")


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


def make_ocr_environment(*, usable: bool) -> OcrEnvironmentDiagnostic:
    """Docling PoCテスト用のOCR環境診断結果を作成する。"""
    return OcrEnvironmentDiagnostic(
        engine="tesseract",
        executable_found=usable,
        executable_path="tesseract" if usable else None,
        version="tesseract 5.3.0" if usable else None,
        available_languages=("eng", "jpn") if usable else (),
        required_languages=("eng", "jpn"),
        missing_languages=() if usable else ("eng", "jpn"),
        usable=usable,
        diagnosis="usable" if usable else "tesseract_not_found",
        warnings=(),
        errors=(),
    )


def test_docling_poc_service_converts_profiles_and_skips_japanese_ocr_for_office() -> None:
    """profileごとに変換し、japanese_ocrはPDF/PNGだけへ適用する。"""
    adapter = FakeAdapter()
    source_files = [
        make_source_file("docs/a.docx", 1),
        make_source_file("docs/b.pdf", 2),
        make_source_file("docs/c.png", 3),
        make_source_file("docs/d.txt", 4),
    ]

    run = DoclingPocService(adapter, ocr_environment=make_ocr_environment(usable=True)).run(
        source_files,
        source_root_name="共有ドライブ",
        formats=parse_formats("docx,pdf,png"),
        samples_per_format=5,
        profiles=parse_profiles("default_local,japanese_ocr"),
        timeout_seconds=180,
        preview_chars=100,
    )

    assert [call[1] for call in adapter.calls] == [
        "default_local",
        "default_local",
        "japanese_ocr",
        "default_local",
        "japanese_ocr",
    ]
    assert run.summary.candidate_counts_by_suffix == {".docx": 1, ".pdf": 1, ".png": 1}
    assert run.summary.selected_counts_by_suffix == {".docx": 1, ".pdf": 1, ".png": 1}
    assert run.summary.executed_conversions == 5
    assert run.summary.status_counts["success"] == 5
    assert all(
        not result.relative_path.startswith(str(Path("root").resolve())) for result in run.results
    )


def test_docling_poc_service_skips_japanese_ocr_when_ocr_unavailable() -> None:
    """OCR環境が利用できない場合はjapanese_ocrを失敗ではなくスキップにする。"""
    adapter = FakeAdapter()
    source_files = [make_source_file("docs/b.pdf", 2)]

    run = DoclingPocService(adapter, ocr_environment=make_ocr_environment(usable=False)).run(
        source_files,
        source_root_name="共有ドライブ",
        formats=parse_formats("pdf"),
        samples_per_format=1,
        profiles=parse_profiles("default_local,japanese_ocr"),
        timeout_seconds=180,
        preview_chars=100,
    )

    assert [call[1] for call in adapter.calls] == ["default_local"]
    assert run.summary.executed_conversions == 1
    assert run.summary.status_counts["success"] == 1
    assert run.summary.status_counts["skipped"] == 1
    assert any(result.status == "skipped" for result in run.results)
    assert run.manifest.ocr_environment is not None


def test_docling_poc_service_continues_after_failure_and_keeps_partial_success() -> None:
    """1件失敗しても継続し、部分成功を失敗扱いにしない。"""
    adapter = FakeAdapter()
    source_files = [
        make_source_file("docs/broken.pdf", 1),
        make_source_file("docs/partial.pdf", 2),
        make_source_file("docs/ok.pdf", 3),
    ]

    run = DoclingPocService(adapter).run(
        source_files,
        source_root_name="共有ドライブ",
        formats=parse_formats("pdf"),
        samples_per_format=3,
        profiles=parse_profiles("default_local"),
        timeout_seconds=30,
        preview_chars=100,
    )

    assert run.summary.status_counts["failed"] == 1
    assert run.summary.status_counts["partial_success"] == 1
    assert run.summary.status_counts["success"] == 1
    assert len(run.artifacts) == 2
    assert [result.relative_path for result in run.results] == [
        "docs/broken.pdf",
        "docs/ok.pdf",
        "docs/partial.pdf",
    ]


def test_docling_poc_service_records_timeout_and_empty_candidates() -> None:
    """タイムアウトと候補0件を扱えることを確認する。"""
    timeout_run = DoclingPocService(TimeoutAdapter()).run(
        [make_source_file("docs/a.pdf", 1)],
        source_root_name="共有ドライブ",
        formats=parse_formats("pdf"),
        samples_per_format=1,
        profiles=parse_profiles("default_local"),
        timeout_seconds=1,
        preview_chars=10,
    )
    empty_run = DoclingPocService(FakeAdapter()).run(
        [],
        source_root_name="共有ドライブ",
        formats=parse_formats("pdf"),
        samples_per_format=1,
        profiles=parse_profiles("default_local"),
        timeout_seconds=1,
        preview_chars=10,
    )

    assert timeout_run.summary.status_counts["timeout"] == 1
    assert empty_run.summary.executed_conversions == 0
    assert empty_run.selections == ()
    assert empty_run.results == ()
