"""Test scripts/train/write_model_card.py: ghép số liệu có sẵn thành model card.

`build_model_card` và `write_model_card` được thay bằng bản ghi lại tham số.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from scripts.train import write_model_card as card_script
from travel_agent.training.chat import CHAT_TEMPLATE_FILE, TOKENIZER_FILE
from travel_agent.training.model_card import sha256_file
from travel_agent.training.sft_config import load_sft_config, repo_artifacts_dir

REPO = Path(__file__).parents[2]
SFT_YAML = REPO / "configs" / "sft.yaml"
MANIFEST = {"name": "hue_sft_v1", "samples": 4000}
CHECKPOINTS = {"250": 0.61, "500": 0.72}


@pytest.fixture
def card_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    monkeypatch.chdir(tmp_path)
    config = load_sft_config(SFT_YAML)
    captured: dict[str, Any] = {}

    def fake_build(**kwargs: Any) -> dict[str, Any]:
        captured["build"] = kwargs
        return {"built": True}

    def fake_write(card: dict[str, Any], path: Path) -> None:
        captured["write"] = (card, path)

    monkeypatch.setattr(card_script, "load_sft_config", lambda path: config)
    monkeypatch.setattr(card_script, "hf_snapshot_dir", lambda repo, revision: tmp_path)
    monkeypatch.setattr(card_script, "current_commit", lambda outputs=(): "deadbeef")
    monkeypatch.setattr(card_script, "build_model_card", fake_build)
    monkeypatch.setattr(card_script, "write_model_card", fake_write)
    yield {"tmp": tmp_path, "captured": captured, "config": config}


def _args(tmp_path: Path) -> list[str]:
    return [
        "--config",
        str(SFT_YAML),
        "--manifest",
        str(tmp_path / "data" / "sft" / "manifest.json"),
        "--eval-report",
        str(tmp_path / "reports" / "eval" / "sft_dev.json"),
    ]


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_missing_manifest_is_an_error(card_env: dict[str, Any]) -> None:
    with pytest.raises(SystemExit):
        card_script.main(_args(card_env["tmp"]))
    assert "build" not in card_env["captured"]


def test_full_run_passes_each_source_to_the_card(card_env: dict[str, Any]) -> None:
    tmp: Path = card_env["tmp"]
    captured = card_env["captured"]
    config = card_env["config"]
    run_name = config.sft.run_name
    quantization = config.export.quantization
    _write_json(tmp / "data" / "sft" / "manifest.json", MANIFEST)
    _write_json(tmp / "reports" / "eval" / "sft_dev.json", {"first_pass_valid_rate": 0.7})
    artifacts = repo_artifacts_dir(run_name)
    train_metrics = {key: 1 for key in card_script.TRAIN_KEYS}
    train_metrics |= {"run_name": run_name, "log_history": [{"loss": 1.0}]}
    _write_json(artifacts / "train_metrics.json", train_metrics)
    export = {"checkpoint": 500, "quantization": quantization}
    _write_json(artifacts / "export.json", export)
    _write_json(artifacts / "checkpoints.json", CHECKPOINTS)

    assert card_script.main(_args(tmp)) == 0

    build = captured["build"]
    assert set(build["train"]) == set(card_script.TRAIN_KEYS)
    assert "log_history" not in build["train"]
    assert build["checkpoint"] == {
        "step": 500,
        "dev_first_pass_valid_rate_by_step": CHECKPOINTS,
    }
    assert build["export"] == export
    assert build["metrics_dev"] == {"first_pass_valid_rate": 0.7}
    assert build["manifest"] == MANIFEST
    assert build["git_commit"] == "deadbeef"

    card, path = captured["write"]
    assert card == {"built": True}
    assert path == repo_artifacts_dir(run_name) / "model_card.json"


def test_only_manifest_leaves_optional_sections_null(card_env: dict[str, Any]) -> None:
    tmp: Path = card_env["tmp"]
    captured = card_env["captured"]
    _write_json(tmp / "data" / "sft" / "manifest.json", MANIFEST)

    assert card_script.main(_args(tmp)) == 0

    build = captured["build"]
    assert build["train"] is None
    assert build["checkpoint"] is None
    assert build["export"] is None
    assert build["metrics_dev"] is None


# --- stage rl ----------------------------------------------------------------

RL_YAML = REPO / "configs" / "rl.yaml"
RL_DATASET_LINES = ('{"key": "a"}', '{"key": "b"}')
RL_STATS = {"requests": 100, "samples": 400, "kept": 42, "mean_reward": 0.5}
RL_DEV = {"first_pass_valid_rate": 0.3}


@pytest.fixture
def rl_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Cây thư mục tối thiểu của một run RL trong tmp_path, với configs thật được sao chép vào."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "configs").mkdir()
    shutil.copy(SFT_YAML, tmp_path / "configs" / "sft.yaml")
    shutil.copy(RL_YAML, tmp_path / "configs" / "rl.yaml")

    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / TOKENIZER_FILE).write_text("{}", encoding="utf-8")
    (snapshot / CHAT_TEMPLATE_FILE).write_text("{{ messages }}", encoding="utf-8")
    monkeypatch.setattr(card_script, "hf_snapshot_dir", lambda repo, revision: snapshot)
    monkeypatch.setattr(card_script, "current_commit", lambda outputs=(): "deadbeef")

    init = tmp_path / "models" / "sft" / "sft-v1" / "adapters" / "step-250"
    _write_bytes(init / "adapter_model.safetensors", b"sft adapter")
    dataset = tmp_path / "data" / "rl" / "rl-v1" / "round-1.jsonl"
    _write_bytes(dataset, ("\n".join(RL_DATASET_LINES) + "\n\n").encode("utf-8"))
    _write_json(dataset.with_suffix(".stats.json"), RL_STATS)
    return tmp_path


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _rl_args(tmp: Path) -> list[str]:
    return ["--stage", "rl", "--rl-config", str(tmp / "configs" / "rl.yaml")]


def _rl_artifacts(tmp: Path) -> Path:
    artifacts = tmp / "models" / "rl" / "rl-v1"
    _write_bytes(artifacts / "adapter" / "adapter_model.safetensors", b"rl adapter")
    _write_json(artifacts / "export.json", {"checkpoint": "models/rl/rl-v1/adapter"})
    _write_json(tmp / "reports" / "eval" / "rl_dev.json", RL_DEV)
    return artifacts


def test_rl_card_is_written_under_models_rl(rl_repo: Path) -> None:
    artifacts = _rl_artifacts(rl_repo)

    assert card_script.main(_rl_args(rl_repo)) == 0

    card = json.loads((artifacts / "model_card.json").read_text(encoding="utf-8"))
    assert card["stage"] == "rl"
    assert card["run_name"] == "rl-v1"
    assert card["method"] == "best_of_n"
    assert card["git_commit"] == "deadbeef"
    assert card["base_model"]["repo"] == "Qwen/Qwen3.5-4B"
    assert card["metrics_dev"] == RL_DEV
    assert card["export"] == {"checkpoint": "models/rl/rl-v1/adapter"}


def test_rl_card_parent_is_the_sft_step_it_started_from(rl_repo: Path) -> None:
    artifacts = _rl_artifacts(rl_repo)

    card_script.main(_rl_args(rl_repo))

    card = json.loads((artifacts / "model_card.json").read_text(encoding="utf-8"))
    assert card["parent"] == {
        "run_name": "sft-v1",
        "checkpoint": 250,
        "adapter_sha256": sha256_file(
            rl_repo
            / "models"
            / "sft"
            / "sft-v1"
            / "adapters"
            / "step-250"
            / "adapter_model.safetensors"
        ),
    }


def test_rl_card_dataset_and_config_values(rl_repo: Path) -> None:
    artifacts = _rl_artifacts(rl_repo)

    card_script.main(_rl_args(rl_repo))

    card = json.loads((artifacts / "model_card.json").read_text(encoding="utf-8"))
    dataset = card["dataset"]
    assert dataset["path"] == "data/rl/rl-v1/round-1.jsonl"
    assert dataset["name"] == "round-1"
    assert dataset["samples"] == len(RL_DATASET_LINES)
    assert dataset["jsonl_sha256"] == sha256_file(rl_repo / dataset["path"])
    assert dataset["stats"] == RL_STATS
    values = card["config"]["values"]
    assert set(values) == {"method", "final", "best_of_n"}
    assert values["final"]["ollama_model"] == "travel-rl-v1"
    assert values["best_of_n"]["samples"] == 4


def test_rl_card_checkpoint_hashes_the_copied_adapter(rl_repo: Path) -> None:
    artifacts = _rl_artifacts(rl_repo)

    card_script.main(_rl_args(rl_repo))

    card = json.loads((artifacts / "model_card.json").read_text(encoding="utf-8"))
    assert card["checkpoint"] == {
        "adapter": "models/rl/rl-v1/adapter",
        "adapter_sha256": sha256_file(artifacts / "adapter" / "adapter_model.safetensors"),
    }


def test_rl_card_without_export_or_adapter_leaves_those_null(rl_repo: Path) -> None:
    artifacts = rl_repo / "models" / "rl" / "rl-v1"

    assert card_script.main(_rl_args(rl_repo)) == 0

    card = json.loads((artifacts / "model_card.json").read_text(encoding="utf-8"))
    assert card["checkpoint"] is None
    assert card["export"] is None
    assert card["metrics_dev"] is None


def test_rl_card_refuses_missing_dataset(rl_repo: Path) -> None:
    (rl_repo / "data" / "rl" / "rl-v1" / "round-1.jsonl").unlink()

    with pytest.raises(SystemExit, match="dataset RL"):
        card_script.main(_rl_args(rl_repo))


def test_rl_card_refuses_missing_stats(rl_repo: Path) -> None:
    (rl_repo / "data" / "rl" / "rl-v1" / "round-1.stats.json").unlink()

    with pytest.raises(SystemExit, match="round-1.stats.json"):
        card_script.main(_rl_args(rl_repo))


def test_step_of_reads_the_sft_step_from_the_adapter_dir() -> None:
    assert card_script.step_of(Path("models/sft/sft-v1/adapters/step-250")) == 250
    with pytest.raises(SystemExit, match="step-<N>"):
        card_script.step_of(Path("models/sft/sft-v1/adapters/final"))
