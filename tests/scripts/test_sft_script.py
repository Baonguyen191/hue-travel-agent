"""Test scripts/train/sft.py: tham số dòng lệnh và chép adapter. Không import torch."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.train import sft
from travel_agent.training.sft_config import SftConfig, load_sft_config, repo_artifacts_dir

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


# --- cờ ghi đè cho vòng best-of-N -------------------------------------------------


def _config_at(tmp_path: Path) -> SftConfig:
    """configs/sft.yaml với runs_dir nằm trong tmp_path, để không đụng thư mục output thật."""
    config = load_sft_config(SFT_YAML)
    sft_params = config.sft.model_copy(update={"runs_dir": tmp_path / "runs"})
    return config.model_copy(update={"sft": sft_params})


def _adapter(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "adapter_model.safetensors").write_bytes(b"adapter")
    return root


def test_parse_args_new_flags_default_to_none() -> None:
    args = sft.parse_args([])
    assert args.init_adapter is None
    assert args.dataset is None
    assert args.run_dir is None
    assert args.learning_rate is None
    assert args.epochs is None
    assert args.run_name is None


def test_parse_args_reads_overrides() -> None:
    args = sft.parse_args(
        [
            "--init-adapter",
            "a/b",
            "--dataset",
            "d.jsonl",
            "--run-dir",
            "r",
            "--learning-rate",
            "1e-4",
            "--epochs",
            "1",
            "--run-name",
            "bon-1",
        ]
    )
    assert args.init_adapter == Path("a/b")
    assert args.dataset == Path("d.jsonl")
    assert args.run_dir == Path("r")
    assert args.learning_rate == 1e-4
    assert args.epochs == 1
    assert args.run_name == "bon-1"


def test_resolve_run_without_flags_keeps_the_old_layout(tmp_path: Path) -> None:
    config = _config_at(tmp_path)
    plan = sft.resolve_run(sft.parse_args([]), config)

    assert plan == sft.RunPlan(
        dataset=config.sft.dataset,
        out=config.sft.run_dir / "checkpoints",
        learning_rate=config.sft.train.learning_rate,
        epochs=config.sft.train.epochs,
        run_name=config.sft.run_name,
        init_adapter=None,
        copy_to_repo=True,
        metrics_path=repo_artifacts_dir(config.sft.run_name) / "train_metrics.json",
    )


def test_resolve_run_smoke_keeps_the_old_layout(tmp_path: Path) -> None:
    config = _config_at(tmp_path)
    plan = sft.resolve_run(sft.parse_args(["--smoke"]), config)

    out = config.sft.run_dir / "smoke"
    assert plan.out == out
    assert plan.copy_to_repo is False
    assert plan.metrics_path == out / "train_metrics.json"


def test_resolve_run_run_dir_disables_repo_copy(tmp_path: Path) -> None:
    config = _config_at(tmp_path)
    run_dir = tmp_path / "bon" / "round-1"

    plan = sft.resolve_run(sft.parse_args(["--run-dir", str(run_dir)]), config)

    assert plan.out == run_dir / "checkpoints"
    assert plan.copy_to_repo is False
    assert plan.metrics_path == run_dir / "train_metrics.json"


def test_resolve_run_applies_every_override(tmp_path: Path) -> None:
    config = _config_at(tmp_path)
    adapter = _adapter(tmp_path / "init")
    args = sft.parse_args(
        [
            "--init-adapter",
            str(adapter),
            "--dataset",
            str(tmp_path / "round.jsonl"),
            "--run-dir",
            str(tmp_path / "round"),
            "--learning-rate",
            "5e-5",
            "--epochs",
            "3",
            "--run-name",
            "bon-round",
        ]
    )

    plan = sft.resolve_run(args, config)

    assert plan.dataset == tmp_path / "round.jsonl"
    assert plan.learning_rate == 5e-5
    assert plan.epochs == 3
    assert plan.run_name == "bon-round"
    assert plan.init_adapter == adapter
    assert plan.copy_to_repo is False


def test_run_name_alone_does_not_move_repo_paths(tmp_path: Path) -> None:
    config = _config_at(tmp_path)

    plan = sft.resolve_run(sft.parse_args(["--run-name", "other"]), config)

    assert plan.run_name == "other"
    assert plan.copy_to_repo is True
    assert plan.metrics_path == repo_artifacts_dir(config.sft.run_name) / "train_metrics.json"


@pytest.mark.parametrize(
    "argv",
    [["--learning-rate", "0"], ["--epochs", "0"], ["--init-adapter", "missing-adapter-dir"]],
)
def test_resolve_run_rejects_bad_overrides(tmp_path: Path, argv: list[str]) -> None:
    config = _config_at(tmp_path)
    with pytest.raises(SystemExit):
        sft.resolve_run(sft.parse_args(argv), config)


@pytest.fixture
def fake_training_libs(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Thay torch, transformers, peft, trl, datasets bằng bản giả để chạy build_trainer.

    Trả về dict ghi lại lời gọi: `get_peft_model` (lora) và `from_pretrained` (path, is_trainable).
    """
    calls: dict[str, list[Any]] = {"get_peft_model": [], "from_pretrained": []}

    class _Model:
        def print_trainable_parameters(self) -> None:
            return None

    class _Auto:
        @staticmethod
        def from_pretrained(*args: Any, **kwargs: Any) -> _Model:
            return _Model()

    class _PeftModel:
        @staticmethod
        def from_pretrained(model: Any, path: str, is_trainable: bool) -> _Model:
            calls["from_pretrained"].append((path, is_trainable))
            return _Model()

    def _get_peft_model(model: Any, lora: Any) -> _Model:
        calls["get_peft_model"].append(lora)
        return _Model()

    class _Dataset:
        @staticmethod
        def from_dict(data: dict[str, Any]) -> dict[str, Any]:
            return data

    torch = types.ModuleType("torch")
    torch.bfloat16 = "bfloat16"  # type: ignore[attr-defined]
    transformers = types.ModuleType("transformers")
    transformers.AutoModelForCausalLM = _Auto  # type: ignore[attr-defined]
    transformers.AutoTokenizer = _Auto  # type: ignore[attr-defined]
    transformers.BitsAndBytesConfig = lambda **kwargs: kwargs  # type: ignore[attr-defined]
    transformers.TrainerCallback = object  # type: ignore[attr-defined]
    peft = types.ModuleType("peft")
    peft.prepare_model_for_kbit_training = lambda model, **kwargs: model  # type: ignore[attr-defined]
    peft.LoraConfig = lambda **kwargs: kwargs  # type: ignore[attr-defined]
    peft.get_peft_model = _get_peft_model  # type: ignore[attr-defined]
    peft.PeftModel = _PeftModel  # type: ignore[attr-defined]
    trl = types.ModuleType("trl")
    trl.SFTConfig = lambda **kwargs: kwargs  # type: ignore[attr-defined]
    trl.SFTTrainer = lambda **kwargs: kwargs  # type: ignore[attr-defined]
    datasets = types.ModuleType("datasets")
    datasets.Dataset = _Dataset  # type: ignore[attr-defined]

    for name, module in (
        ("torch", torch),
        ("transformers", transformers),
        ("peft", peft),
        ("trl", trl),
        ("datasets", datasets),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    return calls


def test_build_trainer_init_adapter_loads_trainable_peft(
    fake_training_libs: dict[str, list[Any]], tmp_path: Path
) -> None:
    config = load_sft_config(SFT_YAML)
    adapter = tmp_path / "init"

    trainer = sft.build_trainer(
        config,
        tmp_path,
        [],
        tmp_path / "out",
        -1,
        "none",
        learning_rate=5e-5,
        epochs=1,
        run_name="bon-round",
        init_adapter=adapter,
    )

    assert fake_training_libs["from_pretrained"] == [(str(adapter), True)]
    assert fake_training_libs["get_peft_model"] == []
    assert trainer["args"]["learning_rate"] == 5e-5
    assert trainer["args"]["num_train_epochs"] == 1
    assert trainer["args"]["run_name"] == "bon-round"


def test_build_trainer_without_init_adapter_attaches_new_lora(
    fake_training_libs: dict[str, list[Any]], tmp_path: Path
) -> None:
    config = load_sft_config(SFT_YAML)

    trainer = sft.build_trainer(config, tmp_path, [], tmp_path / "out", -1, "none")

    assert fake_training_libs["from_pretrained"] == []
    assert len(fake_training_libs["get_peft_model"]) == 1
    train = config.sft.train
    assert trainer["args"]["learning_rate"] == train.learning_rate
    assert trainer["args"]["num_train_epochs"] == train.epochs
    assert trainer["args"]["run_name"] == config.sft.run_name


# --- --adapter-out -----------------------------------------------------------


def test_parse_args_adapter_out_defaults_to_none() -> None:
    assert sft.parse_args([]).adapter_out is None
    assert sft.parse_args(["--adapter-out", "a"]).adapter_out == Path("a")


def test_resolve_run_adapter_out_needs_run_dir(tmp_path: Path) -> None:
    config = _config_at(tmp_path)
    with pytest.raises(SystemExit, match="--run-dir"):
        sft.resolve_run(sft.parse_args(["--adapter-out", str(tmp_path / "out")]), config)


def test_resolve_run_adapter_out_rejects_smoke(tmp_path: Path) -> None:
    config = _config_at(tmp_path)
    argv = ["--smoke", "--run-dir", str(tmp_path / "r"), "--adapter-out", str(tmp_path / "out")]
    with pytest.raises(SystemExit, match="--smoke"):
        sft.resolve_run(sft.parse_args(argv), config)


def test_resolve_run_with_run_dir_and_adapter_out_keeps_repo_untouched(tmp_path: Path) -> None:
    config = _config_at(tmp_path)
    out = tmp_path / "adapter"
    argv = ["--run-dir", str(tmp_path / "round"), "--adapter-out", str(out)]

    plan = sft.resolve_run(sft.parse_args(argv), config)

    assert plan.adapter_out == out
    assert plan.copy_to_repo is False


def test_resolve_run_without_adapter_out_has_none(tmp_path: Path) -> None:
    config = _config_at(tmp_path)
    plan = sft.resolve_run(sft.parse_args(["--run-dir", str(tmp_path / "round")]), config)
    assert plan.adapter_out is None


def test_copy_final_adapter_copies_only_adapter_files(tmp_path: Path) -> None:
    checkpoint = _checkpoint(tmp_path / "checkpoints", 6)
    target = tmp_path / "models" / "rl" / "rl-v1" / "adapter"

    sft.copy_final_adapter(checkpoint, target)

    assert sorted(path.name for path in target.iterdir()) == sorted(ADAPTER_FILES)
    for name in ADAPTER_FILES:
        assert (target / name).read_bytes() == (checkpoint / name).read_bytes()


def test_copy_final_adapter_overwrites_previous_copy(tmp_path: Path) -> None:
    target = tmp_path / "adapter"
    sft.copy_final_adapter(_checkpoint(tmp_path / "first", 6), target)
    newer = _checkpoint(tmp_path / "second", 7)

    sft.copy_final_adapter(newer, target)

    assert (target / "adapter_model.safetensors").read_bytes() == b"weights 7"
    assert (target / "adapter_config.json").read_text(encoding="utf-8") == "config 7"
