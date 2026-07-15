"""検索テキスト正規化のテスト。"""

from signate_drive_rag.retrieval.normalizer import normalize_text


def test_normalize_text_applies_nfkc_casefold_and_whitespace_rules() -> None:
    """全角英数字、大小文字、改行、空白を検索用に正規化する。"""
    text = (
        "\u3000\uff21\uff22\uff23\t\uff11\uff12\uff13\r\n"
        "Contract  金額\rTASK-001 customer_id 1.5%\u3000"
    )

    normalized = normalize_text(text)

    assert normalized == "abc 123\ncontract 金額\ntask-001 customer_id 1.5%"


def test_normalize_text_keeps_japanese_and_structured_symbols() -> None:
    """日本語やIDに必要な記号を一律削除しない。"""
    normalized = normalize_text("契約金額 TASK-001 customer_id version1.2 2026/07")

    assert "契約金額" in normalized
    assert "task-001" in normalized
    assert "customer_id" in normalized
    assert "version1.2" in normalized
    assert "2026/07" in normalized
    assert normalized == normalize_text("契約金額 TASK-001 customer_id version1.2 2026/07")
