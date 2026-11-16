"""Test scripts/train/sft.py: tham số dòng lệnh và chép adapter. Không import torch."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.train import sft
from travel_agent.training.sft_config import load_sft_config

REPO = Path(__file__).parents[2]
SFT_YAML = REPO / "configs" / "sft.yaml"
ADAPTER_FILES = ("adapter_config.json", "adapter_model.safetensors")


def _checkpoint(root: Path, step: int) -> Path:
    checkpoint = root / f"checkpoint-{step}"
    checkpoint.mkdir(parents=True)
    (checkpoint / "adapter_config.json").write_text(f"config {step}", encoding="utf-8")
    (checkpoint / "adapter_model.safetensors").write_bytes(f"weights {step}".encode())
    (checkpoint / "optimizer.pt").write_bytes(b"optimizer state")
    return checkpoint


def test_parse_args_defaults() -> None:
    args = sft.parse_args([])
    assert args.config == Path("configs/sft.yaml")
    assert args.smoke is False
    assert args.resume is False


def test_parse_args_smoke_and_resume() -> None:
    args = sft.parse_args(["--smoke", "--resume"])
    assert args.smoke is True
    assert args.resume is True


def test_report_target_smoke_is_always_none() -> None:
    config = load_sft_config(SFT_YAML)
    assert sft.report_target(config, smoke=True) == "none"


def test_report_target_full_run_uses_config() -> None:
    config = load_sft_config(SFT_YAML)
    assert config.sft.train.report_to == "wandb"
    assert sft.report_target(config, smoke=False) == "wandb"

    train = config.sft.train.model_copy(update={"report_to": "none"})
    off = config.model_copy(update={"sft": config.sft.model_copy(update={"train": train})})
    assert sft.report_target(off, smoke=False) == "none"


def test_interval_callback_reapplies_config_on_train_begin() -> None:
    pytest.importorskip("transformers")
    callback = sft.make_interval_callback()
    args = SimpleNamespace(logging_steps=1, save_steps=50)
    state = SimpleNamespace(logging_steps=10, save_steps=250)  # state cũ từ checkpoint

    callback.on_train_begin(args, state, SimpleNamespace())

    assert state.logging_steps == 1
    assert state.save_steps == 50


def test_copy_adapters_copies_in_numeric_order(tmp_path: Path) -> None:
    checkpoints = tmp_path / "checkpoints"
    for step in (10, 2, 100):
        _checkpoint(checkpoints, step)
    target = tmp_path / "adapters"

    assert sft.copy_adapters(checkpoints, target, every=1, last=100) == [2, 10, 100]

    step_dir = target / "step-10"
    assert sorted(path.name for path in step_dir.iterdir()) == sorted(ADAPTER_FILES)
    for name in ADAPTER_FILES:
        assert (step_dir / name).read_bytes() == (checkpoints / "checkpoint-10" / name).read_bytes()


def test_copy_adapters_is_repeatable(tmp_path: Path) -> None:
    checkpoints = tmp_path / "checkpoints"
    for step in (2, 10):
        _checkpoint(checkpoints, step)
    target = tmp_path / "adapters"

    first = sft.copy_adapters(checkpoints, target, every=1, last=10)
    second = sft.copy_adapters(checkpoints, target, every=1, last=10)

    assert first == second == [2, 10]


def test_copy_adapters_fails_without_adapter_weights(tmp_path: Path) -> None:
    checkpoints = tmp_path / "checkpoints"
    checkpoint = _checkpoint(checkpoints, 5)
    (checkpoint / "adapter_model.safetensors").unlink()

    with pytest.raises(FileNotFoundError):
        sft.copy_adapters(checkpoints, tmp_path / "adapters", every=5, last=5)


def test_copy_adapters_keeps_only_interval_and_final_step(tmp_path: Path) -> None:
    checkpoints = tmp_path / "checkpoints"
    for step in (*range(50, 501, 50), 520):
        _checkpoint(checkpoints, step)
    target = tmp_path / "adapters"

    assert sft.copy_adapters(checkpoints, target, every=250, last=520) == [250, 500, 520]
    assert sorted(path.name for path in target.iterdir()) == [
        "step-250",
        "step-500",
        "step-520",
    ]
