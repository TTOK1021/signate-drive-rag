"""コマンドラインからRAG処理を実行するための入口。"""

import json
import os
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from signate_drive_rag.audit import (
    AuditInputError,
    AuditService,
    load_audit_documents,
    save_audit_result,
)
from signate_drive_rag.audit.service import ISSUE_TYPES
from signate_drive_rag.chunking import (
    ChunkingService,
    ChunkInputError,
    load_chunk_source_documents,
    save_chunking_result,
)
from signate_drive_rag.docling_poc import (
    DoclingConfigurationError,
    DoclingConversionAdapter,
    DoclingPocInputError,
    DoclingPocOutputError,
    DoclingPocService,
    parse_formats,
    parse_profiles,
    save_docling_poc_run,
)
from signate_drive_rag.document_diagnostics.serializer import (
    DocumentDiagnosticOutputError,
    save_document_diagnostic_report,
)
from signate_drive_rag.document_diagnostics.service import (
    DocumentDiagnosticInputError,
    DocumentDiagnosticService,
    parse_diagnostic_formats,
)
from signate_drive_rag.domain import SourceFile
from signate_drive_rag.extraction import ExtractionService, save_extraction_result
from signate_drive_rag.ingestion import discover_files, discover_files_with_ignored
from signate_drive_rag.ingestion.parser_registry import create_default_parser_registry
from signate_drive_rag.retrieval import (
    SEARCH_CHANNELS,
    Bm25Retriever,
    RetrievalIndexError,
    RetrievalInputError,
    SearchInputError,
    build_bm25_index,
    calculate_file_sha256,
    load_bm25_index,
    load_retrieval_chunks,
    save_bm25_index,
    save_search_results,
)
from signate_drive_rag.search_evaluation import (
    SearchEvaluationInputError,
    SearchEvaluationService,
    calculate_query_file_sha256,
    load_search_evaluation_queries,
    save_search_evaluation_result,
)

DEFAULT_DISPLAY_SUFFIXES = (".pdf", ".xlsx", ".docx", ".pptx", ".py", ".ipynb")
OTHER_EXTENSION_LABEL = "その他"
NO_EXTENSION_LABEL = "拡張子なし"

app = typer.Typer(help="共有ドライブ向けRAGシステムの実行コマンド。")


@app.callback()
def main() -> None:
    """共有ドライブ向けRAGシステムのコマンドグループ。"""


def resolve_source_root(root: Path | None) -> Path:
    """引数または環境変数から探索ルートを決定する。"""
    if root is not None:
        return root

    # .envを任意入力として扱い、実行環境ごとの差をコードへ埋め込まない。
    load_dotenv(dotenv_path=Path(".env"))
    source_root = os.getenv("SOURCE_ROOT")
    if source_root is None or source_root == "":
        raise ValueError("--root または SOURCE_ROOT を指定してください。")

    return Path(source_root)


def summarize_extension_counts(source_files: Sequence[SourceFile]) -> list[tuple[str, int]]:
    """表示対象の拡張子別件数とその他件数を集計する。"""
    extension_counts = Counter(source_file.suffix for source_file in source_files)
    known_total = sum(extension_counts[suffix] for suffix in DEFAULT_DISPLAY_SUFFIXES)
    summary = [(suffix, extension_counts[suffix]) for suffix in DEFAULT_DISPLAY_SUFFIXES]
    summary.append((OTHER_EXTENSION_LABEL, len(source_files) - known_total))
    return summary


def summarize_other_extension_counts(source_files: Sequence[SourceFile]) -> list[tuple[str, int]]:
    """主要表示対象に含めない拡張子の内訳を集計する。"""
    extension_counts = Counter(
        source_file.suffix if source_file.suffix != "" else NO_EXTENSION_LABEL
        for source_file in source_files
        if source_file.suffix not in DEFAULT_DISPLAY_SUFFIXES
    )
    return sorted(extension_counts.items(), key=lambda item: (-item[1], item[0]))


