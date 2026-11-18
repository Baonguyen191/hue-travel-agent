"""Config RL (`configs/rl.yaml`). Chỉ pydantic và yaml: venv project nạp được, không cần torch."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from travel_agent.training.sft_config import SmokeParams, TrackingParams


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RlParams(_Strict):
    run_name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    method: Literal["grpo", "best_of_n"]
    python: Path
    runs_dir: Path
    init_adapter: Path  # adapter SFT khởi đầu, đường dẫn tương đối gốc repo
    sft_config: Path  # base model và lượng tử hóa lấy từ đây
    db: Path
    evalset: Path
    sft_dataset: Path
    seed: int
    requests: int = Field(gt=0)  # số request train RL, sau khi loại trùng eval và SFT
    report_to: Literal["none", "wandb"]
    tracking: TrackingParams
    smoke: SmokeParams

    @property
    def run_dir(self) -> Path:
        """Thư mục output nặng của run (checkpoint, adapter cuối), ngoài repo."""
        return self.runs_dir / self.run_name


class GrpoParams(_Strict):
    num_generations: int = Field(ge=2)
    per_device_batch_size: int = Field(gt=0)
    gradient_accumulation_steps: int = Field(gt=0)
    learning_rate: float = Field(gt=0)
    max_completion_length: int = Field(gt=0)
    temperature: float = Field(gt=0)
    beta: float = Field(ge=0)  # hệ số KL; 0 = không có model tham chiếu
    max_steps: int = Field(gt=0)
    save_steps: int = Field(gt=0)
    logging_steps: int = Field(gt=0)

    @model_validator(mode="after")
    def _generation_batch_divisible(self) -> GrpoParams:
        # TRL sinh `per_device_batch_size * gradient_accumulation_steps` completion mỗi lần; số
        # đó phải chia hết cho `num_generations` để mỗi prompt có đủ nhóm.
        generation_batch = self.per_device_batch_size * self.gradient_accumulation_steps
        if generation_batch % self.num_generations != 0:
            raise ValueError(
                "per_device_batch_size * gradient_accumulation_steps "
                "phải chia hết cho num_generations"
            )
        return self


class BestOfNParams(_Strict):
    requests_per_round: int = Field(gt=0)
    samples: int = Field(gt=0)
    threshold: float = Field(ge=0, le=1)
    learning_rate: float = Field(gt=0)
    epochs: int = Field(gt=0)
    max_rounds: int = Field(gt=0)
    temperature: float = Field(gt=0)


class FinalParams(_Strict):
    """Vòng best-of-N được chọn để chạy thật (plan 5 Task 6). Đường dẫn tương đối gốc repo."""

    dataset: Path  # jsonl DatasetSample của vòng đã chọn
    stats: Path  # số đo sinh dữ liệu của vòng đó, đi cùng dataset
    round: int = Field(gt=0)
    ollama_model: str = Field(min_length=1)
    learning_rate: float = Field(gt=0)
    epochs: int = Field(gt=0)

    @model_validator(mode="after")
    def _stats_belongs_to_dataset(self) -> FinalParams:
        if self.stats != self.dataset.with_suffix(".stats.json"):
            raise ValueError("stats phải nằm cạnh dataset, cùng tên với đuôi .stats.json")
        return self


class RlConfig(_Strict):
    rl: RlParams
    grpo: GrpoParams
    best_of_n: BestOfNParams
    final: FinalParams


def load_rl_config(path: Path) -> RlConfig:
    return RlConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def repo_rl_artifacts_dir(run_name: str) -> Path:
    """Thư mục trong repo cho output nhỏ của run RL: adapter cuối (DVC), export, model card."""
    return Path("models") / "rl" / run_name
