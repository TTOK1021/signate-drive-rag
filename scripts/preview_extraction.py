"""実データに対して文書抽出結果を少量プレビューする検証スクリプト。"""

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from signate_drive_rag.domain import ExtractedDocument, SourceFile
from signate_drive_rag.ingestion.discovery import discover_files
from signate_drive_rag.ingestion.parser_registry import create_default_parser_registry

DEFAULT_SUFFIXES = (".md", ".json", ".ipynb")
DEFAULT_ROOT = Path("share") / "共有ドライブ"
DEFAULT_REPORT_PATH = Path("artifacts") / "runs" / "extraction_preview_report.json"


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="実データから少量のファイルを抽出し、単位数やlocatorを確認します。"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="探索ルート。未指定時はSOURCE_ROOT、なければshare/共有ドライブを使用します。",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="拡張子ごとに抽出する最大ファイル数。",
    )
    parser.add_argument(
        "--suffix",
        action="append",
        choices=DEFAULT_SUFFIXES,
        help="対象拡張子。複数指定可。未指定時は.md/.json/.ipynbを対象にします。",
    )
    parser.add_argument(
        "--locator-limit",
        type=int,
        default=8,
        help="ファイルごとに表示するlocatorの最大数。",
    )
    parser.add_argument(
        "--text-preview-chars",
        type=int,
        default=80,
        help="先頭unit本文のプレビュー文字数。0で非表示。",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="抽出候補と実際に読み取ったファイルの差分を保存するJSONパス。",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="JSONレポートを書き出さず、標準出力のみ表示します。",
    )
    return parser.parse_args()


def resolve_root(root: Path | None) -> Path:
    """引数、環境変数、既定相対パスの順で探索ルートを決定する。"""
    if root is not None:
        return root

    load_dotenv(dotenv_path=Path(".env"))
    source_root = os.getenv("SOURCE_ROOT")
    if source_root:
        return Path(source_root)

    return DEFAULT_ROOT


def main() -> None:
    """抽出プレビューを実行する。"""
    configure_standard_streams()
    args = parse_args()
    root = resolve_root(args.root)
    suffixes = tuple(args.suffix) if args.suffix is not None else DEFAULT_SUFFIXES

    source_files = discover_files(root)

    print(f"探索ルート: {root.resolve()}")
    print(f"対象拡張子: {', '.join(suffixes)}")
    print(f"各拡張子の最大件数: {args.limit}")

    total_errors = 0
    report: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "root": str(root.resolve()),
        "suffixes": list(suffixes),
        "limit": args.limit,
        "suffix_reports": [],
    }
    suffix_reports: list[dict[str, object]] = []
    for suffix in suffixes:
        matching_files = [
            source_file for source_file in source_files if source_file.suffix == suffix
        ]
        selected_files = matching_files[: args.limit]
        unselected_files = matching_files[args.limit :]
        print("")
        print(f"== {suffix} ==")
        print(f"候補ファイル数: {len(matching_files)}")
        print(f"抽出対象数: {len(selected_files)}")

        file_summaries, errors = preview_files(
            selected_files,
            locator_limit=args.locator_limit,
            text_preview_chars=args.text_preview_chars,
        )
        total_errors += len(errors)
        print(f"例外数: {len(errors)}")
        print(f"未抽出数(limit超過): {len(unselected_files)}")
        for error in errors:
            print(f"  ERROR {error['path']} | {error['error_type']}: {error['message']}")

        suffix_reports.append(
            {
                "suffix": suffix,
                "candidate_count": len(matching_files),
                "selected_count": len(selected_files),
                "extracted_count": len(file_summaries),
                "error_count": len(errors),
                "unselected_count": len(unselected_files),
                "candidate_files": source_file_paths(matching_files),
                "selected_files": source_file_paths(selected_files),
                "extracted_files": [summary["path"] for summary in file_summaries],
                "error_files": [error["path"] for error in errors],
                "unselected_files": source_file_paths(unselected_files),
                "file_summaries": file_summaries,
                "errors": errors,
            }
        )

    print("")
    print(f"総例外数: {total_errors}")
    report["total_error_count"] = total_errors
    report["suffix_reports"] = suffix_reports
    if not args.no_report:
        write_report(report, args.report)
        print(f"レポート: {args.report}")


