"""コマンドラインからRAG処理を実行するための入口。"""

import json
import os
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from signate_drive_rag.domain import SourceFile
from signate_drive_rag.ingestion import discover_files

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

    source_files = discover_files(source_root)
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

    if manifest is not None:
        write_manifest_jsonl(source_files, manifest)
        typer.echo("")
        typer.echo(f"manifest: {manifest}")
