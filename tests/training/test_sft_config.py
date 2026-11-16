import re
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from travel_agent.training.dataset import load_config
from travel_agent.training.sft_config import SftConfig, load_sft_config

REPO = Path(__file__).parents[2]
SFT_YAML = REPO / "configs" / "sft.yaml"


def test_repo_config_loads() -> None:
    config = load_sft_config(SFT_YAML)
    assert config.sft.run_dir == config.sft.runs_dir / config.sft.run_name
    assert config.export.quantization == "Q4_K_M"


def test_max_seq_and_tokenizer_match_the_dataset_check() -> None:
    sft = load_sft_config(SFT_YAML).sft
    check = load_config(REPO / "configs" / "dataset.yaml").check
    assert sft.max_seq == check.max_tokens
    assert (sft.base_model.repo, sft.base_model.revision) == (
        check.tokenizer.repo,
        check.tokenizer.revision,
    )


def test_repo_config_resume_and_adapter_intervals() -> None:
    train = load_sft_config(SFT_YAML).sft.train
    assert train.save_steps == 50
    assert train.adapter_every == 250


def test_repo_config_reporting_and_tracking() -> None:
    sft = load_sft_config(SFT_YAML).sft
    assert sft.train.report_to == "wandb"
    assert sft.train.logging_steps == 1
    assert sft.tracking.project == "travel-agent-sft"


def test_report_to_rejects_unknown_backend() -> None:
    raw = yaml.safe_load(SFT_YAML.read_text(encoding="utf-8"))
    raw["sft"]["train"]["report_to"] = "tensorboard"
    with pytest.raises(ValidationError):
        SftConfig.model_validate(raw)


def test_adapter_every_must_be_a_multiple_of_save_steps() -> None:
    raw = yaml.safe_load(SFT_YAML.read_text(encoding="utf-8"))
    raw["sft"]["train"]["save_steps"] = 50
    raw["sft"]["train"]["adapter_every"] = 260
    with pytest.raises(ValidationError, match="bội số của save_steps"):
        SftConfig.model_validate(raw)


def test_heavy_outputs_live_outside_the_repo() -> None:
    runs_dir = load_sft_config(SFT_YAML).sft.runs_dir.resolve()
    assert REPO.resolve() not in runs_dir.parents
    assert "OneDrive" not in runs_dir.parts


@pytest.mark.parametrize(
    ("module", "targeted"),
    [
        ("model.language_model.layers.3.self_attn.q_proj", True),
        ("model.language_model.layers.0.linear_attn.in_proj_qkv", True),
        ("model.language_model.layers.31.mlp.down_proj", True),
        ("model.layers.7.self_attn.o_proj", True),
        ("model.layers.0.linear_attn.out_proj", True),
        ("model.language_model.layers.0.linear_attn.in_proj_a", False),
        ("mtp.layers.0.self_attn.q_proj", False),
        ("model.visual.blocks.0.attn.qkv", False),
        ("lm_head", False),
    ],
)
def test_lora_targets_only_text_layers(module: str, targeted: bool) -> None:
    pattern = load_sft_config(SFT_YAML).sft.lora.target_modules
    assert (re.fullmatch(pattern, module) is not None) is targeted


def test_unknown_keys_are_rejected() -> None:
    raw = yaml.safe_load(SFT_YAML.read_text(encoding="utf-8"))
    raw["sft"]["lora"]["rank"] = 8
    with pytest.raises(ValidationError):
        SftConfig.model_validate(raw)
