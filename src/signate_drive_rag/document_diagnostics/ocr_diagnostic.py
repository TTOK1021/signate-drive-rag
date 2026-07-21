"""Tesseract OCR実行環境の診断。"""

import shutil
import subprocess

from signate_drive_rag.document_diagnostics.models import OcrEnvironmentDiagnostic

REQUIRED_TESSERACT_LANGUAGES = ("eng", "jpn")


def diagnose_tesseract_environment(timeout_seconds: int = 5) -> OcrEnvironmentDiagnostic:
    """Tesseract実行ファイルと言語データの利用可否を診断する。"""
    executable_path = shutil.which("tesseract")
    if executable_path is None:
        return OcrEnvironmentDiagnostic(
            engine="tesseract",
            executable_found=False,
            executable_path=None,
            version=None,
            available_languages=(),
            required_languages=REQUIRED_TESSERACT_LANGUAGES,
            missing_languages=REQUIRED_TESSERACT_LANGUAGES,
            usable=False,
            diagnosis="tesseract_not_found",
            warnings=(),
            errors=("tesseract executable was not found on PATH",),
        )

    executable_name = "tesseract"
    version_result = _run_tesseract_command(
        [executable_path, "--version"],
        timeout_seconds=timeout_seconds,
    )
    if version_result.returncode != 0:
        return _command_failed_diagnostic(
            executable_name=executable_name,
            diagnosis="tesseract_command_failed",
            error_message=_safe_command_error(version_result),
        )

    languages_result = _run_tesseract_command(
        [executable_path, "--list-langs"],
        timeout_seconds=timeout_seconds,
    )
    if languages_result.returncode != 0:
        return _command_failed_diagnostic(
            executable_name=executable_name,
            diagnosis="tesseract_command_failed",
            version=_first_line(version_result.stdout),
            error_message=_safe_command_error(languages_result),
        )

    available_languages = _parse_languages(languages_result.stdout)
    missing_languages = tuple(
        language
        for language in REQUIRED_TESSERACT_LANGUAGES
        if language not in set(available_languages)
    )
    usable = len(missing_languages) == 0
    return OcrEnvironmentDiagnostic(
        engine="tesseract",
        executable_found=True,
        executable_path=executable_name,
        version=_first_line(version_result.stdout),
        available_languages=available_languages,
        required_languages=REQUIRED_TESSERACT_LANGUAGES,
        missing_languages=missing_languages,
        usable=usable,
        diagnosis="usable" if usable else "required_languages_missing",
        warnings=() if usable else ("required OCR languages are missing",),
        errors=(),
    )


def _run_tesseract_command(
    command: list[str],
    *,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    """shellを使わず、タイムアウト付きでTesseractを実行する。"""
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            shell=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return subprocess.CompletedProcess(
            command,
            returncode=1,
            stdout="",
            stderr=f"{type(error).__name__}: {error}",
        )


def _command_failed_diagnostic(
    *,
    executable_name: str,
    diagnosis: str,
    error_message: str,
    version: str | None = None,
) -> OcrEnvironmentDiagnostic:
    return OcrEnvironmentDiagnostic(
        engine="tesseract",
        executable_found=True,
        executable_path=executable_name,
        version=version,
        available_languages=(),
        required_languages=REQUIRED_TESSERACT_LANGUAGES,
        missing_languages=REQUIRED_TESSERACT_LANGUAGES,
        usable=False,
        diagnosis=diagnosis,
        warnings=(),
        errors=(error_message,),
    )


def _first_line(value: str) -> str | None:
    line = value.splitlines()[0].strip() if value.splitlines() else ""
    return line or None


def _parse_languages(output: str) -> tuple[str, ...]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    languages = [line for line in lines if not line.lower().startswith("list of available")]
    return tuple(sorted(set(languages)))


def _safe_command_error(result: subprocess.CompletedProcess[str]) -> str:
    message = (result.stderr or result.stdout or "").strip().splitlines()
    if not message:
        return f"command failed with exit code {result.returncode}"
    first_line = message[0]
    if len(first_line) > 300:
        return first_line[:300] + "..."
    return first_line