def write_manifest_jsonl(source_files: Sequence[SourceFile], manifest_path: Path) -> None:
    """検出したファイル情報をJSON Lines形式で保存する。"""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8", newline="\n") as manifest_file:
        for source_file in source_files:
            manifest_file.write(
                json.dumps(_source_file_to_manifest_record(source_file), ensure_ascii=False) + "\n"
            )


def _source_file_to_manifest_record(source_file: SourceFile) -> dict[str, object]:
    """SourceFileを再利用しやすいJSON互換の辞書へ変換する。"""
    return {
        "path": str(source_file.path),
        "relative_path": source_file.relative_path.as_posix(),
        "name": source_file.name,
        "suffix": source_file.suffix,
        "mime_type": source_file.mime_type,
        "size_bytes": source_file.size_bytes,
        "modified_at": source_file.modified_at.isoformat(),
    }


@app.command()
def scan(
    root: Annotated[
        Path | None,
        typer.Option("--root", "-r", help="探索ルート。未指定時はSOURCE_ROOTを使用します。"),
    ] = None,
    manifest: Annotated[
        Path | None,
        typer.Option("--manifest", help="検出結果をJSON Lines形式で保存するパス。"),
    ] = None,
) -> None:
    """指定したルート配下の原本ファイルを探索する。"""
    try:
        source_root = resolve_source_root(root)
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    discovery_result = discover_files_with_ignored(source_root)
    source_files = list(discovery_result.source_files)
    resolved_root = source_root.resolve()

    typer.echo(f"探索ルート: {resolved_root}")
    typer.echo(f"検出ファイル数: {len(source_files)}")
    typer.echo("")
    typer.echo("拡張子別:")
    for extension, count in summarize_extension_counts(source_files):
        typer.echo(f"{extension:<7} {count}")

    other_extension_counts = summarize_other_extension_counts(source_files)
    if other_extension_counts:
        typer.echo("")
        typer.echo("その他内訳:")
        for extension, count in other_extension_counts:
            typer.echo(f"{extension:<7} {count}")

    if discovery_result.ignored_files:
        typer.echo("")
        typer.echo(f"除外ファイル数: {len(discovery_result.ignored_files)}")
        for reason, count in discovery_result.ignored_by_reason.items():
            typer.echo(f"{reason}: {count}")

    if manifest is not None:
        write_manifest_jsonl(source_files, manifest)
        typer.echo("")
        typer.echo(f"manifest: {manifest}")


@app.command()
def extract(
    root: Annotated[
        Path,
        typer.Option("--root", "-r", help="抽出対象の探索ルート。"),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="抽出結果の保存先。"),
    ] = Path("artifacts") / "extracted",
) -> None:
    """指定したルート配下の原本ファイルを一括抽出する。"""
    source_files = discover_files(root)
    parser_registry = create_default_parser_registry()
    extraction_result = ExtractionService(parser_registry).extract(source_files)
    save_extraction_result(extraction_result, output_dir)

    summary = extraction_result.summary
    typer.echo(f"探索ルート: {root.resolve()}")
    typer.echo(f"探索ファイル数: {summary.discovered_files}")
    typer.echo(f"対応ファイル数: {summary.supported_files}")
    typer.echo(f"抽出成功: {summary.succeeded_files}")
    typer.echo(f"抽出失敗: {summary.failed_files}")
    typer.echo(f"未対応: {summary.unsupported_files}")
    typer.echo(f"抽出単位数: {summary.total_units}")
    typer.echo(f"抽出文字数: {summary.total_characters:,}")
    typer.echo("")
    typer.echo("出力:")
    typer.echo("  documents.jsonl")
    typer.echo("  failures.jsonl")
    typer.echo("  unsupported.jsonl")
    typer.echo("  summary.json")


