"""OCR実行デバイス判定のテスト。"""

import sys
from types import SimpleNamespace

import pytest

from signate_drive_rag.ocr.device import is_torch_cuda_available, resolve_ocr_gpu_flag


def test_resolve_ocr_gpu_flag_accepts_cpu_and_gpu() -> None:
    """明示指定のcpu/gpuをEasyOCRのgpuフラグへ変換できることを確認する。"""
    assert resolve_ocr_gpu_flag("cpu") is False
    assert resolve_ocr_gpu_flag("gpu") is True


def test_resolve_ocr_gpu_flag_uses_cuda_detection_for_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    """auto指定ではCUDA対応Torchの検出結果に従うことを確認する。"""
    fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    assert resolve_ocr_gpu_flag("auto") is True


def test_resolve_ocr_gpu_flag_rejects_unknown_device() -> None:
    """未知のデバイス指定を曖昧にCPU扱いしないことを確認する。"""
    with pytest.raises(ValueError, match="ocr-device"):
        resolve_ocr_gpu_flag("cuda")


def test_is_torch_cuda_available_returns_false_when_torch_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Torchをimportできない環境ではCPUへ倒せることを確認する。"""
    monkeypatch.setitem(sys.modules, "torch", None)

    assert is_torch_cuda_available() is False
