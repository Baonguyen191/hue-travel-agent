"""Giữ `dvc.yaml` khớp với những gì từng stage thật sự import."""

import ast
from pathlib import Path
from typing import Any

import yaml

DVC_YAML = Path(__file__).parents[2] / "dvc.yaml"

SRC = Path(__file__).parents[2] / "src"
INPUT_DEPS = ("data/hue.sqlite", "data/eval/hue_eval_v1.jsonl")
# Mã chỉ phục vụ SFT: đổi chúng không được làm baseline hay dataset bị tính lại.
SFT_ONLY_MODULES = ("sft_data.py", "export.py", "model_card.py", "sft_config.py")
# Module gốc mà từng lệnh CLI (training/commands.py) gọi tới; phần còn lại suy ra từ import.
SHARED_ROOTS = (
    "travel_agent.review.store",
    "travel_agent.review.models",
    "travel_agent.data.place_repository",
    "travel_agent.routing.travel_time",
    "travel_agent.domain.models",
)
STAGE_ROOTS = {
    "baseline_eval": (
        "travel_agent.training.requests",
        "travel_agent.training.runner",
        "travel_agent.training.generator",
        "travel_agent.training.metrics",
        "travel_agent.training.tracking",
    ),
    "build_dataset": ("travel_agent.training.dataset",),
    "check_dataset": (
        "travel_agent.training.dataset_check",
        "travel_agent.training.dataset",
    ),
}
# Stage train/export/eval_sft vẫn theo dõi cả thư mục mã.
SFT_CODE_DEPS = (
    "src/travel_agent/planning",
    "src/travel_agent/training",
    "src/travel_agent/validation",
    "src/travel_agent/routing",
    "src/travel_agent/domain",
    "src/travel_agent/review",
    "src/travel_agent/data/place_repository.py",
)


def _module_file(module: str) -> Path | None:
    path = SRC / (module.replace(".", "/") + ".py")
    return path if path.is_file() else None


def _imported_modules(path: Path) -> set[str]:
    """Module travel_agent.* mà file import, kể cả import trong hàm."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("travel_agent"):
            found.add(str(node.module))
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names if a.name.startswith("travel_agent"))
    return found


def _import_closure(roots: tuple[str, ...]) -> set[str]:
    """Đường dẫn (tương đối gốc repo) của mọi file nguồn mà các module gốc import tới."""
    seen: set[str] = set()
    todo = list(roots)
    while todo:
        module = todo.pop()
        path = _module_file(module)
        if path is None or module in seen:
            continue
        seen.add(module)
        todo.extend(_imported_modules(path))
    return {_module_file(m).relative_to(SRC.parent).as_posix() for m in seen if _module_file(m)}


def _stage_code_deps(stage: str) -> set[str]:
    deps = _import_closure((*STAGE_ROOTS[stage], *SHARED_ROOTS))
    return deps | {"src/travel_agent/training/commands.py"}


def _code_deps(stage: dict[str, Any]) -> set[str]:
    return {dep for dep in stage["deps"] if dep.startswith("src/")}


def test_narrowed_stages_depend_on_exactly_the_files_they_import() -> None:
    stages = _stages()
    for name in STAGE_ROOTS:
        deps = stages[name]["deps"]
        for dep in INPUT_DEPS:
            assert dep in deps, (name, dep)
        assert _code_deps(stages[name]) == _stage_code_deps(name), name


def test_narrowed_stages_do_not_depend_on_sft_only_code() -> None:
    stages = _stages()
    for name in STAGE_ROOTS:
        for dep in _code_deps(stages[name]):
            assert not (SRC.parent / dep).is_dir(), (name, dep, "phải liệt kê từng file")
            assert Path(dep).name not in SFT_ONLY_MODULES, (name, dep)


def test_baseline_eval_does_not_depend_on_dataset_or_token_code() -> None:
    """commands.py import các module này ở đầu file, nhưng lệnh eval không gọi hàm nào của chúng.

    Đổi chúng không làm đổi output eval, nên không tính lại baseline.
    """
    deps = _code_deps(_stages()["baseline_eval"])
    for name in ("chat.py", "tokens.py", "dataset.py", "dataset_check.py", "corrupt.py"):
        assert f"src/travel_agent/training/{name}" not in deps, name


def test_baseline_eval_passes_num_ctx_from_params() -> None:
    assert "--num-ctx ${generation.num_ctx}" in DVC_YAML.read_text(encoding="utf-8")


def _stages() -> dict[str, Any]:
    stages = yaml.safe_load(DVC_YAML.read_text(encoding="utf-8"))["stages"]
    assert isinstance(stages, dict)
    return stages


def test_dataset_stages_depend_on_inputs_and_code() -> None:
    stages = _stages()
    build, check = stages["build_dataset"], stages["check_dataset"]
    for stage in (build, check):
        for dep in INPUT_DEPS:
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
    for dep in SFT_CODE_DEPS:
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
