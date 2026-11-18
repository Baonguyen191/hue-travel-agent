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
# Stage train/export có gốc là một file script: quét import travel_agent trong AST của script.
SCRIPT_ROOTS = {
    "sft": ("scripts/train/sft.py",),
    "export_sft": ("scripts/train/export_gguf.py",),
    "rl": ("scripts/train/sft.py",),
    "export_rl": ("scripts/train/export_gguf.py",),
}
CARD_SCRIPT = "scripts/train/write_model_card.py"
# Eval SFT/RL chạy đúng lệnh eval của baseline (cộng commands.py), rồi ghi model card.
EVAL_STAGES = ("eval_sft", "eval_rl")
COMMAND_FILE = "src/travel_agent/training/commands.py"


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


def _root_modules(roots: tuple[str, ...]) -> list[str]:
    """Gốc là tên module (travel_agent.a.b) hoặc đường dẫn script (scripts/.../x.py)."""
    modules: list[str] = []
    for root in roots:
        if root.endswith(".py"):
            modules.extend(_imported_modules(SRC.parent / root))
        else:
            modules.append(root)
    return modules


def _import_closure(roots: tuple[str, ...]) -> set[str]:
    """Đường dẫn (tương đối gốc repo) của mọi file nguồn mà các gốc import tới."""
    seen: set[str] = set()
    todo = _root_modules(roots)
    while todo:
        module = todo.pop()
        path = _module_file(module)
        if path is None or module in seen:
            continue
        seen.add(module)
        todo.extend(_imported_modules(path))
    return {_module_file(m).relative_to(SRC.parent).as_posix() for m in seen if _module_file(m)}


def _stage_code_deps(stage: str) -> set[str]:
    if stage in SCRIPT_ROOTS:
        return _import_closure(SCRIPT_ROOTS[stage])
    if stage in EVAL_STAGES:
        baseline = _import_closure((*STAGE_ROOTS["baseline_eval"], *SHARED_ROOTS))
        return baseline | {COMMAND_FILE} | _import_closure((CARD_SCRIPT,))
    deps = _import_closure((*STAGE_ROOTS[stage], *SHARED_ROOTS))
    return deps | {COMMAND_FILE}


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


def test_script_stages_depend_on_exactly_the_files_their_script_imports() -> None:
    """sft/rl chạy scripts/train/sft.py; export_* chạy scripts/train/export_gguf.py.

    Không được liệt kê thư mục: thêm một module không liên quan không làm SFT bị tính lại.
    """
    stages = _stages()
    for name in SCRIPT_ROOTS:
        assert _code_deps(stages[name]) == _stage_code_deps(name), name
        assert not any((SRC.parent / dep).is_dir() for dep in _code_deps(stages[name])), name


def test_eval_stages_depend_on_eval_path_and_model_card_files() -> None:
    """Eval SFT/RL: đường eval của baseline (cộng commands.py) và closure của write_model_card."""
    stages = _stages()
    for name in EVAL_STAGES:
        assert _code_deps(stages[name]) == _stage_code_deps(name), name
        assert CARD_SCRIPT in stages[name]["deps"], name
        assert not any((SRC.parent / dep).is_dir() for dep in _code_deps(stages[name])), name
    assert _stage_code_deps("eval_sft") == _stage_code_deps("eval_rl")


def test_eval_stages_include_the_model_card_closure() -> None:
    """write_model_card import commands.current_commit, nên closure của commands nằm trong eval."""
    deps = _code_deps(_stages()["eval_sft"])
    assert COMMAND_FILE in deps
    assert "src/travel_agent/training/model_card.py" in deps
    assert "src/travel_agent/training/rl_config.py" in deps
    assert "src/travel_agent/training/reward_report.py" in deps


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


RL_YAML = Path(__file__).parents[2] / "configs" / "rl.yaml"
SFT_YAML = Path(__file__).parents[2] / "configs" / "sft.yaml"
EVAL_YAML = Path(__file__).parents[2] / "configs" / "eval.yaml"
RL_DATASET = "data/rl/rl-v1/round-1.jsonl"
RL_INIT_ADAPTER = "models/sft/sft-v1/adapters/step-250"


