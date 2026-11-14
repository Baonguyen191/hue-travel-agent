"""Giữ `dvc.yaml` khớp với những gì lệnh eval thật sự import."""

from pathlib import Path
from typing import Any

import yaml

DVC_YAML = Path(__file__).parents[2] / "dvc.yaml"

BASELINE_EVAL_DEPS = (
    "data/hue.sqlite",
    "data/eval/hue_eval_v1.jsonl",
    "src/travel_agent/planning",
    "src/travel_agent/training",
    "src/travel_agent/validation",
    "src/travel_agent/routing",
    "src/travel_agent/domain",
    "src/travel_agent/review",
    "src/travel_agent/data/place_repository.py",
)


def test_baseline_eval_depends_on_every_module_it_imports() -> None:
    lines = [line.strip() for line in DVC_YAML.read_text(encoding="utf-8").splitlines()]
    for dep in BASELINE_EVAL_DEPS:
        assert f"- {dep}" in lines, dep


def test_baseline_eval_passes_num_ctx_from_params() -> None:
    assert "--num-ctx ${generation.num_ctx}" in DVC_YAML.read_text(encoding="utf-8")


def _stages() -> dict[str, Any]:
    stages = yaml.safe_load(DVC_YAML.read_text(encoding="utf-8"))["stages"]
    assert isinstance(stages, dict)
    return stages


# Lệnh build-dataset/check-dataset import cùng các module như lệnh eval (qua training.commands).
DATASET_CODE_DEPS = BASELINE_EVAL_DEPS[2:]


def test_dataset_stages_depend_on_inputs_and_code() -> None:
    stages = _stages()
    build, check = stages["build_dataset"], stages["check_dataset"]
    for stage in (build, check):
        for dep in ("data/hue.sqlite", "data/eval/hue_eval_v1.jsonl", *DATASET_CODE_DEPS):
            assert dep in stage["deps"], dep
        assert "--config configs/dataset.yaml" in stage["cmd"]
    assert build["outs"] == ["data/sft/hue_sft_v1.jsonl"]
    assert "data/sft/hue_sft_v1.jsonl" in check["deps"]
    assert "--dataset data/sft/hue_sft_v1.jsonl" in check["cmd"]


def test_dataset_stages_track_their_config_sections() -> None:
    stages = _stages()
    assert stages["build_dataset"]["params"] == [{"configs/dataset.yaml": ["dataset"]}]
    assert stages["check_dataset"]["params"] == [{"configs/dataset.yaml": ["check"]}]
    assert stages["build_dataset"]["metrics"] == [{"data/sft/manifest.json": {"cache": False}}]
    assert stages["check_dataset"]["metrics"] == [{"reports/dataset/check.json": {"cache": False}}]


def test_check_dataset_stage_never_skips_the_token_check() -> None:
    assert "--allow-skip-tokens" not in _stages()["check_dataset"]["cmd"]
