"""Giữ `dvc.yaml` khớp với những gì lệnh eval thật sự import."""

from pathlib import Path

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
