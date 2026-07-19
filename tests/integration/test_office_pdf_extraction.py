"""Office・PDF抽出パイプラインの統合テスト。"""

import json
from pathlib import Path

from typer.testing import CliRunner

from signate_drive_rag.cli import app
from signate_drive_rag.domain import ExtractedDocument, ExtractedUnit, ExtractionIssue, SourceFile
from signate_drive_rag.ingestion import discover_files_with_ignored
from signate_drive_rag.ingestion.parser_registry import ParserRegistry

runner = CliRunner()


class FakeOfficePdfParser:
    """統合テストで外部変換を避けるための偽パーサー。"""

    def __init__(
        self,
        *,
        name: str,
        suffix: str,
        unit_type: str,
        locator: str,
        issue: ExtractionIssue | None = None,
        should_fail: bool = False,
    ) -> None:
        """拡張子ごとの最小パーサーを作成する。"""
        self._name = name
        self._suffix = suffix
        self._unit_type = unit_type
        self._locator = locator
        self._issue = issue
        self._should_fail = should_fail

    @property
    def name(self) -> str:
        """パーサー名を返す。"""
        return self._name

    def supports(self, source_file: SourceFile) -> bool:
        """対象拡張子だけを処理する。"""
        return source_file.suffix == self._suffix

    def parse(self, source_file: SourceFile) -> ExtractedDocument:
        """固定の抽出結果または失敗を返す。"""
        if self._should_fail:
            raise ValueError("failed without source text")
        return ExtractedDocument(
            source_file=source_file,
            parser_name=self.name,
            units=(
                ExtractedUnit(
                    unit_type=self._unit_type,
                    text=f"{source_file.name} の本文",
                    locator=self._locator,
                    metadata={"headers": ["A"], "logical_row_number": 1}
                    if self._unit_type.endswith("table_row")
                    else {},
                ),
            ),
            issues=() if self._issue is None else (self._issue,),
        )


def create_fake_registry() -> ParserRegistry:
    """DOCX・PPTX・PDF用の偽Registryを作成する。"""
    registry = ParserRegistry()
    registry.register(
        FakeOfficePdfParser(
            name="docling_docx",
            suffix=".docx",
            unit_type="docx_paragraph",
            locator="item:1",
        )
    )
    registry.register(
        FakeOfficePdfParser(
            name="docling_pptx",
            suffix=".pptx",
            unit_type="pptx_slide_text",
            locator="slide:1/item:1",
        )
    )
    registry.register(
        FakeOfficePdfParser(
            name="pypdf",
            suffix=".pdf",
            unit_type="pdf_page_text",
            locator="page:1",
            issue=ExtractionIssue(
                issue_type="pdf_page_needs_ocr",
                severity="info",
                message="OCR候補です。",
                locator="page:1",
                metadata={"page_number": 1, "threshold": 20, "text_characters": 1},
            ),
        )
    )
    registry.register(
        FakeOfficePdfParser(
            name="broken_json",
            suffix=".json",
            unit_type="json_value",
            locator="/",
            should_fail=True,
        )
    )
    return registry


def test_office_pdf_pipeline_extracts_audits_and_chunks_with_fake_parsers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """DOCX・PPTX・PDFを含むディレクトリを抽出、監査、チャンク化できる。"""
    root = tmp_path / "root"
    root.mkdir()
    for file_name in ("資料.docx", "発表.pptx", "報告.pdf", "broken.json", "~$一時.docx"):
        (root / file_name).write_text("content", encoding="utf-8")
    output_dir = tmp_path / "extracted"
    audit_dir = tmp_path / "audit"
    chunks_dir = tmp_path / "chunks"

    discovery_result = discover_files_with_ignored(root)
    assert [file.relative_path.as_posix() for file in discovery_result.source_files] == [
        "broken.json",
        "報告.pdf",
        "発表.pptx",
        "資料.docx",
    ]
    assert len(discovery_result.ignored_files) == 1

    monkeypatch.setattr(
        "signate_drive_rag.cli.create_default_parser_registry",
        create_fake_registry,
    )
    extract_result = runner.invoke(
        app,
        ["extract", "--root", str(root), "--output-dir", str(output_dir)],
    )
    assert extract_result.exit_code == 0
    assert "抽出成功: 3" in extract_result.stdout
    assert "抽出失敗: 1" in extract_result.stdout

    documents = [
        json.loads(line)
        for line in (output_dir / "documents.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["by_parser"] == {"docling_docx": 1, "docling_pptx": 1, "pypdf": 1}
    assert summary["issues_by_type"] == {"pdf_page_needs_ocr": 1}
    assert {document["parser_name"] for document in documents} == {
        "docling_docx",
        "docling_pptx",
        "pypdf",
    }

    audit_result = runner.invoke(
        app,
        [
            "audit",
            "--documents",
            str(output_dir / "documents.jsonl"),
            "--output-dir",
            str(audit_dir),
        ],
    )
    assert audit_result.exit_code == 0
    assert (audit_dir / "report.md").exists()
    audit_summary = json.loads((audit_dir / "summary.json").read_text(encoding="utf-8"))
    assert audit_summary["by_parser"]["pypdf"]["documents"] == 1
    assert audit_summary["issues_by_type"]["pdf_page_needs_ocr"] == 1

    chunk_result = runner.invoke(
        app,
        [
            "chunk",
            "--documents",
            str(output_dir / "documents.jsonl"),
            "--output-dir",
            str(chunks_dir),
            "--max-chars",
            "100",
            "--overlap-chars",
            "0",
        ],
    )
    assert chunk_result.exit_code == 0
    chunks = [
        json.loads(line)
        for line in (chunks_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert {chunk["parser_name"] for chunk in chunks} == {"docling_docx", "docling_pptx", "pypdf"}
