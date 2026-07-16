"""evaluate-searchコマンドの統合テスト。"""

import json
from pathlib import Path

from typer.testing import CliRunner

from signate_drive_rag.chunking.models import RetrievalChunk
from signate_drive_rag.cli import app
from signate_drive_rag.retrieval.index_builder import build_bm25_index
from signate_drive_rag.retrieval.index_store import save_bm25_index
from signate_drive_rag.retrieval.models import LoadedBm25Index, SearchResult

runner = CliRunner()


def build_test_index(index_dir: Path) -> None:
    """テスト用BM25インデックスを作成する。"""
    chunks = (
        RetrievalChunk(
            chunk_id="contract",
            relative_path="資料/契約.md",
            parser_name="markdown",
            unit_type="markdown_section",
            text="契約金額は100万円です",
            locator="line:1-2",
            source_unit_indices=(0,),
            chunk_index=0,
            metadata={"heading": "契約"},
        ),
        RetrievalChunk(
            chunk_id="analysis",
            relative_path="資料/分析.md",
            parser_name="markdown",
            unit_type="markdown_section",
            text="分析結果 customer_id",
            locator="line:3-4",
            source_unit_indices=(1,),
            chunk_index=1,
            metadata={"heading": "分析"},
        ),
    )
    save_bm25_index(build_bm25_index(chunks, source_sha256="chunks-sha"), index_dir)


def write_queries(path: Path) -> None:
    """テスト用質問JSONLを書き込む。"""
    records = [
        {
            "query_id": "q1",
            "query": "契約金額",
            "query_type": "exact",
            "expected_relevant": [{"relative_path": "資料/契約.md", "locator": None}],
            "notes": "",
        },
        {
            "query_id": "q2",
            "query": "customer_id",
            "query_type": "identifier",
            "expected_relevant": [],
            "notes": "目視",
        },
    ]
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def test_evaluate_search_command_writes_outputs_and_prints_summary(tmp_path: Path) -> None:
    """evaluate-searchコマンドで成果物4ファイルと全体指標を生成する。"""
    index_dir = tmp_path / "index"
    queries_path = tmp_path / "queries.jsonl"
    output_dir = tmp_path / "evaluation"
    build_test_index(index_dir)
    write_queries(queries_path)

    result = runner.invoke(
        app,
        [
            "evaluate-search",
            "--index-dir",
            str(index_dir),
            "--queries",
            str(queries_path),
            "--output-dir",
            str(output_dir),
            "--top-k",
            "10",
            "--candidate-multiplier",
            "2",
            "--rrf-k",
            "30",
            "--preview-chars",
            "20",
            "--report-results-per-query",
            "2",
        ],
    )

    assert result.exit_code == 0
    assert "検索評価を完了しました" in result.stdout
    assert "質問数: 2" in result.stdout
    assert "Hit@1: 1/1 (100.00%)" in result.stdout
    for file_name in ("summary.json", "query_results.jsonl", "review.csv", "report.md"):
        assert (output_dir / file_name).exists()


def test_evaluate_search_command_handles_empty_query_set(tmp_path: Path) -> None:
    """空質問セットでも正常に評価成果物を生成する。"""
    index_dir = tmp_path / "index"
    queries_path = tmp_path / "queries.jsonl"
    output_dir = tmp_path / "evaluation"
    build_test_index(index_dir)
    queries_path.write_text("", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "evaluate-search",
            "--index-dir",
            str(index_dir),
            "--queries",
            str(queries_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    assert "質問数: 0" in result.stdout
    assert (output_dir / "query_results.jsonl").read_text(encoding="utf-8") == ""


def test_evaluate_search_command_rejects_missing_inputs_and_invalid_options(
    tmp_path: Path,
) -> None:
    """存在しない入力や不正な数値オプションではエラーになる。"""
    index_dir = tmp_path / "index"
    queries_path = tmp_path / "queries.jsonl"
    build_test_index(index_dir)
    write_queries(queries_path)

    assert (
        runner.invoke(
            app,
            [
                "evaluate-search",
                "--index-dir",
                str(index_dir),
                "--queries",
                str(tmp_path / "missing.jsonl"),
            ],
        ).exit_code
        == 2
    )
    assert (
        runner.invoke(
            app,
            [
                "evaluate-search",
                "--index-dir",
                str(tmp_path / "missing"),
                "--queries",
                str(queries_path),
            ],
        ).exit_code
        == 2
    )
    assert (
        runner.invoke(
            app,
            [
                "evaluate-search",
                "--index-dir",
                str(index_dir),
                "--queries",
                str(queries_path),
                "--top-k",
                "0",
            ],
        ).exit_code
        == 2
    )
    assert (
        runner.invoke(
            app,
            [
                "evaluate-search",
                "--index-dir",
                str(index_dir),
                "--queries",
                str(queries_path),
                "--top-k",
                "1",
                "--report-results-per-query",
                "2",
            ],
        ).exit_code
        == 2
    )


def test_evaluate_search_command_loads_index_once(tmp_path: Path, monkeypatch) -> None:
    """BM25インデックスを質問ごとに読み直さない。"""
    queries_path = tmp_path / "queries.jsonl"
    output_dir = tmp_path / "evaluation"
    write_queries(queries_path)
    load_count = 0

    def fake_load_bm25_index(index_dir: Path) -> LoadedBm25Index:
        nonlocal load_count
        load_count += 1
        return LoadedBm25Index(
            manifest={"source_sha256": "index"},
            records=(),
            channel_indexes={},
        )

    class FakeBm25Retriever:
        """CLI接続確認用Retriever。"""

        def __init__(
            self,
            index: LoadedBm25Index,
            *,
            candidate_multiplier: int,
            rrf_k: int,
        ) -> None:
            self.index = index

        def search(self, query: str, top_k: int) -> tuple[SearchResult, ...]:
            return (
                SearchResult(
                    rank=1,
                    chunk_id="chunk",
                    relative_path="資料/契約.md",
                    locator=None,
                    parser_name="markdown",
                    unit_type="markdown_section",
                    score=1.0,
                    channel_ranks={"content_word": 1},
                    text=query,
                    metadata={},
                ),
            )

    monkeypatch.setattr("signate_drive_rag.cli.load_bm25_index", fake_load_bm25_index)
    monkeypatch.setattr("signate_drive_rag.cli.Bm25Retriever", FakeBm25Retriever)

    result = runner.invoke(
        app,
        [
            "evaluate-search",
            "--index-dir",
            str(tmp_path / "index"),
            "--queries",
            str(queries_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    assert load_count == 1
