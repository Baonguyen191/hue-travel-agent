import json
from pathlib import Path

import pytest
import yaml

from tests.training.dataset_factories import pool
from travel_agent.cli import main
from travel_agent.data.place_repository import SqlitePlaceRepository
from travel_agent.training.commands import EXIT_DATASET_INVALID, EXIT_OK, EXIT_USAGE
from travel_agent.training.dataset import DatasetSample
from travel_agent.training.requests import EvalEntry, Split, generate_requests, write_eval_set

SEED = 42
CONFIG = {
    "dataset": {
        "name": "test_sft",
        "request_seed": SEED,
        "target_samples": 12,
        "repair_share": 0.25,
        "max_requests": 30,
        "solver_time_limit_s": 10.0,
    },
    "check": {
        "max_tokens": 100_000,
        "tokenizer": {"repo": "test/none", "revision": "0"},
        "distribution": {"min_share": 0.0, "max_share": 1.0},
    },
}


@pytest.fixture
def files(tmp_path: Path) -> dict[str, Path]:
    db = tmp_path / "hue.sqlite"
    repo = SqlitePlaceRepository(db)
    repo.upsert_many(pool())
    repo.close()
    # Bộ eval chứa 2 request đầu của luồng train: build phải loại chúng.
    leaked = generate_requests(2, SEED)
    evalset = tmp_path / "eval.jsonl"
    write_eval_set(
        [EvalEntry(key=str(i), split=Split.TEST, request=r) for i, r in enumerate(leaked)], evalset
    )
    config = tmp_path / "dataset.yaml"
    config.write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    return {"db": db, "evalset": evalset, "config": config, "dir": tmp_path}


def build(files: dict[str, Path], name: str) -> tuple[int, Path, Path]:
    out, manifest = files["dir"] / f"{name}.jsonl", files["dir"] / f"{name}.manifest.json"
    code = main(
        [
            "build-dataset",
            "--config",
            str(files["config"]),
            "--db",
            str(files["db"]),
            "--evalset",
            str(files["evalset"]),
            "--out",
            str(out),
            "--manifest",
            str(manifest),
        ]
    )
    return code, out, manifest


def check(files: dict[str, Path], dataset: Path, *extra: str) -> tuple[int, dict[str, object]]:
    report = files["dir"] / "check.json"
    code = main(
        [
            "check-dataset",
            "--config",
            str(files["config"]),
            "--db",
            str(files["db"]),
            "--evalset",
            str(files["evalset"]),
            "--dataset",
            str(dataset),
            "--out",
            str(report),
            "--tokenizer-dir",
            str(files["dir"] / "no-tokenizer"),
            *extra,
        ]
    )
    return code, json.loads(report.read_text(encoding="utf-8"))


def test_build_writes_dataset_and_manifest_reproducibly(files: dict[str, Path]) -> None:
    code, out, manifest_path = build(files, "a")
    assert code == EXIT_OK
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["samples"] == 12
    assert manifest["eval_collisions_removed"] == 2
    assert manifest["samples_by_kind"] == {"generate": 9, "repair": 3}
    _, again, again_manifest = build(files, "b")
    assert out.read_bytes() == again.read_bytes()
    assert manifest_path.read_text(encoding="utf-8") == again_manifest.read_text(encoding="utf-8")


def test_check_fails_without_a_real_tokenizer_unless_allowed(files: dict[str, Path]) -> None:
    _, out, _ = build(files, "a")
    code, report = check(files, out)
    assert code == EXIT_DATASET_INVALID
    assert report["token_check"] == "missing"
    assert report["failure_counts"] == {"tokens_not_checked": 1}

    code, report = check(files, out, "--allow-skip-tokens")
    assert code == EXIT_OK
    assert report["token_check"] == "skipped"
    assert report["passed"] is True


def test_check_catches_a_leaked_eval_request(files: dict[str, Path]) -> None:
    _, out, _ = build(files, "a")
    leaked = generate_requests(2, SEED)[0]
    first = DatasetSample.model_validate_json(out.read_text(encoding="utf-8").splitlines()[0])
    # Ghi mẫu đầu với request của bộ eval: phải bị bắt dù mọi thứ khác đúng.
    tampered = first.model_copy(update={"request": leaked})
    lines = out.read_text(encoding="utf-8").splitlines()
    out.write_text("\n".join([tampered.model_dump_json(), *lines[1:]]) + "\n", encoding="utf-8")
    code, report = check(files, out, "--allow-skip-tokens")
    assert code == EXIT_DATASET_INVALID
    assert "eval_leak" in report["failure_counts"]


def test_build_fails_when_target_cannot_be_reached(files: dict[str, Path]) -> None:
    config = dict(CONFIG, dataset={**CONFIG["dataset"], "max_requests": 5})
    files["config"].write_text(yaml.safe_dump(config), encoding="utf-8")
    code, out, manifest = build(files, "short")
    assert code == EXIT_DATASET_INVALID
    assert not out.exists() and not manifest.exists()


def test_commands_refuse_missing_inputs(files: dict[str, Path]) -> None:
    files["db"] = files["dir"] / "missing.sqlite"
    assert build(files, "x")[0] == EXIT_USAGE
