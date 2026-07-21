"""OCR環境診断のテスト。"""

import subprocess
from collections.abc import Sequence

from signate_drive_rag.document_diagnostics import ocr_diagnostic


def test_diagnose_tesseract_environment_reports_not_found(monkeypatch: object) -> None:
    """tesseract実行ファイルが見つからない場合は未利用として診断する。"""
    monkeypatch.setattr(ocr_diagnostic.shutil, "which", lambda _name: None)

    result = ocr_diagnostic.diagnose_tesseract_environment()

    assert result.executable_found is False
    assert result.executable_path is None
    assert result.usable is False
    assert result.diagnosis == "tesseract_not_found"
    assert result.missing_languages == ("eng", "jpn")


def test_diagnose_tesseract_environment_reports_missing_languages(
    monkeypatch: object,
) -> None:
    """必須言語の一部が欠けている場合は不足言語を記録する。"""
    monkeypatch.setattr(ocr_diagnostic.shutil, "which", lambda _name: "tesseract-path")

    def fake_run(command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["shell"] is False
        assert kwargs["timeout"] == 5
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="tesseract 5.3.0\n", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="List of available languages in data path:\neng\n",
            stderr="",
        )

    monkeypatch.setattr(ocr_diagnostic.subprocess, "run", fake_run)

    result = ocr_diagnostic.diagnose_tesseract_environment()

    assert result.executable_found
    assert result.executable_path == "tesseract"
    assert result.version == "tesseract 5.3.0"
    assert result.available_languages == ("eng",)
    assert result.missing_languages == ("jpn",)
    assert result.usable is False
    assert result.diagnosis == "required_languages_missing"


def test_diagnose_tesseract_environment_reports_usable_when_required_languages_exist(
    monkeypatch: object,
) -> None:
    """engとjpnが利用できる場合だけOCR環境を利用可能と判定する。"""
    monkeypatch.setattr(ocr_diagnostic.shutil, "which", lambda _name: "tesseract-path")

    def fake_run(command: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, stdout="tesseract 5.3.0\n", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="List of available languages in data path:\njpn\neng\njpn_vert\n",
            stderr="",
        )

    monkeypatch.setattr(ocr_diagnostic.subprocess, "run", fake_run)

    result = ocr_diagnostic.diagnose_tesseract_environment()

    assert result.available_languages == ("eng", "jpn", "jpn_vert")
    assert result.missing_languages == ()
    assert result.usable
    assert result.diagnosis == "usable"


def test_diagnose_tesseract_environment_reports_command_failure(
    monkeypatch: object,
) -> None:
    """tesseractコマンドが失敗した場合はコマンド失敗として診断する。"""
    monkeypatch.setattr(ocr_diagnostic.shutil, "which", lambda _name: "tesseract-path")
    monkeypatch.setattr(
        ocr_diagnostic.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="boom",
        ),
    )

    result = ocr_diagnostic.diagnose_tesseract_environment()

    assert result.usable is False
    assert result.diagnosis == "tesseract_command_failed"
    assert result.errors == ("boom",)
