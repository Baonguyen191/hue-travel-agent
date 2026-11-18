"""Lệnh `plan`: đọc yêu cầu, gọi generator giả, in JSON và trả mã thoát đúng."""

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from tests.planning.factories import make_pool
from travel_agent.cli import main
from travel_agent.data.place_repository import SqlitePlaceRepository
from travel_agent.domain.models import Category, PlanRequest, TravelMode
from travel_agent.planning.candidates import select_candidates
from travel_agent.training import commands
from travel_agent.training.commands import load_usable_places
from travel_agent.training.generator import Generation
from travel_agent.training.requests import request_key
from travel_agent.training.runner import candidate_seed

REPO_ROOT = Path(__file__).parents[2]
START = "2026-12-01"
# Đúng với yêu cầu mà lệnh plan dựng từ `--days 1 --start-date 2026-12-01`;
# các mục còn lại là mặc định.
CLI_REQUEST = PlanRequest(
    start_date=dt.date(2026, 12, 1),
    num_days=1,
    travel_mode=TravelMode.MOTORBIKE,
)


class FakeGenerator:
    created: list[dict[str, Any]] = []
    outputs: list[str] = []
    seen: list[list[dict[str, str]]] = []

    def __init__(self, model: str, **kwargs: Any) -> None:
        self.model = model
        FakeGenerator.created.append({"model": model, **kwargs})

    def generate(
        self, messages: list[dict[str, str]], format_schema: dict[str, Any] | None = None
    ) -> Generation:
        FakeGenerator.seen.append(messages)
        return Generation(content=FakeGenerator.outputs[len(FakeGenerator.seen) - 1])


@pytest.fixture(autouse=True)
def _reset_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeGenerator.created = []
    FakeGenerator.outputs = []
    FakeGenerator.seen = []
    monkeypatch.setattr(commands, "OllamaGenerator", FakeGenerator)
    monkeypatch.chdir(REPO_ROOT)  # configs/rl.yaml và configs/eval.yaml đọc theo thư mục gốc


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "hue.sqlite"
    repo = SqlitePlaceRepository(path)
    repo.upsert_many(make_pool(per_category=6))
    repo.close()
    return path


def _valid_raw(db_places: list[Any]) -> str:
    """Lịch một ngày dùng đúng candidate mà lệnh plan sẽ chọn (cùng seed, cùng request)."""
    candidates = select_candidates(CLI_REQUEST, db_places, candidate_seed(request_key(CLI_REQUEST)))
    restaurants = [p.id for p in candidates if p.category is Category.RESTAURANT][:2]
    others = [p.id for p in candidates if p.category is not Category.RESTAURANT]
    stops = [
        {"place_id": others[0], "arrive": "08:30", "depart": "10:30"},
        {"place_id": restaurants[0], "arrive": "11:30", "depart": "12:30"},
        {"place_id": restaurants[1], "arrive": "18:00", "depart": "19:00"},
    ]
    return json.dumps({"days": [{"date": START, "stops": stops}]}, ensure_ascii=False)


def _plan_args(db: Path, *extra: str) -> list[str]:
    base = ["plan", "--db", str(db), "--days", "1", "--start-date", START]
    return [*base, *extra]


def test_valid_plan_prints_json_and_exits_zero(
    db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    FakeGenerator.outputs = [_valid_raw(load_usable_places(db))]
    assert main(_plan_args(db, "--model", "fake")) == commands.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True
    assert payload["itinerary"]["days"][0]["date"] == START
    assert payload["attempts"][0]["kind"] == "generate"
    assert payload["attempts"][0]["parsed"] is True
    assert payload["dropped"] == []
    assert FakeGenerator.created[0]["model"] == "fake"


def test_still_invalid_plan_exits_three(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    FakeGenerator.outputs = ["không phải json"]
    code = main(_plan_args(db, "--model", "fake", "--max-repairs", "0"))
    assert code == commands.EXIT_PLAN_INVALID == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False
    assert payload["itinerary"] is None
    [attempt] = payload["attempts"]
    assert (attempt["kind"], attempt["parsed"], attempt["error_count"]) == ("generate", False, 0)


def test_model_defaults_to_rl_final_model(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    FakeGenerator.outputs = ["không phải json"]
    assert main(_plan_args(db, "--max-repairs", "0")) == commands.EXIT_PLAN_INVALID
    assert FakeGenerator.created[0]["model"] == "travel-rl-v1"


def test_generation_params_come_from_eval_config(db: Path) -> None:
    FakeGenerator.outputs = ["không phải json"]
    main(_plan_args(db, "--model", "fake", "--max-repairs", "0"))
    options = FakeGenerator.created[0]
    assert options["temperature"] == 0.0
    assert options["seed"] == 0
    assert options["num_predict"] == 2048
    assert options["num_ctx"] == 8192


def test_request_file_is_read(db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    request_file = tmp_path / "request.json"
    request_file.write_text(CLI_REQUEST.model_dump_json(), encoding="utf-8")
    FakeGenerator.outputs = [_valid_raw(load_usable_places(db))]
    code = main(["plan", "--db", str(db), "--request", str(request_file), "--model", "fake"])
    assert code == commands.EXIT_OK


def test_request_file_conflicts_with_flags(db: Path, tmp_path: Path) -> None:
    request_file = tmp_path / "request.json"
    request_file.write_text(CLI_REQUEST.model_dump_json(), encoding="utf-8")
    code = main(
        [
            "plan",
            "--db",
            str(db),
            "--request",
            str(request_file),
            "--model",
            "fake",
            "--pace",
            "packed",
        ]
    )
    assert code == commands.EXIT_USAGE
    assert FakeGenerator.created == []


@pytest.mark.parametrize("extra", [["--max-repairs", "-1"], ["--days", "9"]])
def test_bad_values_exit_two(db: Path, extra: list[str]) -> None:
    code = main(_plan_args(db, "--model", "fake", *extra))
    assert code == commands.EXIT_USAGE
    assert FakeGenerator.created == []


@pytest.mark.parametrize(
    "extra", [["--day-start", "25:00"], ["--start-date", "2026-13-01"], ["--pace", "lazy"]]
)
def test_unparseable_flags_exit_two_via_argparse(db: Path, extra: list[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(_plan_args(db, "--model", "fake", *extra))
    assert info.value.code == commands.EXIT_USAGE
    assert FakeGenerator.created == []


def test_missing_days_exits_two(db: Path) -> None:
    code = main(["plan", "--db", str(db), "--model", "fake", "--start-date", START])
    assert code == commands.EXIT_USAGE


def test_missing_db_exits_two(tmp_path: Path) -> None:
    code = main(_plan_args(tmp_path / "none.sqlite", "--model", "fake"))
    assert code == commands.EXIT_USAGE
