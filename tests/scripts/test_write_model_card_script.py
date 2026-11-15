"""Test scripts/train/write_model_card.py: ghép số liệu có sẵn thành model card.

`build_model_card` và `write_model_card` được thay bằng bản ghi lại tham số.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from scripts.train import write_model_card as card_script
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