@app.command()
def audit(
    documents: Annotated[
        Path,
        typer.Option("--documents", help="抽出済みdocuments.jsonlへのパス。"),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="監査結果の保存先。"),
    ] = Path("artifacts") / "audit",
    samples_per_parser: Annotated[
        int,
        typer.Option("--samples-per-parser", help="パーサーごとのサンプル文書数。"),
    ] = 3,
    preview_chars: Annotated[
        int,
        typer.Option("--preview-chars", help="サンプル本文プレビューの最大文字数。"),
    ] = 300,
    large_unit_chars: Annotated[
        int,
        typer.Option("--large-unit-chars", help="巨大unitと判定する文字数。"),
    ] = 20_000,
) -> None:
    """抽出済みdocuments.jsonlの品質を監査する。"""
    try:
        audit_documents = load_audit_documents(documents)
        audit_result = AuditService(
            large_unit_chars=large_unit_chars,
            samples_per_parser=samples_per_parser,
            preview_chars=preview_chars,
        ).audit(audit_documents)
    except (AuditInputError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    save_audit_result(audit_result, output_dir)
    summary = audit_result.summary

    typer.echo(f"監査対象: {documents.resolve()}")
    typer.echo(f"文書数: {summary.documents}")
    typer.echo(f"抽出単位数: {summary.total_units:,}")
    typer.echo(f"抽出文字数: {summary.total_characters:,}")
    typer.echo("")
    typer.echo("検出事項:")
    typer.echo(f"  error: {summary.issues_by_severity['error']}")
    typer.echo(f"  warning: {summary.issues_by_severity['warning']}")
    typer.echo(f"  info: {summary.issues_by_severity['info']}")
    typer.echo(f"  合計: {summary.total_issues}")
    typer.echo("")
    typer.echo("主な内訳:")
    for issue_type in ISSUE_TYPES:
        typer.echo(f"  {issue_type}: {summary.issues_by_type[issue_type]}")
    typer.echo("")
    typer.echo("出力:")
    typer.echo("  summary.json")
    typer.echo("  issues.jsonl")
    typer.echo("  samples.jsonl")
    typer.echo("  report.md")


@app.command()
def chunk(
    documents: Annotated[
        Path,
        typer.Option("--documents", help="抽出済みdocuments.jsonlへのパス。"),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="検索用チャンクの保存先。"),
    ] = Path("artifacts") / "chunks",
    max_chars: Annotated[
        int,
        typer.Option("--max-chars", help="1チャンクの最大文字数。"),
    ] = 4_000,
    overlap_chars: Annotated[
        int,
        typer.Option("--overlap-chars", help="分割チャンク間の重複文字数。"),
    ] = 200,
    table_max_rows: Annotated[
        int,
        typer.Option("--table-max-rows", help="表チャンクに含める最大データ行数。"),
    ] = 25,
) -> None:
    """抽出済みdocuments.jsonlから検索用チャンクを生成する。"""
    try:
        source_documents = load_chunk_source_documents(documents)
        chunking_result = ChunkingService(
            max_chars=max_chars,
            overlap_chars=overlap_chars,
            table_max_rows=table_max_rows,
        ).chunk(source_documents)
    except (ChunkInputError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    save_chunking_result(chunking_result, output_dir)
    summary = chunking_result.summary
    typer.echo(f"入力: {documents.resolve()}")
    typer.echo(f"元文書数: {summary.source_documents}")
    typer.echo(f"元unit数: {summary.source_units:,}")
    typer.echo(f"元文字数: {summary.source_characters:,}")
    typer.echo("")
    typer.echo(f"生成チャンク数: {summary.generated_chunks:,}")
    typer.echo(f"チャンク文字数: {summary.chunk_characters:,}")
    typer.echo(f"最大チャンク文字数: {summary.maximum_chunk_characters:,}")
    typer.echo(f"文字数削減率: {summary.character_reduction_rate:.2%}")
    typer.echo("")
    typer.echo("issue:")
    typer.echo(f"  error: {summary.issues_by_severity['error']}")
    typer.echo(f"  warning: {summary.issues_by_severity['warning']}")
    typer.echo(f"  info: {summary.issues_by_severity['info']}")
    typer.echo("")
    typer.echo("出力:")
    typer.echo("  chunks.jsonl")
    typer.echo("  summary.json")
    typer.echo("  issues.jsonl")

    if summary.issues_by_severity["error"] > 0:
        raise typer.Exit(code=1)


@app.command()
def index(
    chunks: Annotated[
        Path,
        typer.Option("--chunks", help="入力chunks.jsonlへのパス。"),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="BM25インデックスの保存先。"),
    ] = Path("artifacts") / "indexes" / "bm25",
    ngram_min: Annotated[
        int,
        typer.Option("--ngram-min", help="日本語N-gramの最小長。"),
    ] = 2,
    ngram_max: Annotated[
        int,
        typer.Option("--ngram-max", help="日本語N-gramの最大長。"),
    ] = 3,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="既存インデックスを置き換える。"),
    ] = False,
) -> None:
    """chunks.jsonlからBM25インデックスを構築する。"""
    try:
        retrieval_chunks = load_retrieval_chunks(chunks)
        source_sha256 = calculate_file_sha256(chunks)
        bm25_index = build_bm25_index(
            retrieval_chunks,
            source_sha256=source_sha256,
            ngram_min=ngram_min,
            ngram_max=ngram_max,
        )
        save_bm25_index(bm25_index, output_dir, overwrite=overwrite)
    except (RetrievalInputError, RetrievalIndexError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    typer.echo(f"入力: {chunks.resolve()}")
    typer.echo(f"チャンク数: {len(retrieval_chunks):,}")
    typer.echo(f"入力SHA-256: {source_sha256}")
    typer.echo("")
    typer.echo("構築チャネル:")
    for channel_name in SEARCH_CHANNELS:
        typer.echo(f"  {channel_name}")
    typer.echo("")
    typer.echo("出力:")
    typer.echo("  manifest.json")
    typer.echo("  records.jsonl")
    typer.echo("  content_word/")
    typer.echo("  content_ngram/")
    typer.echo("  context_word/")


@app.command()
def search(
    index_dir: Annotated[
        Path,
        typer.Option("--index-dir", help="BM25インデックスの保存先。"),
    ] = Path("artifacts") / "indexes" / "bm25",
    query: Annotated[
        str,
        typer.Option("--query", help="検索クエリ。"),
    ] = "",
    top_k: Annotated[
        int,
        typer.Option("--top-k", help="取得する検索結果数。"),
    ] = 10,
    candidate_multiplier: Annotated[
        int,
        typer.Option("--candidate-multiplier", help="各チャネルで取得する候補倍率。"),
    ] = 5,
    rrf_k: Annotated[
        int,
        typer.Option("--rrf-k", help="RRFの順位緩和パラメータ。"),
    ] = 60,
    preview_chars: Annotated[
        int,
        typer.Option("--preview-chars", help="標準出力に表示する本文プレビュー文字数。"),
    ] = 300,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="検索結果JSONの保存先。"),
    ] = None,
) -> None:
    """保存済みBM25インデックスを検索する。"""
    try:
        if preview_chars < 0:
            raise ValueError("preview_charsは0以上である必要があります。")
        loaded_index = load_bm25_index(index_dir)
        retriever = Bm25Retriever(
            loaded_index,
            candidate_multiplier=candidate_multiplier,
            rrf_k=rrf_k,
        )
        search_results = retriever.search(query, top_k=top_k)
        if output is not None:
            save_search_results(output, query=query, top_k=top_k, results=search_results)
    except (RetrievalIndexError, SearchInputError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    typer.echo(f"検索語: {query}")
    typer.echo(f"取得件数: {len(search_results)}")
    typer.echo("")
    for result in search_results:
        typer.echo(f"{result.rank}. score={result.score:.6f}")
        _echo_display(f"   file: {result.relative_path}")
        _echo_display(f"   locator: {result.locator}")
        _echo_display(f"   parser: {result.parser_name}")
        _echo_display(f"   unit: {result.unit_type}")
        channels = ", ".join(
            f"{channel_name}={rank}" for channel_name, rank in result.channel_ranks.items()
        )
        _echo_display(f"   channels: {channels}")
        _echo_display(f"   preview: {_preview_text(result.text, preview_chars)}")
        typer.echo("")


def _echo_display(text: str) -> None:
    """Windows端末でも分解済み日本語で落ちにくい表示に寄せる。"""
    typer.echo(unicodedata.normalize("NFC", text))


def _preview_text(text: str, preview_chars: int) -> str:
    """標準出力へ本文全体を出さないためのプレビューを作る。"""
    if preview_chars == 0:
        return ""
    normalized = unicodedata.normalize("NFC", text.replace("\n", " "))
    if len(normalized) <= preview_chars:
        return normalized
    return normalized[:preview_chars] + "..."


@app.command()
def evaluate_search(
    queries: Annotated[
        Path,
        typer.Option("--queries", help="検索評価用JSONLへのパス。"),
    ],
    index_dir: Annotated[
        Path,
        typer.Option("--index-dir", help="BM25インデックスの保存先。"),
    ] = Path("artifacts") / "indexes" / "bm25",
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="検索評価結果の保存先。"),
    ] = Path("artifacts") / "search_evaluation",
    top_k: Annotated[
        int,
        typer.Option("--top-k", help="質問ごとに取得する検索結果数。"),
    ] = 10,
    candidate_multiplier: Annotated[
        int,
        typer.Option("--candidate-multiplier", help="各チャネルで取得する候補倍率。"),
    ] = 5,
    rrf_k: Annotated[
        int,
        typer.Option("--rrf-k", help="RRFの順位緩和パラメータ。"),
    ] = 60,
    preview_chars: Annotated[
        int,
        typer.Option("--preview-chars", help="レビュー用プレビュー文字数。"),
    ] = 300,
    report_results_per_query: Annotated[
        int,
        typer.Option("--report-results-per-query", help="report.mdに表示する質問ごとの結果数。"),
    ] = 5,
) -> None:
    """BM25検索を複数質問で一括評価する。"""
    try:
        _validate_evaluate_search_options(
            top_k=top_k,
            candidate_multiplier=candidate_multiplier,
            rrf_k=rrf_k,
            preview_chars=preview_chars,
            report_results_per_query=report_results_per_query,
        )
        evaluation_queries = load_search_evaluation_queries(queries)
        query_file_sha256 = calculate_query_file_sha256(queries)
        loaded_index = load_bm25_index(index_dir)
        index_source_sha256 = _index_source_sha256(loaded_index.manifest)
        retriever = Bm25Retriever(
            loaded_index,
            candidate_multiplier=candidate_multiplier,
            rrf_k=rrf_k,
        )
        evaluation_result = SearchEvaluationService(retriever).evaluate(
            evaluation_queries,
            top_k=top_k,
            index_source_sha256=index_source_sha256,
            query_file_sha256=query_file_sha256,
            candidate_multiplier=candidate_multiplier,
            rrf_k=rrf_k,
            preview_chars=preview_chars,
            report_results_per_query=report_results_per_query,
        )
        save_search_evaluation_result(evaluation_result, output_dir)
    except (
        RetrievalIndexError,
        SearchEvaluationInputError,
        SearchInputError,
        ValueError,
    ) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    summary = evaluation_result.summary
    typer.echo("検索評価を完了しました")
    typer.echo("")
    typer.echo(f"質問数: {summary.total_queries}")
    typer.echo(f"自動評価対象: {summary.auto_evaluated_queries}")
    typer.echo(f"目視確認対象: {summary.manual_review_queries}")
    typer.echo("")
    typer.echo(
        f"Hit@1: {summary.hit_at_1_count}/{summary.auto_evaluated_queries} "
        f"({summary.hit_at_1_rate:.2%})"
    )
    typer.echo(
        f"Hit@3: {summary.hit_at_3_count}/{summary.auto_evaluated_queries} "
        f"({summary.hit_at_3_rate:.2%})"
    )
    typer.echo(
        f"Hit@5: {summary.hit_at_5_count}/{summary.auto_evaluated_queries} "
        f"({summary.hit_at_5_rate:.2%})"
    )
    typer.echo(
        f"Hit@10: {summary.hit_at_10_count}/{summary.auto_evaluated_queries} "
        f"({summary.hit_at_10_rate:.2%})"
    )
    typer.echo(f"MRR: {summary.mean_reciprocal_rank:.4f}")
    typer.echo("")
    typer.echo("出力:")
    typer.echo("  summary.json")
    typer.echo("  query_results.jsonl")
    typer.echo("  review.csv")
    typer.echo("  report.md")


