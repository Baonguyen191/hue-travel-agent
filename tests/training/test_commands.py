import json
from pathlib import Path
from typing import Any

import pytest

from tests.planning.factories import make_pool
from tests.review.conftest import NOW
from travel_agent.cli import main
from travel_agent.data.place_repository import SqlitePlaceRepository
from travel_agent.review.models import ReviewInput, ReviewStatus
from travel_agent.review.store import ReviewStore
from travel_agent.training import commands
from travel_agent.training.commands import load_usable_places
from travel_agent.training.requests import EVAL_SIZE, TEST_SIZE, read_eval_set


class FakeGenerator:
    def __init__(self, model: str, **kwargs: Any) -> None:
        self.model = model

    def generate(self, messages: list[dict[str, str]]) -> str:
        return "không phải json"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "hue.sqlite"
    repo = SqlitePlaceRepository(path)
    repo.upsert_many(make_pool(per_category=6))
    repo.close()
    return path


@pytest.fixture
def evalset(tmp_path: Path) -> Path:
    path = tmp_path / "eval.jsonl"
    assert main(["make-evalset", "--out", str(path), "--seed", "11"]) == 0
    return path


def run_eval_cmd(db: Path, evalset: Path, out: Path, *extra: str) -> int:
    base = ["eval", "--db", str(db), "--evalset", str(evalset), "--model", "fake"]
    return main([*base, "--out", str(out), "--limit", "5", *extra])


def test_make_evalset_writes_100_entries(evalset: Path) -> None:
    assert len(read_eval_set(evalset)) == EVAL_SIZE


def test_load_usable_places_drops_rejected(db: Path) -> None:
    store = ReviewStore(db)
    store.save(ReviewInput(place_id="t:cafe/0", status=ReviewStatus.REJECTED), NOW)
    store.close()
    ids = {place.id for place in load_usable_places(db)}
    assert "t:cafe/0" not in ids
    assert "t:cafe/1" in ids


def test_eval_writes_summary_and_outcomes(
    db: Path, evalset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(commands, "OllamaGenerator", FakeGenerator)
    out = tmp_path / "reports" / "run.json"
    assert run_eval_cmd(db, evalset, out, "--run-name", "smoke") == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["summary"]["n"] == 5
    assert report["summary"]["parse_error_rate"] == 1.0
    assert report["meta"]["run_name"] == "smoke"
    assert report["meta"]["model"] == "fake"
    assert report["meta"]["split"] == "dev"
    assert len(report["meta"]["evalset_sha256"]) == 64
    outcomes = (tmp_path / "reports" / "run.outcomes.jsonl").read_text(encoding="utf-8")
    assert len(outcomes.splitlines()) == 5


def test_eval_fails_gate_against_better_baseline(
    db: Path, evalset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(commands, "OllamaGenerator", FakeGenerator)
    first = tmp_path / "first.json"
    assert run_eval_cmd(db, evalset, first) == 0
    better = json.loads(first.read_text(encoding="utf-8"))
    better["summary"]["first_pass_valid_rate"] = 0.5
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(better), encoding="utf-8")
    assert run_eval_cmd(db, evalset, tmp_path / "second.json", "--baseline", str(baseline)) == 1


def test_eval_refuses_test_split_without_flag(
    db: Path, evalset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(commands, "OllamaGenerator", FakeGenerator)
    out = tmp_path / "t.json"
    assert run_eval_cmd(db, evalset, out, "--split", "test") == 2
    assert not out.exists()
    assert run_eval_cmd(db, evalset, out, "--split", "test", "--allow-test") == 0
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["n"] == min(5, TEST_SIZE)


def test_eval_refuses_missing_db(evalset: Path, tmp_path: Path) -> None:
    assert run_eval_cmd(tmp_path / "missing.sqlite", evalset, tmp_path / "x.json") == 2
