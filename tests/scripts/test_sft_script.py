"""Test scripts/train/sft.py: tham số dòng lệnh và chép adapter. Không import torch."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.train import sft

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


def test_copy_adapters_copies_in_numeric_order(tmp_path: Path) -> None:
    checkpoints = tmp_path / "checkpoints"
    for step in (10, 2, 100):
        _checkpoint(checkpoints, step)
    target = tmp_path / "adapters"

    assert sft.copy_adapters(checkpoints, target) == [2, 10, 100]

    step_dir = target / "step-10"
    assert sorted(path.name for path in step_dir.iterdir()) == sorted(ADAPTER_FILES)
    for name in ADAPTER_FILES:
        assert (step_dir / name).read_bytes() == (checkpoints / "checkpoint-10" / name).read_bytes()


def test_copy_adapters_is_repeatable(tmp_path: Path) -> None:
    checkpoints = tmp_path / "checkpoints"
    for step in (2, 10):
        _checkpoint(checkpoints, step)
    target = tmp_path / "adapters"

    first = sft.copy_adapters(checkpoints, target)
    second = sft.copy_adapters(checkpoints, target)

    assert first == second == [2, 10]


def test_copy_adapters_fails_without_adapter_weights(tmp_path: Path) -> None:
    checkpoints = tmp_path / "checkpoints"
    checkpoint = _checkpoint(checkpoints, 5)
    (checkpoint / "adapter_model.safetensors").unlink()

    with pytest.raises(FileNotFoundError):
        sft.copy_adapters(checkpoints, tmp_path / "adapters")
