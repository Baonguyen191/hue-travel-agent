"""Test scripts/train/grpo.py: tham số, reward, dựng dataset và GRPOConfig. Không import torch."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.train import grpo
from tests.training.factories import PLACES, REQUEST, VALID_RAW
from travel_agent.routing.travel_time import HaversineEstimator
from travel_agent.training.reward import score_reward
from travel_agent.training.rl_config import load_rl_config
from travel_agent.training.rl_data import RlPrompt

REPO = Path(__file__).parents[2]
RL_YAML = REPO / "configs" / "rl.yaml"
GARBAGE = "không phải JSON"


def _prompt(key: str = "k1") -> RlPrompt:
    return RlPrompt(key=key, request=REQUEST, candidates=list(PLACES), messages=[])


def _functions() -> dict[str, object]:
    functions, _ = grpo.make_reward_functions({"k1": _prompt()}, HaversineEstimator())
    return {function.__name__: function for function in functions}


def test_parse_args_defaults() -> None:
    args = grpo.parse_args([])
    assert args.config == Path("configs/rl.yaml")
    assert args.smoke is False
    assert args.resume is False


def test_parse_args_smoke_and_resume() -> None:
    args = grpo.parse_args(["--smoke", "--resume"])
    assert args.smoke is True
    assert args.resume is True


def test_report_target_smoke_is_always_none() -> None:
    config = load_rl_config(RL_YAML)
    assert grpo.report_target(config, smoke=True) == "none"
    assert grpo.report_target(config, smoke=False) == "wandb"


def test_max_steps_follow_smoke_or_full_run() -> None:
    config = load_rl_config(RL_YAML)
    assert grpo.max_steps_for(config, smoke=True) == 5
    assert grpo.max_steps_for(config, smoke=False) == config.grpo.max_steps


def test_completion_text_accepts_string_and_message_list() -> None:
    assert grpo.completion_text("abc") == "abc"
    assert grpo.completion_text([{"role": "assistant", "content": "xyz"}]) == "xyz"


def test_completion_text_rejects_unknown_shape() -> None:
    with pytest.raises(TypeError):
        grpo.completion_text(42)


def test_reward_functions_are_named_and_weighted() -> None:
    functions, weights = grpo.make_reward_functions({"k1": _prompt()}, HaversineEstimator())

    assert [function.__name__ for function in functions] == [
        "reward_total",
        "parsed",
        "valid",
        "stops",
    ]
    assert weights == [1.0, 0.0, 0.0, 0.0]


def test_reward_total_matches_the_reward_module() -> None:
    expected = score_reward(REQUEST, VALID_RAW, PLACES, HaversineEstimator()).total

    total = _functions()["reward_total"](completions=[VALID_RAW], key=["k1"])

    assert total == [expected]


def test_reward_total_penalises_unparsed_output_at_minus_one() -> None:
    assert _functions()["reward_total"](completions=[GARBAGE], key=["k1"]) == [-1.0]


def test_diagnostics_report_parse_validity_and_stops() -> None:
    functions = _functions()
    valid_run = score_reward(REQUEST, VALID_RAW, PLACES, HaversineEstimator())

    assert functions["parsed"](completions=[VALID_RAW, GARBAGE], key=["k1", "k1"]) == [1.0, 0.0]
    assert functions["valid"](completions=[VALID_RAW, GARBAGE], key=["k1", "k1"]) == [
        1.0 if valid_run.valid else 0.0,
        0.0,
    ]
    # VALID_RAW có 1 ngày với 3 stop; output không parse được thì 0.
    assert functions["stops"](completions=[VALID_RAW, GARBAGE], key=["k1", "k1"]) == [3.0, 0.0]


def test_completions_as_message_lists_are_scored_the_same() -> None:
    as_text = _functions()["reward_total"](completions=[VALID_RAW], key=["k1"])
    as_messages = _functions()["reward_total"](
        completions=[[{"role": "assistant", "content": VALID_RAW}]], key=["k1"]
    )

    assert as_text == as_messages


def test_reward_total_logs_every_issue_key_for_each_completion() -> None:
    logged: list[tuple[str, float]] = []

    _functions()["reward_total"](
        completions=[GARBAGE],
        key=["k1"],
        log_metric=lambda name, value: logged.append((name, value)),
    )

    assert [name for name, _ in logged] == [f"issue/{key}" for key in grpo.ISSUE_KEYS]
    assert all(value == 0.0 for _, value in logged)  # không parse thì không có khóa phạt


def test_unknown_prompt_key_is_an_error() -> None:
    with pytest.raises(KeyError):
        _functions()["reward_total"](completions=[VALID_RAW], key=["missing"])


def test_build_rows_renders_each_prompt_once() -> None:
    prompts = [_prompt("a"), _prompt("b")]
    seen: list[list[dict[str, str]]] = []

    def render(messages: Sequence[Mapping[str, str]]) -> str:
        seen.append([dict(message) for message in messages])
        return f"rendered {len(seen)}"

    rows = grpo.build_rows(prompts, render)

    assert rows == [
        {"prompt": "rendered 1", "key": "a"},
        {"prompt": "rendered 2", "key": "b"},
    ]
    assert len(seen) == 2


def test_grpo_config_kwargs_use_the_config_values() -> None:
    config = load_rl_config(RL_YAML)
    kwargs = grpo.grpo_config_kwargs(
        config.rl,
        config.grpo,
        Path("out"),
        max_steps=5,
        report_to="none",
        reward_weights=[1.0, 0.0, 0.0, 0.0],
    )

    assert kwargs["max_steps"] == 5
    assert kwargs["num_generations"] == 4
    assert kwargs["beta"] == 0.0
    assert kwargs["max_completion_length"] == 1024
    assert kwargs["save_steps"] == 25
    assert kwargs["reward_weights"] == [1.0, 0.0, 0.0, 0.0]
    assert kwargs["remove_unused_columns"] is False
    assert kwargs["report_to"] == "none"
    assert kwargs["run_name"] == "rl-v1"
    assert kwargs["seed"] == 4242


def test_interval_callback_reapplies_config_on_train_begin() -> None:
    pytest.importorskip("transformers")
    callback = grpo.make_interval_callback()
    args = SimpleNamespace(logging_steps=1, save_steps=25)
    state = SimpleNamespace(logging_steps=10, save_steps=250)  # state cũ từ checkpoint

    callback.on_train_begin(args, state, SimpleNamespace())

    assert state.logging_steps == 1
    assert state.save_steps == 25


def test_script_import_does_not_load_torch() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO / "src"), str(REPO)])
    probe = "import scripts.train.grpo, sys; print('torch' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"