def _validate_evaluate_search_options(
    *,
    top_k: int,
    candidate_multiplier: int,
    rrf_k: int,
    preview_chars: int,
    report_results_per_query: int,
) -> None:
    """検索評価CLIの数値オプションを検証する。"""
    if top_k <= 0:
        raise ValueError("top_kは1以上である必要があります。")
    if candidate_multiplier <= 0:
        raise ValueError("candidate_multiplierは1以上である必要があります。")
    if rrf_k <= 0:
        raise ValueError("rrf_kは1以上である必要があります。")
    if preview_chars < 0:
        raise ValueError("preview_charsは0以上である必要があります。")
    if report_results_per_query < 0:
        raise ValueError("report_results_per_queryは0以上である必要があります。")
    if report_results_per_query > top_k:
        raise ValueError("report_results_per_queryはtop_k以下である必要があります。")


def _index_source_sha256(manifest: Mapping[str, object]) -> str:
    """BM25 manifestから入力chunks.jsonlのSHA-256を取得する。"""
    value = manifest.get("source_sha256")
    if not isinstance(value, str):
        raise ValueError("manifest.source_sha256が文字列ではありません。")
    return value


@app.command()
def diagnose_documents(
    source: Annotated[
        Path,
        typer.Option("--source", help="診断対象の共有ドライブルートディレクトリ。"),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="文書診断成果物の保存先。"),
    ] = Path("artifacts") / "document_diagnostics",
    formats: Annotated[
        str,
        typer.Option("--formats", help="診断対象形式のカンマ区切り指定。"),
    ] = "pdf",
    sample_pages: Annotated[
        int,
        typer.Option("--sample-pages", help="pypdfでテキスト抽出を試す最大ページ数。"),
    ] = 3,
    try_docling: Annotated[
        bool,
        typer.Option("--try-docling", help="PDF診断時にDocling default_localを試行する。"),
    ] = False,
    diagnose_ocr: Annotated[
        bool,
        typer.Option("--diagnose-ocr/--no-diagnose-ocr", help="Tesseract OCR環境を診断する。"),
    ] = True,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="既存の診断出力を置き換える。"),
    ] = False,
) -> None:
    """文書入力とローカル変換環境を診断する。"""
    try:
        parsed_formats = parse_diagnostic_formats(formats)
        diagnostic_report = DocumentDiagnosticService(
            docling_adapter_factory=create_docling_conversion_adapter,
        ).diagnose(
            source,
            formats=parsed_formats,
            sample_pages=sample_pages,
            try_docling=try_docling,
            diagnose_ocr=diagnose_ocr,
        )
        save_document_diagnostic_report(diagnostic_report, output_dir, overwrite=overwrite)
    except (
        DoclingConfigurationError,
        DocumentDiagnosticInputError,
        DocumentDiagnosticOutputError,
        FileNotFoundError,
        NotADirectoryError,
        ValueError,
    ) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    summary = diagnostic_report.summary
    typer.echo("文書入力・環境診断を完了しました")
    typer.echo("")
    typer.echo(f"探索ルート: {source.resolve()}")
    typer.echo(f"PDF候補数: {summary.candidate_files}")
    typer.echo(f"PDF診断数: {summary.diagnosed_files}")
    typer.echo(f"Office一時ファイル除外数: {summary.ignored_files}")
    typer.echo(f"pypdf読取可能: {summary.pypdf_readable}")
    typer.echo(f"pypdf読取不可: {summary.pypdf_unreadable}")
    typer.echo(f"Docling試行: {summary.docling_attempted}")
    typer.echo(f"Docling成功: {summary.docling_success}")
    typer.echo(f"Docling失敗: {summary.docling_failed}")
    typer.echo(f"OCR診断: {summary.ocr_diagnosis or '未実行'}")
    typer.echo("")
    typer.echo("出力:")
    typer.echo("  manifest.json")
    typer.echo("  pdf_results.jsonl")
    typer.echo("  ocr_environment.json")
    typer.echo("  ignored.jsonl")
    typer.echo("  summary.json")
    typer.echo("  report.md")


