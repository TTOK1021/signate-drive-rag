"""OCR実行デバイスの判定を扱う。"""


def is_torch_cuda_available() -> bool:
    """CUDA対応Torchが利用できる場合だけTrueを返す。"""
    try:
        import torch
    except ImportError:
        return False
    return bool(torch.cuda.is_available())


def resolve_ocr_gpu_flag(device: str) -> bool:
    """CLI指定をEasyOCRのgpuフラグへ変換する。"""
    normalized = device.strip().lower()
    if normalized == "cpu":
        return False
    if normalized == "gpu":
        return True
    if normalized == "auto":
        return is_torch_cuda_available()
    raise ValueError("ocr-deviceはcpu、gpu、autoのいずれかを指定してください。")
