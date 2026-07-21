"""Docling公開APIを使ったPoC用変換アダプター。"""

import logging
from importlib import metadata
from pathlib import Path
from typing import Any, cast

from signate_drive_rag.docling_poc.models import ConversionOutput
from signate_drive_rag.domain.extracted_document import JsonValue

EXPECTED_DOCLING_VERSION = "2.113.0"


class DoclingConfigurationError(RuntimeError):
    """Doclingの実行設定に問題がある場合の例外。"""


class DoclingConversionAdapter:
    """Doclingの依存をPoC内部へ閉じ込めるアダプター。"""

    def __init__(self) -> None:
        """Doclingバージョンを固定してPoC結果の再現性を保つ。"""
        _configure_external_loggers()
        version = metadata.version("docling")
        if version != EXPECTED_DOCLING_VERSION:
            raise DoclingConfigurationError(f"doclingのバージョンが想定と異なります: {version}")
        self._converters: dict[tuple[str, int], Any] = {}

    def convert(
        self,
        source_path: Path,
        *,
        profile: str,
        timeout_seconds: int,
    ) -> ConversionOutput:
        """Doclingで文書をMarkdown・JSON・テキストへ変換する。"""
        converter = self._converter(profile=profile, timeout_seconds=timeout_seconds)
        conversion_result = converter.convert(source_path, raises_on_error=False)
        status = _normalize_status(conversion_result.status)
        errors = tuple(_safe_error_message(error) for error in conversion_result.errors)
        document = conversion_result.document
        if document is None:
            return ConversionOutput(
                status=status,
                markdown="",
                text="",
                json_document={},
                document=None,
                warnings=(),
                errors=errors,
            )

        traverse_pictures = profile == "japanese_ocr"
        markdown = document.export_to_markdown(traverse_pictures=traverse_pictures)
        text = document.export_to_text(traverse_pictures=traverse_pictures)
        json_document = cast(dict[str, JsonValue], document.export_to_dict(mode="json"))
        return ConversionOutput(
            status=status,
            markdown=markdown,
            text=text,
            json_document=json_document,
            document=document,
            warnings=(),
            errors=errors,
        )

    def _converter(self, *, profile: str, timeout_seconds: int) -> Any:
        key = (profile, timeout_seconds)
        if key not in self._converters:
            self._converters[key] = _create_document_converter(
                profile=profile,
                timeout_seconds=timeout_seconds,
            )
        return self._converters[key]


def _create_document_converter(*, profile: str, timeout_seconds: int) -> Any:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
    from docling.document_converter import (
        DocumentConverter,
        ExcelFormatOption,
        ImageFormatOption,
        PdfFormatOption,
        PowerpointFormatOption,
        WordFormatOption,
    )

    allowed_formats = [
        InputFormat.DOCX,
        InputFormat.PPTX,
        InputFormat.PDF,
        InputFormat.XLSX,
        InputFormat.IMAGE,
    ]
    pdf_options = PdfPipelineOptions(
        document_timeout=float(timeout_seconds),
        enable_remote_services=False,
        do_picture_description=False,
        do_table_structure=True,
    )
    image_options = pdf_options
    if profile == "japanese_ocr":
        # Tesseractの言語コードは公式のISO 639-2系コードを使い、推測した短縮形を避ける。
        ocr_options = TesseractCliOcrOptions(
            lang=["jpn", "eng"],
            force_full_page_ocr=True,
        )
        pdf_options = PdfPipelineOptions(
            document_timeout=float(timeout_seconds),
            enable_remote_services=False,
            do_picture_description=False,
            do_table_structure=True,
            do_ocr=True,
            ocr_options=ocr_options,
        )
        image_options = pdf_options
    elif profile != "default_local":
        raise DoclingConfigurationError(f"未知のDocling PoC profileです: {profile}")

    return DocumentConverter(
        allowed_formats=allowed_formats,
        format_options={
            InputFormat.DOCX: WordFormatOption(),
            InputFormat.PPTX: PowerpointFormatOption(),
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
            InputFormat.XLSX: ExcelFormatOption(),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=image_options),
        },
    )


def _configure_external_loggers() -> None:
    """外部ライブラリ由来の原本パス出力を抑える。"""
    for logger_name in ("docling", "rapidocr", "RapidOCR"):
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.CRITICAL)
        logger.propagate = False


def _normalize_status(status: object) -> str:
    value = getattr(status, "value", status)
    if value == "success":
        return "success"
    if value == "partial_success":
        return "partial_success"
    if value == "skipped":
        return "skipped"
    return "failed"


def _safe_error_message(error: object) -> str:
    error_type = type(error).__name__
    message = str(error)
    if len(message) > 500:
        message = message[:500] + "..."
    return f"{error_type}: {message}"
