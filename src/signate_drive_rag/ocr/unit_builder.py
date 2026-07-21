"""OCR認識領域からExtractedUnitとissueを組み立てる処理。"""

from dataclasses import dataclass
from statistics import mean
from typing import cast

from signate_drive_rag.domain import ExtractedUnit, ExtractionIssue, JsonValue
from signate_drive_rag.ocr.models import OcrImage, OcrOptions, OcrTextRegion

OCR_NO_TEXT = "ocr_no_text"
OCR_LOW_CONFIDENCE = "ocr_low_confidence"
OCR_REGION_METADATA_TRUNCATED = "ocr_region_metadata_truncated"


@dataclass(frozen=True, slots=True)
class OcrUnitBuildResult:
    """OCR unit生成結果と品質情報。"""

    unit: ExtractedUnit | None
    issues: tuple[ExtractionIssue, ...]
    recognized_region_count: int
    included_region_count: int
    excluded_low_confidence_region_count: int
    ocr_text_characters: int
    mean_confidence: float | None
    minimum_confidence: float | None
    maximum_confidence: float | None


def build_ocr_unit_result(
    *,
    image: OcrImage,
    regions: tuple[OcrTextRegion, ...],
    options: OcrOptions,
    unit_type: str,
    locator: str,
    metadata: dict[str, JsonValue],
) -> OcrUnitBuildResult:
    """低信頼領域を除外し、検索用本文と位置metadataを作る。"""
    prepared_regions = [
        _prepared_region(region) for region in regions if _prepared_region(region).text != ""
    ]
    included_regions = [
        region for region in prepared_regions if region.confidence >= options.min_region_confidence
    ]
    excluded_low_confidence_count = len(prepared_regions) - len(included_regions)
    text = _ocr_text(included_regions)
    ocr_text_characters = len(text)
    confidence_values = [region.confidence for region in included_regions]
    mean_confidence = float(mean(confidence_values)) if confidence_values else None
    minimum_confidence = min(confidence_values, default=None)
    maximum_confidence = max(confidence_values, default=None)

    issues: list[ExtractionIssue] = []
    if ocr_text_characters < options.min_text_characters_per_image:
        issues.append(
            _extraction_issue(
                OCR_NO_TEXT,
                message="OCRで検索に使える文字列を抽出できませんでした。",
                locator=locator,
                metadata={
                    "recognized_region_count": len(regions),
                    "included_region_count": len(included_regions),
                    "ocr_text_characters": ocr_text_characters,
                    "threshold": options.min_text_characters_per_image,
                },
            )
        )
        return OcrUnitBuildResult(
            unit=None,
            issues=tuple(issues),
            recognized_region_count=len(regions),
            included_region_count=len(included_regions),
            excluded_low_confidence_region_count=excluded_low_confidence_count,
            ocr_text_characters=ocr_text_characters,
            mean_confidence=mean_confidence,
            minimum_confidence=minimum_confidence,
            maximum_confidence=maximum_confidence,
        )

    if mean_confidence is not None and mean_confidence < options.low_confidence_threshold:
        issues.append(
            _extraction_issue(
                OCR_LOW_CONFIDENCE,
                message="OCR平均信頼度がしきい値未満です。",
                locator=locator,
                metadata={
                    "mean_confidence": mean_confidence,
                    "threshold": options.low_confidence_threshold,
                },
            )
        )

    region_records = [_region_to_metadata(region) for region in included_regions]
    if len(region_records) > options.max_regions_in_metadata:
        region_records = region_records[: options.max_regions_in_metadata]
        issues.append(
            _extraction_issue(
                OCR_REGION_METADATA_TRUNCATED,
                message="OCR領域metadataを上限件数で切り詰めました。",
                locator=locator,
                metadata={
                    "included_region_count": len(included_regions),
                    "max_regions_in_metadata": options.max_regions_in_metadata,
                },
            )
        )

    unit_metadata: dict[str, JsonValue] = {
        **metadata,
        "image_width": image.width,
        "image_height": image.height,
        "image_mode": image.image_mode,
        "ocr_languages": list(options.languages),
        "recognized_region_count": len(regions),
        "included_region_count": len(included_regions),
        "excluded_low_confidence_region_count": excluded_low_confidence_count,
        "mean_confidence": mean_confidence,
        "minimum_confidence": minimum_confidence,
        "maximum_confidence": maximum_confidence,
        "ocr_text_characters": ocr_text_characters,
        "bbox_available": bool(included_regions),
        "regions": cast(list[JsonValue], region_records),
        "source_quality": "ocr",
        "evidence_priority": "auxiliary",
    }
    return OcrUnitBuildResult(
        unit=ExtractedUnit(
            unit_type=unit_type,
            text=text,
            locator=locator,
            metadata=unit_metadata,
        ),
        issues=tuple(issues),
        recognized_region_count=len(regions),
        included_region_count=len(included_regions),
        excluded_low_confidence_region_count=excluded_low_confidence_count,
        ocr_text_characters=ocr_text_characters,
        mean_confidence=mean_confidence,
        minimum_confidence=minimum_confidence,
        maximum_confidence=maximum_confidence,
    )


def normalize_ocr_text(text: str) -> str:
    """OCR文字列は補正せず、検索投入前に危険な制御文字だけを整える。"""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()


def _ocr_text(regions: list[OcrTextRegion]) -> str:
    lines = [f"領域{index}: {region.text}" for index, region in enumerate(regions, start=1)]
    return "\n".join(lines)


def _prepared_region(region: OcrTextRegion) -> OcrTextRegion:
    return OcrTextRegion(
        text=normalize_ocr_text(region.text),
        confidence=region.confidence,
        bbox_pixels=region.bbox_pixels,
        bbox_normalized=region.bbox_normalized,
        polygon=region.polygon,
        order=region.order,
    )


def _region_to_metadata(region: OcrTextRegion) -> dict[str, JsonValue]:
    return {
        "text": region.text,
        "confidence": region.confidence,
        "bbox_pixels": list(region.bbox_pixels),
        "bbox_normalized": list(region.bbox_normalized),
        "polygon": [[x, y] for x, y in region.polygon],
        "order": region.order,
    }


def _extraction_issue(
    issue_type: str,
    *,
    message: str,
    locator: str,
    metadata: dict[str, JsonValue],
) -> ExtractionIssue:
    """循環importを避けるため、issue生成だけを実行時に読み込む。"""
    from signate_drive_rag.ingestion.parsers.extraction_issue import extraction_issue

    return extraction_issue(
        issue_type,
        message=message,
        locator=locator,
        metadata=metadata,
    )
