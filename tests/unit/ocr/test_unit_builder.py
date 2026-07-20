"""OCR unit生成の単体テスト。"""

from signate_drive_rag.ocr.models import OcrImage, OcrOptions, OcrTextRegion
from signate_drive_rag.ocr.unit_builder import build_ocr_unit_result


def image() -> OcrImage:
    """テスト用OCR画像を作成する。"""
    return OcrImage(
        image_array=object(),
        width=100,
        height=50,
        source_kind="png",
        page_number=None,
        image_index=1,
        image_mode="RGB",
    )


def region(text: str, confidence: float, *, order: int) -> OcrTextRegion:
    """テスト用OCR領域を作成する。"""
    return OcrTextRegion(
        text=text,
        confidence=confidence,
        bbox_pixels=(0.0, 0.0, 10.0, 10.0),
        bbox_normalized=(0.0, 0.0, 0.1, 0.2),
        polygon=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        order=order,
    )


def test_build_ocr_unit_result_preserves_regions_and_filters_low_confidence() -> None:
    """低信頼領域を本文から除外し、bboxとpolygonをmetadataへ保持する。"""
    result = build_ocr_unit_result(
        image=image(),
        regions=(region("日本語", 0.9, order=0), region("low", 0.1, order=1)),
        options=OcrOptions(min_region_confidence=0.2),
        unit_type="image_ocr_text",
        locator="image:1",
        metadata={"ocr_engine": "fake"},
    )

    assert result.unit is not None
    assert "日本語" in result.unit.text
    assert "low" not in result.unit.text
    assert result.unit.metadata["recognized_region_count"] == 2
    assert result.unit.metadata["included_region_count"] == 1
    assert result.unit.metadata["excluded_low_confidence_region_count"] == 1
    assert result.unit.metadata["regions"][0]["polygon"] == [
        [0.0, 0.0],
        [10.0, 0.0],
        [10.0, 10.0],
        [0.0, 10.0],
    ]


def test_build_ocr_unit_result_returns_no_text_issue_for_empty_output() -> None:
    """OCR本文が空の場合はunitを作らずocr_no_text issueを返す。"""
    result = build_ocr_unit_result(
        image=image(),
        regions=(region(" ", 0.9, order=0),),
        options=OcrOptions(),
        unit_type="image_ocr_text",
        locator="image:1",
        metadata={},
    )

    assert result.unit is None
    assert [issue.issue_type for issue in result.issues] == ["ocr_no_text"]
