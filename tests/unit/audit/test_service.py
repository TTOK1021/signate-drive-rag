"""監査サービスの単体テスト。"""

import pytest

from signate_drive_rag.audit.models import AuditDocument, AuditUnit
from signate_drive_rag.audit.service import AuditService, distribution_statistics


def unit(
    text: str,
    *,
    unit_type: str = "markdown_section",
    locator: str | None = "line:1-1",
) -> AuditUnit:
    """テスト用AuditUnitを作成する。"""
    return AuditUnit(unit_type=unit_type, text=text, locator=locator, metadata={})


def document(
    relative_path: str,
    *,
    parser_name: str = "markdown",
    size_bytes: int = 100,
    units: tuple[AuditUnit, ...] = (unit("本文"),),
) -> AuditDocument:
    """テスト用AuditDocumentを作成する。"""
    return AuditDocument(
        relative_path=relative_path,
        name=relative_path.rsplit("/", maxsplit=1)[-1],
        suffix="." + relative_path.rsplit(".", maxsplit=1)[-1],
        size_bytes=size_bytes,
        parser_name=parser_name,
        units=units,
    )


def issue_types(result) -> list[str]:
    """issue_typeの一覧を取得する。"""
    return [issue.issue_type for issue in result.issues]


def test_audit_service_summarizes_documents_units_and_characters() -> None:
    """文書数・unit数・文字数を集計できる。"""
    result = AuditService().audit(
        [
            document("b.md", units=(unit("abc"),)),
            document("a.md", units=(unit("de"), unit("f"))),
        ]
    )

    assert result.summary.documents == 2
    assert result.summary.total_units == 3
    assert result.summary.total_characters == 6
    assert list(result.summary.by_parser) == ["markdown"]


def test_audit_service_detects_documents_with_no_units_by_source_size() -> None:
    """抽出単位0件の文書を原本サイズに応じた重大度で検出する。"""
    result = AuditService().audit(
        [
            document("empty.md", size_bytes=0, units=()),
            document("non_empty.md", size_bytes=10, units=()),
        ]
    )

    severities = {
        issue.relative_path: issue.severity
        for issue in result.issues
        if issue.issue_type == "document_has_no_units"
    }
    assert severities == {"empty.md": "info", "non_empty.md": "warning"}
    assert result.summary.documents_with_no_units == 2
    assert result.summary.documents_with_no_text == 2


def test_audit_service_detects_empty_unit() -> None:
    """textが空文字のunitを検出する。"""
    result = AuditService().audit([document("empty-unit.md", units=(unit(""),))])

    assert "empty_unit" in issue_types(result)
    assert result.summary.empty_units == 1


@pytest.mark.parametrize(
    ("audit_unit", "expected_issue_type"),
    [
        (unit("md", unit_type="markdown_section", locator=None), "missing_required_locator"),
        (unit("md", unit_type="markdown_section", locator="row:1"), "invalid_locator_format"),
        (unit("json", unit_type="json_value", locator=None), "missing_required_locator"),
        (unit("cell", unit_type="notebook_cell", locator="line:1"), "invalid_locator_format"),
        (unit("out", unit_type="notebook_output", locator=None), "missing_required_locator"),
        (unit("head", unit_type="table_header", locator=None), "missing_required_locator"),
        (unit("row", unit_type="table_row", locator="cell:1"), "invalid_locator_format"),
    ],
)
def test_audit_service_validates_required_locator(
    audit_unit: AuditUnit,
    expected_issue_type: str,
) -> None:
    """構造化unitのlocator欠落と形式不正を検出する。"""
    result = AuditService().audit([document("structured.dat", units=(audit_unit,))])

    assert expected_issue_type in issue_types(result)
    assert result.summary.units_without_required_locator == 1


def test_audit_service_accepts_json_root_locator_and_plain_text_without_locator() -> None:
    """JSONルート値とPlainTextのlocatorなしを問題扱いしない。"""
    result = AuditService().audit(
        [
            document(
                "root.json",
                parser_name="json",
                units=(unit("root", unit_type="json_value", locator=""),),
            ),
            document(
                "plain.txt",
                parser_name="plain_text",
                units=(unit("plain", unit_type="text", locator=None),),
            ),
        ]
    )

    assert result.summary.units_without_required_locator == 0


def test_audit_service_detects_duplicate_text_only_within_same_document() -> None:
    """同一文書内の完全一致重複だけを検出する。"""
    result = AuditService().audit(
        [
            document("dup.md", units=(unit("same"), unit(""), unit("same"), unit(""))),
            document("other.md", units=(unit("same"),)),
        ]
    )

    duplicate_issues = [
        issue for issue in result.issues if issue.issue_type == "duplicate_unit_text"
    ]
    assert len(duplicate_issues) == 1
    assert duplicate_issues[0].relative_path == "dup.md"
    assert duplicate_issues[0].unit_index == 2
    assert result.summary.duplicate_units == 1