def test_rl_vars_do_not_clash_with_sft_or_eval_vars() -> None:
    """DVC gộp các file vars vào một namespace: khóa trùng sẽ làm stage đọc sai giá trị."""
    raw = yaml.safe_load(RL_YAML.read_text(encoding="utf-8"))
    others: set[str] = set()
    for path in (SFT_YAML, EVAL_YAML):
        others |= set(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert set(raw) == {"rl", "grpo", "best_of_n", "final"}
    assert set(raw) & others == set()
    assert "configs/rl.yaml" in DVC_YAML.read_text(encoding="utf-8").split("stages:")[0]


def test_rl_stage_chains_dataset_adapter_and_trains_from_step_250() -> None:
    from travel_agent.training.rl_config import load_rl_config

    stages = _stages()
    rl = stages["rl"]
    config = load_rl_config(RL_YAML)
    # Đường dẫn trong deps là chữ, phải khớp config: DVC không nội suy deps trong test này.
    assert config.final.dataset.as_posix() == RL_DATASET
    assert config.rl.init_adapter.as_posix() == RL_INIT_ADAPTER
    assert {RL_DATASET, RL_INIT_ADAPTER} <= set(rl["deps"])
    assert rl["outs"] == ["models/rl/${rl.run_name}/adapter"]
    assert rl["cmd"].startswith("${sft.python} scripts/train/sft.py --config configs/sft.yaml")
    assert f"--init-adapter {RL_INIT_ADAPTER}" in rl["cmd"]
    assert "--dataset ${final.dataset}" in rl["cmd"]
    assert "--run-dir ${rl.runs_dir}/${rl.run_name}/final" in rl["cmd"]
    assert "--learning-rate ${final.learning_rate}" in rl["cmd"]
    assert "--epochs ${final.epochs}" in rl["cmd"]
    assert "--run-name rl-v1-final" in rl["cmd"]
    assert "--adapter-out models/rl/${rl.run_name}/adapter" in rl["cmd"]
    assert {"configs/rl.yaml": ["final"]} in rl["params"]


def test_rl_export_reads_the_rl_adapter_and_records_it() -> None:
    export = _stages()["export_rl"]
    assert "models/rl/${rl.run_name}/adapter" in export["deps"]
    assert "scripts/train/export_gguf.py" in export["deps"]
    assert "--adapter models/rl/${rl.run_name}/adapter" in export["cmd"]
    assert "--name ${final.ollama_model}" in export["cmd"]
    assert "--record-out models/rl/${rl.run_name}/export.json" in export["cmd"]
    assert "--record" not in export["cmd"].replace("--record-out", "")
    assert export["metrics"] == [{"models/rl/${rl.run_name}/export.json": {"cache": False}}]
    assert {"configs/sft.yaml": ["export"]} in export["params"]


def test_rl_eval_runs_like_sft_except_model_run_name_baseline_and_out() -> None:
    """RL và SFT chỉ khác trọng số: sinh và dữ liệu eval phải giống hệt nhau."""
    stages = _stages()
    sft = _eval_flags(stages["eval_sft"]["cmd"][0])
    rl = _eval_flags(stages["eval_rl"]["cmd"][0])
    differing = {"--model", "--run-name", "--out", "--baseline"}
    assert {k: v for k, v in sft.items() if k not in differing} == {
        k: v for k, v in rl.items() if k not in differing
    }
    assert rl["--model"] == "${final.ollama_model}"
    assert rl["--run-name"] == "rl"
    assert rl["--out"] == "reports/eval/rl_dev.json"


def test_rl_eval_generation_matches_the_baseline() -> None:
    stages = _stages()
    baseline = _eval_flags(stages["baseline_eval"]["cmd"])
    rl = _eval_flags(stages["eval_rl"]["cmd"][0])
    differing = {"--model", "--run-name", "--out", "--baseline"}
    assert {k: v for k, v in baseline.items() if k not in differing} == {
        k: v for k, v in rl.items() if k not in differing
    }


def test_rl_eval_gates_against_the_sft_report() -> None:
    evaluate = _stages()["eval_rl"]
    assert _eval_flags(evaluate["cmd"][0])["--baseline"] == "reports/eval/sft_dev.json"
    assert "reports/eval/sft_dev.json" in evaluate["deps"]
    assert evaluate["metrics"] == [
        {"reports/eval/rl_dev.json": {"cache": False}},
        {"models/rl/${rl.run_name}/model_card.json": {"cache": False}},
    ]
    assert evaluate["outs"] == ["reports/eval/rl_dev.outcomes.jsonl"]


def test_rl_eval_writes_the_rl_model_card_from_stats_and_export() -> None:
    evaluate = _stages()["eval_rl"]
    card = evaluate["cmd"][1]
    assert card == "python scripts/train/write_model_card.py --stage rl --rl-config configs/rl.yaml"
    assert "models/rl/${rl.run_name}/export.json" in evaluate["deps"]
    assert "data/rl/rl-v1/round-1.stats.json" in evaluate["deps"]
    assert "scripts/train/write_model_card.py" in evaluate["deps"]
    assert {"configs/rl.yaml": ["final"]} in evaluate["params"]
