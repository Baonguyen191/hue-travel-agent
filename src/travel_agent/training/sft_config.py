"""Config SFT (`configs/sft.yaml`). Chỉ pydantic và yaml: venv project nạp được, không cần torch."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BaseModelRef(_Strict):
    repo: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    license: str = Field(min_length=1)
    license_source: str = Field(min_length=1)


class LoraParams(_Strict):
    r: int = Field(gt=0)
    alpha: int = Field(gt=0)
    dropout: float = Field(ge=0, lt=1)
    target_modules: str = Field(min_length=1)  # regex, PEFT so bằng re.fullmatch

    @field_validator("target_modules")
    @classmethod
    def _compiles(cls, value: str) -> str:
        re.compile(value)
        return value


class QuantizationParams(_Strict):
    load_in_4bit: bool
    quant_type: str
    double_quant: bool
    compute_dtype: str


class TrainParams(_Strict):
    epochs: int = Field(gt=0)
    learning_rate: float = Field(gt=0)
    per_device_batch_size: int = Field(gt=0)
    gradient_accumulation_steps: int = Field(gt=0)
    lr_scheduler: str
    warmup_ratio: float = Field(ge=0, lt=1)
    weight_decay: float = Field(ge=0)
    optimizer: str
    gradient_checkpointing: bool
    logging_steps: int = Field(gt=0)
    save_steps: int = Field(gt=0)


class SmokeParams(_Strict):
    max_steps: int = Field(gt=0)


class SftParams(_Strict):
    run_name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    python: Path
    runs_dir: Path
    dataset: Path
    base_model: BaseModelRef
    seed: int
    max_seq: int = Field(gt=0)
    lora: LoraParams
    quantization: QuantizationParams
    train: TrainParams
    smoke: SmokeParams

    @property
    def run_dir(self) -> Path:
        """Thư mục output nặng của run (checkpoint, merge, GGUF), ngoài repo."""
        return self.runs_dir / self.run_name


class ExportParams(_Strict):
    checkpoint: int | None = Field(default=None, gt=0)
    quantization: str = Field(min_length=1)
    llama_cpp_dir: Path
    template_model: str = Field(min_length=1)
    ollama_model: str = Field(min_length=1)


class SftConfig(_Strict):
    sft: SftParams
    export: ExportParams


def load_sft_config(path: Path) -> SftConfig:
    return SftConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def repo_artifacts_dir(run_name: str) -> Path:
    """Thư mục trong repo cho output nhỏ của run: adapter (DVC), model card, metrics."""
    return Path("models") / "sft" / run_name