def test_audit_service_detects_large_unit_above_threshold_only() -> None:
    """しきい値を超えたunitだけをlarge_unitとして検出する。"""
    result = AuditService(large_unit_chars=3).audit(
        [document("large.md", units=(unit("abc"), unit("abcd")))]
    )

    large_issues = [issue for issue in result.issues if issue.issue_type == "large_unit"]
    assert len(large_issues) == 1
    assert large_issues[0].unit_index == 1
    assert result.summary.large_units == 1


def test_distribution_statistics_uses_linear_interpolation_for_percentile() -> None:
    """分布統計と95パーセンタイルの計算仕様を固定する。"""
    statistics = distribution_statistics([0, 10])

    assert statistics.count == 2
    assert statistics.minimum == 0
    assert statistics.maximum == 10
    assert statistics.mean == 5.0
    assert statistics.median == 5.0
    assert statistics.percentile_95 == 9.5


def test_distribution_statistics_returns_zero_values_for_empty_input() -> None:
    """0件時の分布統計は定義済みの0値を返す。"""
    statistics = distribution_statistics([])

    assert statistics.count == 0
    assert statistics.minimum == 0
    assert statistics.maximum == 0
    assert statistics.mean == 0.0
    assert statistics.median == 0.0
    assert statistics.percentile_95 == 0.0


def test_audit_service_summarizes_issues_by_severity_and_type() -> None:
    """issue件数をseverity別とissue_type別に集計する。"""
    result = AuditService(large_unit_chars=1).audit(
        [document("issues.md", units=(unit(""), unit("abc", locator=None)))]
    )

    assert result.summary.issues_by_severity["info"] >= 1
    assert result.summary.issues_by_severity["warning"] >= 1
    assert result.summary.issues_by_type["empty_unit"] == 1
    assert result.summary.issues_by_type["large_unit"] == 1


def test_audit_service_builds_parser_statistics_in_deterministic_order() -> None:
    """パーサー別の分布統計をパーサー名順で作成する。"""
    result = AuditService().audit(
        [
            document("b.txt", parser_name="plain_text", units=(unit("abc", unit_type="text"),)),
            document(
                "a.json", parser_name="json", units=(unit("x", unit_type="json_value", locator=""),)
            ),
        ]
    )

    assert list(result.summary.by_parser) == ["json", "plain_text"]
    assert result.summary.by_parser["plain_text"].document_character_statistics.maximum == 3
    assert result.summary.by_parser["json"].unit_character_statistics.maximum == 1


def test_audit_service_selects_samples_deterministically_per_parser() -> None:
    """3件指定でパーサーごとに先頭・中央・末尾を選択する。"""
    documents = [
        document(f"markdown/{index}.md", parser_name="markdown", units=(unit(str(index)),))
        for index in range(5)
    ] + [
        document(
            f"json/{index}.json",
            parser_name="json",
            units=(unit(str(index), unit_type="json_value", locator=""),),
        )
        for index in range(2)
    ]

    result = AuditService(samples_per_parser=3).audit(documents)

    assert [sample.relative_path for sample in result.samples] == [
        "json/0.json",
        "json/1.json",
        "markdown/0.md",
        "markdown/2.md",
        "markdown/4.md",
    ]


def test_audit_service_selects_sample_units_and_previews() -> None:
    """unitも先頭・中央・末尾から選び、プレビュー文字数を適用する。"""
    result = AuditService(samples_per_parser=1, preview_chars=2).audit(
        [
            document(
                "sample.md",
                units=(unit("あいう"), unit("かき"), unit("くけこ"), unit("さしす")),
            )
        ]
    )

    sample = result.samples[0]
    assert [sample_unit.unit_index for sample_unit in sample.sample_units] == [0, 2, 3]
    assert sample.sample_units[0].text_preview == "あい..."
    assert sample.sample_units[1].text_preview == "くけ..."
    assert sample.sample_units[2].text_preview == "さし..."


def test_audit_service_handles_sample_boundaries_and_invalid_options() -> None:
    """サンプル数とプレビュー文字数の境界値を扱う。"""
    assert AuditService(samples_per_parser=0).audit([document("a.md")]).samples == ()
    assert (
        AuditService(samples_per_parser=1, preview_chars=0)
        .audit([document("a.md", units=(unit("abc"),))])
        .samples[0]
        .sample_units[0]
        .text_preview
        == ""
    )
    assert (
        AuditService(samples_per_parser=1, preview_chars=3)
        .audit([document("a.md", units=(unit("abc"),))])
        .samples[0]
        .sample_units[0]
        .text_preview
        == "abc"
    )
    with pytest.raises(ValueError):
        AuditService(samples_per_parser=-1)
    with pytest.raises(ValueError):
        AuditService(preview_chars=-1)
    with pytest.raises(ValueError):
        AuditService(large_unit_chars=-1)
