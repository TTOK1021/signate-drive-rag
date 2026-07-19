"""原本ファイル群を一括抽出するサービス。"""

from collections import Counter
from collections.abc import Sequence

from signate_drive_rag.domain import ExtractedDocument, SourceFile
from signate_drive_rag.extraction.models import (
    BatchExtractionResult,
    ExtractionFailure,
    ExtractionSummary,
)
from signate_drive_rag.ingestion.parser_registry import ParserNotFoundError, ParserRegistry


class ExtractionService:
    """原本ファイル群を一括抽出する。"""

    def __init__(self, parser_registry: ParserRegistry) -> None:
        """使用するパーサーレジストリを受け取る。"""
        self._parser_registry = parser_registry

    def extract(self, source_files: Sequence[SourceFile]) -> BatchExtractionResult:
        """原本ファイル一覧を抽出し、成功・未対応・失敗へ分類する。"""
        documents: list[ExtractedDocument] = []
        failures: list[ExtractionFailure] = []
        unsupported_files: list[SourceFile] = []

        for source_file in source_files:
            try:
                parser = self._parser_registry.find_parser(source_file)
            except ParserNotFoundError:
                unsupported_files.append(source_file)
                continue

            try:
                documents.append(parser.parse(source_file))
            except Exception as error:
                # 一括処理では1ファイルの破損で全体を止めず、失敗情報として成果物へ残す。
                failures.append(
                    ExtractionFailure(
                        source_file=source_file,
                        parser_name=parser.name,
                        error_type=type(error).__name__,
                        error_message=str(error),
                    )
                )

        sorted_documents = tuple(sorted(documents, key=_document_sort_key))
        sorted_failures = tuple(sorted(failures, key=_failure_sort_key))
        sorted_unsupported_files = tuple(sorted(unsupported_files, key=_source_file_sort_key))
        summary = _build_summary(
            source_files=source_files,
            documents=sorted_documents,
            failures=sorted_failures,
            unsupported_files=sorted_unsupported_files,
        )
        return BatchExtractionResult(
            documents=sorted_documents,
            failures=sorted_failures,
            unsupported_files=sorted_unsupported_files,
            summary=summary,
        )


def _build_summary(
    source_files: Sequence[SourceFile],
    documents: Sequence[ExtractedDocument],
    failures: Sequence[ExtractionFailure],
    unsupported_files: Sequence[SourceFile],
) -> ExtractionSummary:
    """一括抽出結果から集計値を作成する。"""
    by_parser = Counter(document.parser_name for document in documents)
    by_suffix = Counter(source_file.suffix.lower() for source_file in source_files)
    issues_by_type = Counter(
        issue.issue_type for document in documents for issue in document.issues
    )
    total_units = sum(len(document.units) for document in documents)
    total_characters = sum(len(unit.text) for document in documents for unit in document.units)
    succeeded_files = len(documents)
    failed_files = len(failures)
    unsupported_count = len(unsupported_files)

    return ExtractionSummary(
        discovered_files=len(source_files),
        supported_files=succeeded_files + failed_files,
        succeeded_files=succeeded_files,
        failed_files=failed_files,
        unsupported_files=unsupported_count,
        total_units=total_units,
        total_characters=total_characters,
        total_issues=sum(issues_by_type.values()),
        by_parser=dict(sorted(by_parser.items())),
        by_suffix=dict(sorted(by_suffix.items())),
        issues_by_type=dict(sorted(issues_by_type.items())),
    )


def _source_file_sort_key(source_file: SourceFile) -> str:
    """SourceFileを相対パス順に並べるためのキーを返す。"""
    return source_file.relative_path.as_posix()


def _document_sort_key(document: ExtractedDocument) -> str:
    """ExtractedDocumentを原本相対パス順に並べるためのキーを返す。"""
    return _source_file_sort_key(document.source_file)


def _failure_sort_key(failure: ExtractionFailure) -> str:
    """ExtractionFailureを原本相対パス順に並べるためのキーを返す。"""
    return _source_file_sort_key(failure.source_file)
