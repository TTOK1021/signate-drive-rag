"""OCR領域の読み順決定テスト。"""

from signate_drive_rag.ocr.models import OcrTextRegion
from signate_drive_rag.ocr.ordering import order_ocr_regions


def region(text: str, x: float, y: float, *, order: int) -> OcrTextRegion:
    """テスト用OCR領域を作成する。"""
    return OcrTextRegion(
        text=text,
        confidence=0.9,
        bbox_pixels=(x, y, x + 10, y + 10),
        bbox_normalized=(0.0, 0.0, 0.1, 0.1),
        polygon=((x, y), (x + 10, y), (x + 10, y + 10), (x, y + 10)),
        order=order,
    )


def test_order_ocr_regions_sorts_top_to_bottom_and_left_to_right() -> None:
    """OCR領域を上から下、同一行では左から右に並べることを確認する。"""
    ordered = order_ocr_regions(
        (
            region("bottom", 5, 30, order=0),
            region("right", 50, 10, order=1),
            region("left", 5, 12, order=2),
        )
    )

    assert [item.text for item in ordered] == ["left", "right", "bottom"]
    assert [item.order for item in ordered] == [0, 1, 2]
