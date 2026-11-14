import hashlib
import json
import sqlite3
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
from travel_agent.training.generator import Generation, GenerationError
from travel_agent.training.requests import EVAL_SIZE, TEST_SIZE, read_eval_set


class FakeGenerator:
    created: list[dict[str, Any]] = []

    def __init__(self, model: str, **kwargs: Any) -> None:
        self.model = model
        FakeGenerator.created.append(kwargs)

    def generate(self, messages: list[dict[str, str]]) -> Generation:
        return Generation(content="không phải json", done_reason="stop")


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


def _tables(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    finally:
        conn.close()


def test_load_usable_places_does_not_modify_db_without_reviews_table(db: Path) -> None:
    """DB là dependency của DVC: eval không được ghi vào nó."""
    assert "place_reviews" not in _tables(db)
    before = hashlib.md5(db.read_bytes()).hexdigest()
    places = load_usable_places(db)
    assert len(places) == len(make_pool(per_category=6))
    assert hashlib.md5(db.read_bytes()).hexdigest() == before
    assert "place_reviews" not in _tables(db)


def test_load_usable_places_works_in_non_ascii_path(tmp_path: Path) -> None:
    folder = tmp_path / "Máy tính #1"
    folder.mkdir()
    path = folder / "hue.sqlite"
    repo = SqlitePlaceRepository(path)
    repo.upsert_many(make_pool(per_category=2))
    repo.close()
    assert len(load_usable_places(path)) == len(make_pool(per_category=2))


def test_load_usable_places_keeps_reviews_table_untouched(db: Path) -> None:
    store = ReviewStore(db)
    store.save(ReviewInput(place_id="t:cafe/0", status=ReviewStatus.REJECTED), NOW)
    store.close()
    before = hashlib.md5(db.read_bytes()).hexdigest()
    ids = {place.id for place in load_usable_places(db)}
    assert "t:cafe/0" not in ids
    assert hashlib.md5(db.read_bytes()).hexdigest() == before


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
    assert run_eval_cmd(db, evalset, tmp_path / "second.json", "--baseline", str(baseline)) == 3


def test_eval_refuses_baseline_run_under_other_conditions(
    db: Path,
    evalset: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(commands, "OllamaGenerator", FakeGenerator)
    first = tmp_path / "first.json"
    assert run_eval_cmd(db, evalset, first) == 0
    other = json.loads(first.read_text(encoding="utf-8"))
    other["meta"]["db_sha256"] = "0" * 64
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(other), encoding="utf-8")
    capsys.readouterr()
    second = tmp_path / "second.json"
    assert run_eval_cmd(db, evalset, second, "--baseline", str(baseline)) == 2
    assert "db_sha256" in capsys.readouterr().err
    assert second.exists()  # báo cáo của lần chạy vẫn được ghi


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


def test_load_usable_places_applies_reviewer_overrides(db: Path) -> None:
    store = ReviewStore(db)
    store.save(
        ReviewInput(place_id="t:cafe/2", status=ReviewStatus.APPROVED, name_override="Mới"), NOW
    )
    store.close()
    names = {place.id: place.name for place in load_usable_places(db)}
    assert names["t:cafe/2"] == "Mới"


def test_eval_passes_gate_against_equal_baseline(
    db: Path, evalset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(commands, "OllamaGenerator", FakeGenerator)
    first = tmp_path / "first.json"
    assert run_eval_cmd(db, evalset, first) == 0
    second = tmp_path / "second.json"
    assert run_eval_cmd(db, evalset, second, "--baseline", str(first)) == 0


def test_eval_refuses_missing_baseline_before_running(
    db: Path, evalset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(commands, "OllamaGenerator", FakeGenerator)
    out = tmp_path / "out.json"
    missing = tmp_path / "nope.json"
    assert run_eval_cmd(db, evalset, out, "--baseline", str(missing)) == 2
    assert not out.exists()


def test_eval_refuses_malformed_baseline(
    db: Path, evalset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(commands, "OllamaGenerator", FakeGenerator)
    out = tmp_path / "out.json"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"x": 1}), encoding="utf-8")
    assert run_eval_cmd(db, evalset, out, "--baseline", str(bad)) == 2
    assert not out.exists()
    bad.write_text("không phải json", encoding="utf-8")
    assert run_eval_cmd(db, evalset, out, "--baseline", str(bad)) == 2
    assert not out.exists()


def test_eval_meta_records_generation_config(
    db: Path, evalset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(commands, "OllamaGenerator", FakeGenerator)
    out = tmp_path / "a.json"
    assert run_eval_cmd(db, evalset, out, "--host", "http://h:1", "--no-schema") == 0
    meta = json.loads(out.read_text(encoding="utf-8"))["meta"]
    assert meta["schema_format"] is False
    assert meta["limit"] == 5
    assert meta["host"] == "http://h:1"


def test_eval_meta_limit_is_all_when_unset(
    db: Path, evalset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(commands, "OllamaGenerator", FakeGenerator)
    out = tmp_path / "a.json"
    base = ["eval", "--db", str(db), "--evalset", str(evalset), "--model", "fake"]
    assert main([*base, "--out", str(out)]) == 0
    meta = json.loads(out.read_text(encoding="utf-8"))["meta"]
    assert meta["limit"] == "all"
    assert meta["schema_format"] is True


def test_eval_passes_num_ctx_and_records_it_in_meta(
    db: Path, evalset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(commands, "OllamaGenerator", FakeGenerator)
    FakeGenerator.created.clear()
    default_out = tmp_path / "d.json"
    assert run_eval_cmd(db, evalset, default_out) == 0
    assert FakeGenerator.created[-1]["num_ctx"] == 8192
    assert json.loads(default_out.read_text(encoding="utf-8"))["meta"]["num_ctx"] == 8192
    out = tmp_path / "c.json"
    assert run_eval_cmd(db, evalset, out, "--num-ctx", "4096") == 0
    assert FakeGenerator.created[-1]["num_ctx"] == 4096
    assert json.loads(out.read_text(encoding="utf-8"))["meta"]["num_ctx"] == 4096


def test_eval_outcomes_keep_raw_output_and_done_reason(
    db: Path, evalset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(commands, "OllamaGenerator", FakeGenerator)
    out = tmp_path / "r.json"
    assert run_eval_cmd(db, evalset, out) == 0
    lines = out.with_suffix(".outcomes.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    assert first["raw"] == "không phải json"
    assert first["done_reason"] == "stop"
    assert first["stops_per_day"] == []


def test_eval_keeps_outcomes_written_before_a_generation_error(
    db: Path, evalset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailsOnThird(FakeGenerator):
        calls = 0

        def generate(self, messages: list[dict[str, str]]) -> Generation:
            FailsOnThird.calls += 1
            if FailsOnThird.calls == 3:
                raise GenerationError("Ollama chết")
            return super().generate(messages)

    monkeypatch.setattr(commands, "OllamaGenerator", FailsOnThird)
    out = tmp_path / "reports" / "run.json"
    with pytest.raises(GenerationError):
        run_eval_cmd(db, evalset, out)
    lines = out.with_suffix(".outcomes.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all(json.loads(line)["raw"] == "không phải json" for line in lines)
    assert not out.exists()  # báo cáo tổng hợp chỉ ghi khi chạy xong
