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


def _eval_flags(cmd: str) -> dict[str, str]:
    tokens = cmd.split()
    return {
        tokens[i]: tokens[i + 1]
        if i + 1 < len(tokens) and not tokens[i + 1].startswith("--")
        else ""
        for i in range(len(tokens))
        if tokens[i].startswith("--")
    }


def test_sft_stages_chain_dataset_check_training_export_and_eval() -> None:
    stages = _stages()
    sft, export, evaluate = stages["sft"], stages["export_sft"], stages["eval_sft"]
    assert {"data/sft/hue_sft_v1.jsonl", "reports/dataset/check.json"} <= set(sft["deps"])
    assert sft["outs"] == ["models/sft/${sft.run_name}/adapters"]
    assert sft["cmd"].startswith("${sft.python} scripts/train/sft.py")
    assert "models/sft/${sft.run_name}/adapters" in export["deps"]
    assert "--record" in export["cmd"]
    assert "models/sft/${sft.run_name}/export.json" in evaluate["deps"]
    for dep in DATASET_CODE_DEPS:
        assert dep in sft["deps"] and dep in evaluate["deps"], dep


def test_sft_eval_runs_like_the_baseline_except_model_and_gate() -> None:
    """Baseline và SFT chỉ khác trọng số: mọi tham số sinh và dữ liệu eval phải giống nhau."""
    stages = _stages()
    baseline = _eval_flags(stages["baseline_eval"]["cmd"])
    sft = _eval_flags(stages["eval_sft"]["cmd"][0])
    differing = {"--model", "--run-name", "--out"}
    assert {k: v for k, v in baseline.items() if k not in differing} == {
        k: v for k, v in sft.items() if k not in differing | {"--baseline"}
    }
    assert sft["--baseline"] == "reports/eval/baseline_dev.json"
    assert sft["--model"] == "${export.ollama_model}"