def preview_files(
    source_files: Sequence[SourceFile],
    locator_limit: int,
    text_preview_chars: int,
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """ファイルごとの抽出結果概要を表示し、レポート用情報を返す。"""
    registry = create_default_parser_registry()
    file_summaries: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []

    for source_file in source_files:
        try:
            parser = registry.find_parser(source_file)
            document = parser.parse(source_file)
        except Exception as error:
            # 検証用途では1件の失敗で全体を止めず、例外種別と対象ファイルを一覧化する。
            errors.append(
                {
                    "path": source_file.relative_path.as_posix(),
                    "error_type": type(error).__name__,
                    "message": str(error),
                }
            )
            continue

        file_summary = build_document_summary(
            source_file,
            document,
            locator_limit=locator_limit,
        )
        print_document_summary(file_summary, text_preview_chars=text_preview_chars)
        file_summaries.append(file_summary)

    return file_summaries, errors


def build_document_summary(
    source_file: SourceFile,
    document: ExtractedDocument,
    locator_limit: int,
) -> dict[str, object]:
    """1ファイル分の抽出概要をレポート可能な辞書にする。"""
    unit_type_counts = Counter(unit.unit_type for unit in document.units)
    total_chars = sum(len(unit.text) for unit in document.units)
    empty_units = sum(1 for unit in document.units if unit.text == "")
    missing_locator_units = sum(1 for unit in document.units if unit.locator is None)
    duplicated_locator_count = count_duplicated_locators(document)
    locators = [unit.locator for unit in document.units[:locator_limit]]
    first_text = document.units[0].text if document.units else ""

    return {
        "path": source_file.relative_path.as_posix(),
        "parser": document.parser_name,
        "unit_count": len(document.units),
        "char_count": total_chars,
        "unit_types": dict(sorted(unit_type_counts.items())),
        "empty_unit_count": empty_units,
        "missing_locator_unit_count": missing_locator_units,
        "duplicated_locator_count": duplicated_locator_count,
        "locators": locators,
        "first_text": first_text,
    }


def print_document_summary(
    summary: dict[str, object],
    text_preview_chars: int,
) -> None:
    """1ファイル分の抽出概要を表示する。"""
    print("")
    print(summary["path"])
    print(f"  parser: {summary['parser']}")
    print(f"  units: {summary['unit_count']}")
    print(f"  chars: {summary['char_count']}")
    print(f"  unit_types: {summary['unit_types']}")
    print(f"  empty_units: {summary['empty_unit_count']}")
    print(f"  missing_locator_units: {summary['missing_locator_unit_count']}")
    print(f"  duplicated_locator_count: {summary['duplicated_locator_count']}")
    print(f"  locators: {summary['locators']}")
    first_text = summary["first_text"]
    if text_preview_chars > 0 and isinstance(first_text, str) and first_text:
        preview = first_text[:text_preview_chars].replace("\n", "\\n")
        print(f"  first_text: {preview}")


def count_duplicated_locators(document: ExtractedDocument) -> int:
    """locator重複数を数える。"""
    locators = [unit.locator for unit in document.units if unit.locator is not None]
    locator_counts = Counter(locators)
    return sum(count - 1 for count in locator_counts.values() if count > 1)


def source_file_paths(source_files: Sequence[SourceFile]) -> list[str]:
    """SourceFileの相対パス一覧を返す。"""
    return [source_file.relative_path.as_posix() for source_file in source_files]


def write_report(report: dict[str, object], report_path: Path) -> None:
    """抽出プレビューの差分レポートをJSONで保存する。"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def configure_standard_streams() -> None:
    """Windows端末でも日本語パスを表示できるよう標準ストリームをUTF-8へ寄せる。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    main()
