"""OCR領域を決定的な読み順へ並べ替える処理。"""

from dataclasses import dataclass

from signate_drive_rag.ocr.models import OcrTextRegion


@dataclass(slots=True)
class _OcrLine:
    center_y: float
    height: float
    regions: list[OcrTextRegion]


def order_ocr_regions(regions: tuple[OcrTextRegion, ...]) -> tuple[OcrTextRegion, ...]:
    """上から下、同じ行では左から右の順にOCR領域を並べる。"""
    lines: list[_OcrLine] = []
    for region in sorted(regions, key=lambda item: (_top(item), _left(item), item.order)):
        matching_line = _find_matching_line(lines, region)
        if matching_line is None:
            lines.append(
                _OcrLine(
                    center_y=_center_y(region),
                    height=max(1.0, _height(region)),
                    regions=[region],
                )
            )
            continue
        matching_line.regions.append(region)
        matching_line.center_y = sum(_center_y(item) for item in matching_line.regions) / len(
            matching_line.regions
        )
        matching_line.height = max(matching_line.height, _height(region))

    ordered: list[OcrTextRegion] = []
    for line in sorted(lines, key=lambda item: item.center_y):
        ordered.extend(sorted(line.regions, key=lambda item: (_left(item), item.order)))
    return tuple(
        OcrTextRegion(
            text=region.text,
            confidence=region.confidence,
            bbox_pixels=region.bbox_pixels,
            bbox_normalized=region.bbox_normalized,
            polygon=region.polygon,
            order=index,
        )
        for index, region in enumerate(ordered)
    )


def _find_matching_line(lines: list[_OcrLine], region: OcrTextRegion) -> _OcrLine | None:
    center_y = _center_y(region)
    height = max(1.0, _height(region))
    for line in lines:
        tolerance = max(line.height, height) * 0.60
        if abs(line.center_y - center_y) <= tolerance:
            return line
    return None


def _left(region: OcrTextRegion) -> float:
    return region.bbox_pixels[0]


def _top(region: OcrTextRegion) -> float:
    return region.bbox_pixels[1]


def _height(region: OcrTextRegion) -> float:
    return max(0.0, region.bbox_pixels[3] - region.bbox_pixels[1])


def _center_y(region: OcrTextRegion) -> float:
    return region.bbox_pixels[1] + _height(region) / 2
