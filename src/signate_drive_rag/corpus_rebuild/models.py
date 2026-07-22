"""全文書コーパス再構築パイプラインのモデル。"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RebuildCorpusOptions:
    """全文書コーパス再構築の実行設定。"""

    source: Path
    output_dir: Path
    enable_ocr: bool = False
    ocr_model_dir: Path = Path("artifacts") / "models" / "easyocr"
    ocr_device: str = "auto"
    ocr_languages: tuple[str, ...] = ("ja", "en")
    max_chars: int = 4_000
    overlap_chars: int = 200
    table_max_rows: int = 25
    queries: Path | None = None
    baseline_dir: Path | None = None
    top_k: int = 10
    candidate_multiplier: int = 5
    rrf_k: int = 60
    preview_chars: int = 300
    report_results_per_query: int = 5
    overwrite: bool = False
    resume: bool = False
    strict: bool = False


@dataclass(frozen=True, slots=True)
class StageStatus:
    """パイプライン工程の実行状態。"""

    name: str
    status: str
    started: str | None
    completed: str | None
    elapsed_seconds: float
    input_fingerprint: str
    output_fingerprint: str
    settings_fingerprint: str
    summary_path: str | None
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class RebuildCorpusResult:
    """全文書コーパス再構築の結果。"""

    output_dir: Path
    manifest_path: Path
    stage_status_path: Path
    report_path: Path
    stages: tuple[StageStatus, ...]