@app.command()
def docling_poc(
    source: Annotated[
        Path,
        typer.Option("--source", help="共有ドライブのルートディレクトリ。"),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Docling PoC成果物の保存先。"),
    ] = Path("artifacts") / "docling_poc",
    formats: Annotated[
        str,
        typer.Option("--formats", help="対象形式のカンマ区切り指定。"),
    ] = "docx,pptx,pdf,xlsx,png",
    samples_per_format: Annotated[
        int,
        typer.Option("--samples-per-format", help="形式ごとの代表サンプル数。"),
    ] = 5,
    profiles: Annotated[
        str,
        typer.Option("--profiles", help="変換profileのカンマ区切り指定。"),
    ] = "default_local,japanese_ocr",
    timeout_seconds: Annotated[
        int,
        typer.Option("--timeout-seconds", help="Doclingの文書タイムアウト秒数。"),
    ] = 180,
    preview_chars: Annotated[
        int,
        typer.Option("--preview-chars", help="レビュー用プレビュー文字数。"),
    ] = 300,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="既存PoC出力を置き換える。"),
    ] = False,
) -> None:
    """未対応形式に対するDocling適用可否を形式別に評価する。"""
    try:
        parsed_formats = parse_formats(formats)
        parsed_profiles = parse_profiles(profiles)
        adapter = create_docling_conversion_adapter()
        poc_run = DoclingPocService(adapter).run_from_root(
            source,
            formats=parsed_formats,
            samples_per_format=samples_per_format,
            profiles=parsed_profiles,
            timeout_seconds=timeout_seconds,
            preview_chars=preview_chars,
        )
        save_docling_poc_run(poc_run, output_dir, overwrite=overwrite)
    except (
        DoclingConfigurationError,
        DoclingPocInputError,
        DoclingPocOutputError,
        FileNotFoundError,
        NotADirectoryError,
        ValueError,
    ) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error

    summary = poc_run.summary
    typer.echo("Docling形式別PoCを完了しました")
    typer.echo("")
    typer.echo("候補ファイル:")
    for suffix, count in summary.candidate_counts_by_suffix.items():
        typer.echo(f"  {suffix.upper().lstrip('.')}: {count}")
    typer.echo("")
    typer.echo("選択ファイル:")
    for suffix, count in summary.selected_counts_by_suffix.items():
        typer.echo(f"  {suffix.upper().lstrip('.')}: {count}")
    typer.echo("")
    typer.echo(f"変換実行数: {summary.executed_conversions}")
    typer.echo(f"成功: {summary.status_counts.get('success', 0)}")
    typer.echo(f"部分成功: {summary.status_counts.get('partial_success', 0)}")
    typer.echo(f"失敗: {summary.status_counts.get('failed', 0)}")
    typer.echo(f"タイムアウト: {summary.status_counts.get('timeout', 0)}")
    typer.echo(f"スキップ: {summary.status_counts.get('skipped', 0)}")
    typer.echo("")
    typer.echo("出力:")
    typer.echo("  manifest.json")
    typer.echo("  selection.jsonl")
    typer.echo("  results.jsonl")
    typer.echo("  errors.jsonl")
    typer.echo("  summary.json")
    typer.echo("  review.csv")
    typer.echo("  report.md")
    typer.echo("  converted/")


def create_docling_conversion_adapter() -> DoclingConversionAdapter:
    """CLIから使うDoclingアダプターを作成する。"""
    return DoclingConversionAdapter()
