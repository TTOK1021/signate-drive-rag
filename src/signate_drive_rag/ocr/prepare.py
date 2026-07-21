"""EasyOCRモデルを明示的に準備しmanifestへ記録する処理。"""

import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any


class OcrModelPrepareError(RuntimeError):
    """OCRモデル準備に失敗した場合の例外。"""


def prepare_easyocr_models(
    *,
    model_dir: Path,
    languages: tuple[str, ...],
    gpu: bool,
    overwrite: bool,
) -> dict[str, Any]:
    """モデルダウンロードはこの明示コマンドだけで許可する。"""
    manifest_path = model_dir / "manifest.json"
    if manifest_path.exists() and not overwrite:
        raise OcrModelPrepareError(
            "manifest.jsonが既に存在します。"
            f"上書きする場合は--overwriteを指定してください: {manifest_path}"
        )

    model_dir.mkdir(parents=True, exist_ok=True)
    try:
        import easyocr  # type: ignore[import-untyped]

        easyocr.Reader(
            list(languages),
            gpu=gpu,
            model_storage_directory=str(model_dir),
            download_enabled=True,
        )
    except Exception as error:
        raise OcrModelPrepareError(f"EasyOCRモデル準備に失敗しました: {error}") from error

    manifest = _build_manifest(model_dir, languages)
    temporary_path = manifest_path.with_name("manifest.json.tmp")
    temporary_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(manifest_path)
    return manifest


def _build_manifest(model_dir: Path, languages: tuple[str, ...]) -> dict[str, Any]:
    files = [
        path
        for path in sorted(
            model_dir.rglob("*"),
            key=lambda item: item.relative_to(model_dir).as_posix(),
        )
        if path.is_file() and path.name != "manifest.json"
    ]
    return {
        "schema_version": 1,
        "engine": "easyocr",
        "easyocr_version": importlib.metadata.version("easyocr"),
        "languages": list(languages),
        "model_files": [
            {
                "filename": path.relative_to(model_dir).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "source": "easyocr model storage",
                "license": "Apache-2.0 or upstream model license",
            }
            for path in files
        ],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
