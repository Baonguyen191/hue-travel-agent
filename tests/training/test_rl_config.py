from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from travel_agent.training.rl_config import RlConfig, load_rl_config, repo_rl_artifacts_dir
from travel_agent.training.sft_config import load_sft_config

REPO = Path(__file__).parents[2]
RL_YAML = REPO / "configs" / "rl.yaml"


def _raw() -> dict:
    return yaml.safe_load(RL_YAML.read_text(encoding="utf-8"))


def test_repo_config_loads() -> None:
    config = load_rl_config(RL_YAML)
    assert config.rl.method == "best_of_n"  # smoke GRPO không qua cổng spec 8.3
    assert config.rl.run_dir == config.rl.runs_dir / "rl-v1"


def test_base_model_comes_from_the_sft_config() -> None:
    config = load_rl_config(RL_YAML)
    sft = load_sft_config(REPO / config.rl.sft_config).sft
    assert (sft.base_model.repo, sft.base_model.revision) == (
        "Qwen/Qwen3.5-4B",
        "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a",
    )


def test_rl_starts_from_the_chosen_sft_checkpoint() -> None:
    rl = load_rl_config(RL_YAML).rl
    assert rl.init_adapter == Path("models/sft/sft-v1/adapters/step-250")
    assert rl.seed == 4242
    assert rl.tracking.project == "travel-agent-sft"
    assert rl.smoke.max_steps == 5


def test_rl_requests_cover_every_best_of_n_round() -> None:
    config = load_rl_config(RL_YAML)
    best = config.best_of_n
    assert config.rl.requests >= best.requests_per_round * best.max_rounds


def test_grpo_values_match_the_plan() -> None:
    grpo = load_rl_config(RL_YAML).grpo
    assert grpo.num_generations == 4
    assert grpo.learning_rate == pytest.approx(5e-6)
    assert grpo.max_completion_length == 1024
    assert grpo.temperature == 1.0
    assert grpo.save_steps == 25
    assert grpo.beta == 0.0


def test_best_of_n_values_match_the_plan() -> None:
    bon = load_rl_config(RL_YAML).best_of_n
    assert bon.requests_per_round == 500
    assert bon.samples == 4
    assert bon.threshold == pytest.approx(0.9)
    assert bon.learning_rate == pytest.approx(5e-5)
    assert bon.epochs == 1
    assert bon.max_rounds == 5
    assert bon.temperature == 1.0


def test_generation_batch_must_divide_by_num_generations() -> None:
    raw = _raw()
    raw["grpo"]["gradient_accumulation_steps"] = 6  # 1 * 6 = 6 không chia hết cho 4
    with pytest.raises(ValidationError, match="chia hết cho num_generations"):
        RlConfig.model_validate(raw)


def test_method_rejects_unknown_value() -> None:
    raw = _raw()
    raw["rl"]["method"] = "ppo"
    with pytest.raises(ValidationError):
        RlConfig.model_validate(raw)


def test_report_to_rejects_unknown_backend() -> None:
    raw = _raw()
    raw["rl"]["report_to"] = "tensorboard"
    with pytest.raises(ValidationError):
        RlConfig.model_validate(raw)


def test_threshold_must_be_a_probability() -> None:
    raw = _raw()
    raw["best_of_n"]["threshold"] = 1.5
    with pytest.raises(ValidationError):
        RlConfig.model_validate(raw)


def test_unknown_keys_are_rejected() -> None:
    raw = _raw()
    raw["grpo"]["clip_range"] = 0.2
    with pytest.raises(ValidationError):
        RlConfig.model_validate(raw)


def test_heavy_outputs_live_outside_the_repo() -> None:
    runs_dir = load_rl_config(RL_YAML).rl.runs_dir.resolve()
    assert REPO.resolve() not in runs_dir.parents
    assert "OneDrive" not in runs_dir.parts


def test_final_round_is_the_chosen_round_one() -> None:
    final = load_rl_config(RL_YAML).final
    assert final.round == 1
    assert final.dataset == Path("data/rl/rl-v1/round-1.jsonl")
    assert final.stats == Path("data/rl/rl-v1/round-1.stats.json")
    assert final.ollama_model == "travel-rl-v1"
    assert final.learning_rate == pytest.approx(5e-5)
    assert final.epochs == 1


def test_final_stats_must_sit_next_to_the_dataset() -> None:
    raw = _raw()
    raw["final"]["stats"] = "data/rl/rl-v1/other.json"
    with pytest.raises(ValidationError, match="stats"):
        RlConfig.model_validate(raw)


def test_final_rejects_non_positive_learning_rate() -> None:
    raw = _raw()
    raw["final"]["learning_rate"] = 0
    with pytest.raises(ValidationError):
        RlConfig.model_validate(raw)


def test_rl_artifacts_live_under_models_rl() -> None:
    assert repo_rl_artifacts_dir("rl-v1") == Path("models") / "rl" / "rl-v1"
