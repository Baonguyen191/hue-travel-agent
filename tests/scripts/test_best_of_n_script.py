"""Test scripts/train/best_of_n.py: tham số, sinh mẫu (bản giả, không mạng), chạy tiếp, select.

Không dùng Ollama và không đọc data/hue.sqlite: `load_usable_places` và `rl_requests` được thay
bằng dữ liệu giả của tests/training/factories.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.train import best_of_n as script
from tests.training.factories import PLACES, REQUEST, VALID_RAW
from travel_agent.training.best_of_n import ScoredSample, sample_seed, select_best
from travel_agent.training.dataset import DatasetSample
from travel_agent.training.generator import (
    DEFAULT_HOST,
    Generation,
    PlanGenerator,
    itinerary_format_schema,
)
from travel_agent.training.parsing import parse_itinerary
from travel_agent.training.requests import request_key
from travel_agent.training.reward import RewardBreakdown
from travel_agent.training.rl_config import load_rl_config

REPO = Path(__file__).parents[2]
RL_YAML = REPO / "configs" / "rl.yaml"
RUN_NAME = "rl-test"
ROUND_DIR = "round-1"
EXIT_OK, EXIT_USAGE, EXIT_EMPTY = 0, 2, 4

# Ba request khác nhau (khác ngày bắt đầu), đủ cho requests_per_round = 3.
REQUESTS = [
    REQUEST.model_copy(update={"start_date": REQUEST.start_date + dt.timedelta(days=offset)})
    for offset in range(3)
]
KEYS = [request_key(request) for request in REQUESTS]


class FakeGenerator:
    """Trả đúng VALID_RAW, không mạng."""

    def generate(
        self, messages: list[dict[str, str]], format_schema: dict[str, Any] | None = None
    ) -> Generation:
        return Generation(content=VALID_RAW)


def _write_config(tmp_path: Path, *, samples: int = 2, per_round: int = 3) -> Path:
    config = load_rl_config(RL_YAML)
    updated = config.model_copy(
        update={
            "rl": config.rl.model_copy(
                update={"run_name": RUN_NAME, "runs_dir": tmp_path / "runs"}
            ),
            "best_of_n": config.best_of_n.model_copy(
                update={"samples": samples, "requests_per_round": per_round, "threshold": 0.9}
            ),
        }
    )
    path = tmp_path / "rl.yaml"
    path.write_text(yaml.safe_dump(updated.model_dump(mode="json")), encoding="utf-8")
    return path


def _run_dir(config_path: Path) -> Path:
    return load_rl_config(config_path).rl.run_dir / ROUND_DIR


@pytest.fixture
def stub_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(script, "rl_requests", lambda params: list(REQUESTS))
    monkeypatch.setattr(script, "load_usable_places", lambda db: list(PLACES))


class Recorder:
    """Ghi lại mỗi lần dựng generator; mỗi lần sinh còn ghi số dòng đã có trong samples.jsonl."""

    def __init__(self, samples_path: Path | None = None) -> None:
        self.samples_path = samples_path
        self.calls: list[dict[str, Any]] = []
        self.lines_seen: list[int] = []

    def factory(self, model: str, *, host: str, temperature: float, seed: int) -> PlanGenerator:
        self.calls.append({"model": model, "host": host, "temperature": temperature, "seed": seed})
        return _RecordingGenerator(self)


class _RecordingGenerator:
    def __init__(self, recorder: Recorder) -> None:
        self._recorder = recorder

    def generate(
        self, messages: list[dict[str, str]], format_schema: dict[str, Any] | None = None
    ) -> Generation:
        path = self._recorder.samples_path
        seen = 0
        if path is not None and path.is_file():
            seen = len(path.read_text(encoding="utf-8").splitlines())
        self._recorder.lines_seen.append(seen)
        return Generation(content=VALID_RAW)


def _read_lines(path: Path) -> list[ScoredSample]:
    return [
        ScoredSample.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# --- tham số -----------------------------------------------------------------------------------


def test_parse_args_generate_defaults() -> None:
    args = script.parse_args(["generate", "--round", "1", "--model", "m"])
    assert args.command == "generate"
    assert args.config == Path("configs/rl.yaml")
    assert args.host == DEFAULT_HOST
    assert args.limit is None


def test_parse_args_generate_limit_and_host() -> None:
    args = script.parse_args(
        ["generate", "--round", "2", "--model", "m", "--limit", "100", "--host", "http://h:1"]
    )
    assert (args.round, args.limit, args.host) == (2, 100, "http://h:1")


def test_parse_args_select() -> None:
    args = script.parse_args(["select", "--round", "3"])
    assert args.command == "select"
    assert args.round == 3


def test_parse_args_requires_subcommand() -> None:
    with pytest.raises(SystemExit):
        script.parse_args([])


def test_round_zero_is_usage_error(tmp_path: Path, stub_data: None) -> None:
    config = _write_config(tmp_path)
    code = script.main(["select", "--config", str(config), "--round", "0"])
    assert code == EXIT_USAGE


# --- generate ----------------------------------------------------------------------------------


def test_generate_writes_each_sample_as_it_is_made(tmp_path: Path, stub_data: None) -> None:
    config = _write_config(tmp_path, samples=2, per_round=3)
    samples_path = _run_dir(config) / script.SAMPLES_FILE
    recorder = Recorder(samples_path)

    code = script.main(
        ["generate", "--config", str(config), "--round", "1", "--model", "m", "--limit", "2"],
        make_generator=recorder.factory,
    )

    assert code == EXIT_OK
    assert len(recorder.calls) == 4  # 2 request x 2 mẫu
    # Trước mỗi lần sinh, số dòng đã ghi đúng bằng số lần sinh trước đó: ghi dần, không gom cuối.
    assert recorder.lines_seen == [0, 1, 2, 3]
    lines = _read_lines(samples_path)
    assert [(line.key, line.index) for line in lines] == [
        (KEYS[0], 0),
        (KEYS[0], 1),
        (KEYS[1], 0),
        (KEYS[1], 1),
    ]


def test_generate_passes_config_temperature_seed_and_schema(
    tmp_path: Path, stub_data: None
) -> None:
    config = _write_config(tmp_path, samples=2, per_round=1)
    seen_schemas: list[object] = []

    class SchemaGenerator:
        def generate(
            self, messages: list[dict[str, str]], format_schema: dict[str, Any] | None = None
        ) -> Generation:
            seen_schemas.append(format_schema)
            return Generation(content=VALID_RAW)

    calls: list[dict[str, Any]] = []

    def factory(model: str, *, host: str, temperature: float, seed: int) -> PlanGenerator:
        calls.append({"model": model, "host": host, "temperature": temperature, "seed": seed})
        return SchemaGenerator()

    code = script.main(
        ["generate", "--config", str(config), "--round", "1", "--model", "qwen-x"],
        make_generator=factory,
    )

    base_seed = load_rl_config(RL_YAML).rl.seed
    assert code == EXIT_OK
    assert [call["model"] for call in calls] == ["qwen-x", "qwen-x"]
    assert {call["temperature"] for call in calls} == {
        load_rl_config(RL_YAML).best_of_n.temperature
    }
    assert [call["seed"] for call in calls] == [
        sample_seed(base_seed, KEYS[0], 1, 0),
        sample_seed(base_seed, KEYS[0], 1, 1),
    ]
    assert len(set(call["seed"] for call in calls)) == 2
    assert seen_schemas == [itinerary_format_schema(REQUESTS[0].num_days)] * 2


def test_generate_scores_each_sample(tmp_path: Path, stub_data: None) -> None:
    config = _write_config(tmp_path, samples=1, per_round=1)
    script.main(
        ["generate", "--config", str(config), "--round", "1", "--model", "m"],
        make_generator=Recorder().factory,
    )

    (line,) = _read_lines(_run_dir(config) / script.SAMPLES_FILE)
    assert line.raw == VALID_RAW
    assert line.reward.parsed is True
    assert line.latency_s >= 0


def test_generate_resumes_and_skips_finished_samples(tmp_path: Path, stub_data: None) -> None:
    config = _write_config(tmp_path, samples=2, per_round=3)
    samples_path = _run_dir(config) / script.SAMPLES_FILE

    first = Recorder(samples_path)
    script.main(
        ["generate", "--config", str(config), "--round", "1", "--model", "m", "--limit", "1"],
        make_generator=first.factory,
    )
    assert len(first.calls) == 2

    # Đứt giữa chừng: dòng cuối dở dang, không có xuống dòng.
    with samples_path.open("a", encoding="utf-8") as handle:
        handle.write('{"key": "dở dang')

    second = Recorder(samples_path)
    code = script.main(
        ["generate", "--config", str(config), "--round", "1", "--model", "m", "--limit", "2"],
        make_generator=second.factory,
    )

    assert code == EXIT_OK
    # Chỉ sinh phần còn thiếu: 2 mẫu của request thứ hai, không sinh lại request đầu.
    assert len(second.calls) == 2
    assert {call["seed"] for call in second.calls} == {
        sample_seed(load_rl_config(RL_YAML).rl.seed, KEYS[1], 1, index) for index in (0, 1)
    }
    lines, broken = script.read_samples(samples_path)
    assert broken == 1
    assert sorted((line.key, line.index) for line in lines) == sorted(
        (key, index) for key in KEYS[:2] for index in (0, 1)
    )
    # Dòng dở dang vẫn nằm đó, nhưng không làm hỏng dòng mới ghi sau nó.
    assert samples_path.read_text(encoding="utf-8").count("\n") == 5


def test_generate_is_a_noop_when_round_is_complete(tmp_path: Path, stub_data: None) -> None:
    config = _write_config(tmp_path, samples=1, per_round=2)
    script.main(
        ["generate", "--config", str(config), "--round", "1", "--model", "m"],
        make_generator=Recorder().factory,
    )

    again = Recorder()
    code = script.main(
        ["generate", "--config", str(config), "--round", "1", "--model", "m"],
        make_generator=again.factory,
    )
    assert code == EXIT_OK
    assert again.calls == []


def test_generate_round_beyond_available_prompts_fails(tmp_path: Path, stub_data: None) -> None:
    config = _write_config(tmp_path, samples=1, per_round=2)  # 3 request có sẵn, vòng 2 cần 4..5
    with pytest.raises(ValueError):
        script.main(
            ["generate", "--config", str(config), "--round", "2", "--model", "m"],
            make_generator=Recorder().factory,
        )


# --- select ------------------------------------------------------------------------------------


def _variant_raw() -> str:
    """Cùng lịch trình như VALID_RAW nhưng bữa trưa là quán cà phê: để biết mẫu nào được chọn."""
    data = json.loads(VALID_RAW)
    data["days"][0]["stops"][1]["place_id"] = "t:cafe"
    return json.dumps(data)


def _write_samples(config: Path, rows: list[tuple[str, int, float, str]]) -> None:
    path = _run_dir(config) / script.SAMPLES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, index, total, raw in rows:
        reward = RewardBreakdown(total=total, parsed=True, valid=True, penalties={})
        sample = ScoredSample(
            key=key, index=index, seed=index, raw=raw, reward=reward, latency_s=2.0
        )
        lines.append(sample.model_dump_json())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_select_end_to_end(tmp_path: Path, stub_data: None) -> None:
    config = _write_config(tmp_path, samples=2, per_round=3)
    _write_samples(
        config,
        [
            (KEYS[0], 0, 0.4, VALID_RAW),
            (KEYS[0], 1, 0.95, _variant_raw()),  # thắng: reward cao nhất
            (KEYS[1], 0, 0.6, VALID_RAW),  # dưới ngưỡng 0,9: bị loại
            (KEYS[1], 1, 0.6, _variant_raw()),
            (KEYS[2], 0, 0.95, VALID_RAW),  # hòa: mẫu số 0 thắng
            (KEYS[2], 1, 0.95, _variant_raw()),
        ],
    )

    code = script.main(["select", "--config", str(config), "--round", "1"])

    assert code == EXIT_OK
    round_dir = _run_dir(config)
    rows = [
        DatasetSample.model_validate_json(line)
        for line in (round_dir / script.DATASET_FILE).read_text(encoding="utf-8").splitlines()
    ]
    assert [row.key for row in rows] == [KEYS[0], KEYS[2]]
    cafe_answer, museum_answer = rows[0].messages[-1]["content"], rows[1].messages[-1]["content"]
    assert "t:cafe" in cafe_answer  # mẫu index 1 của KEYS[0] được giữ
    assert "t:lunch" in museum_answer  # hòa: mẫu index 0 của KEYS[2] được giữ
    assert rows[0].messages[-1]["role"] == "assistant"
    assert all(parse_itinerary(row.messages[-1]["content"]) is not None for row in rows)

    stats = json.loads((round_dir / script.STATS_FILE).read_text(encoding="utf-8"))
    assert stats["requests"] == 3
    assert stats["samples"] == 6
    assert stats["kept"] == 2
    assert stats["keep_rate"] == pytest.approx(2 / 3)


def test_select_matches_pure_selection(tmp_path: Path, stub_data: None) -> None:
    """Dataset ghi ra đúng mẫu mà `select_best` chọn, không có logic chọn riêng trong script."""
    config = _write_config(tmp_path, samples=2, per_round=1)
    rows = [(KEYS[0], 0, 0.7, VALID_RAW), (KEYS[0], 1, 0.91, _variant_raw())]
    _write_samples(config, rows)
    scored = _read_lines(_run_dir(config) / script.SAMPLES_FILE)

    script.main(["select", "--config", str(config), "--round", "1"])

    best = select_best(scored, 0.9)
    assert best is not None and best.index == 1
    (row,) = [
        DatasetSample.model_validate_json(line)
        for line in (_run_dir(config) / script.DATASET_FILE)
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert (
        row.messages[-1]["content"]
        == script.to_dataset_sample(
            script.round_run_prompts(load_rl_config(config), 1)[0], best.raw
        ).messages[-1]["content"]
    )


def test_select_with_nothing_kept_exits_four(tmp_path: Path, stub_data: None) -> None:
    config = _write_config(tmp_path, samples=1, per_round=2)
    _write_samples(config, [(KEYS[0], 0, 0.3, VALID_RAW), (KEYS[1], 0, 0.5, VALID_RAW)])

    code = script.main(["select", "--config", str(config), "--round", "1"])

    assert code == EXIT_EMPTY
    round_dir = _run_dir(config)
    assert (round_dir / script.DATASET_FILE).read_text(encoding="utf-8") == ""
    stats = json.loads((round_dir / script.STATS_FILE).read_text(encoding="utf-8"))
    assert stats["kept"] == 0


def test_select_without_samples_is_usage_error(tmp_path: Path, stub_data: None) -> None:
    config = _write_config(tmp_path)
    code = script.main(["select", "--config", str(config), "--round", "1"])
    assert code == EXIT_USAGE


def test_select_rejects_samples_outside_the_round(tmp_path: Path, stub_data: None) -> None:
    config = _write_config(tmp_path, samples=1, per_round=1)
    unknown = "f" * 16
    _write_samples(config, [(unknown, 0, 1.0, VALID_RAW)])

    code = script.main(["select", "--config", str(config), "--round", "1"])
    assert code == EXIT_USAGE


def test_select_skips_broken_lines(tmp_path: Path, stub_data: None) -> None:
    config = _write_config(tmp_path, samples=1, per_round=1)
    _write_samples(config, [(KEYS[0], 0, 1.0, VALID_RAW)])
    path = _run_dir(config) / script.SAMPLES_FILE
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"key": "dở dang\n')

    code = script.main(["select", "--config", str(config), "--round", "1"])

    assert code == EXIT_OK
    assert (_run_dir(config) / script.DATASET_FILE).read_text(encoding="utf-8").count("\n") == 1
