"""Test lệnh parse và qu-eval với generator giả (monkeypatch _generator, không gọi Ollama)."""

import json
from pathlib import Path
from typing import Any

import pytest

from travel_agent import cli as top_cli
from travel_agent.training.generator import Generation, GenerationError
from travel_agent.understanding import cli as qu_cli

REPO_ROOT = Path(__file__).parents[2]
HUE_DB = REPO_ROOT / "data" / "hue.sqlite"
EVAL_FILE = REPO_ROOT / "data" / "eval" / "query_eval_v1.jsonl"
requires_inputs = pytest.mark.skipif(
    not (HUE_DB.exists() and EVAL_FILE.exists()), reason="thiếu DB hoặc bộ eval"
)

OUT_OF_SCOPE = json.dumps(
    {
        "intent": "out_of_scope",
        "date_text": None,
        "duration_text": None,
        "travel_mode": None,
        "pace": None,
        "day_start": None,
        "day_end": None,
        "interest_phrases": [],
        "must_include_mentions": [],
        "exclude_mentions": [],
        "exclude_category_phrases": [],
        "soft_preferences": [],
        "city": None,
    },
    ensure_ascii=False,
)


class FixedGenerator:
    def __init__(self, content: str | None = None, error: Exception | None = None) -> None:
        self._content = content
        self._error = error

    def generate(
        self, messages: list[dict[str, str]], format_schema: dict[str, Any] | None = None
    ) -> Generation:
        if self._error is not None:
            raise self._error
        assert self._content is not None
        return Generation(content=self._content)


@pytest.fixture
def fake_generator(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Thay _generator; trả về dict để test chỉnh nội dung/lỗi trước khi chạy."""
    state: dict[str, Any] = {"content": OUT_OF_SCOPE, "error": None, "models": []}

    def factory(model: str, host: str) -> FixedGenerator:
        state["models"].append((model, host))
        return FixedGenerator(content=state["content"], error=state["error"])

    monkeypatch.setattr(qu_cli, "_generator", factory)
    return state


def test_understanding_commands_are_registered_on_top_level_parser() -> None:
    parser = top_cli._build_parser()
    parsed = parser.parse_args(["parse", "đi Huế"])
    assert parsed.func is qu_cli._cmd_parse
    parsed = parser.parse_args(["qu-eval", "--model", "m", "--out", "r.json"])
    assert parsed.func is qu_cli._cmd_qu_eval
    assert parsed.split.value == "dev"
    assert parsed.allow_test is False


@requires_inputs
def test_parse_prints_parsed_query_json(
    fake_generator: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    fake_generator["content"] = json.dumps(
        {
            "intent": "plan_new",
            "date_text": "20/12",
            "duration_text": "2 ngày",
            "travel_mode": "car",
            "pace": None,
            "day_start": None,
            "day_end": None,
            "interest_phrases": ["chùa"],
            "must_include_mentions": ["chùa Thiên Mụ"],
            "exclude_mentions": [],
            "exclude_category_phrases": [],
            "soft_preferences": [],
            "city": None,
        },
        ensure_ascii=False,
    )
    code = top_cli.main(
        [
            "parse",
            "đi Huế 2 ngày 20/12 bằng ô tô",
            "--model",
            "m",
            "--ref",
            "2026-11-18",
            "--db",
            str(HUE_DB),
        ]
    )
    out = capsys.readouterr().out
    assert code == qu_cli.EXIT_OK
    data = json.loads(out)
    assert data["intent"] == "plan_new"
    assert data["request"]["start_date"] == "2026-12-20"
    assert data["request"]["num_days"] == 2
    assert data["request"]["travel_mode"] == "car"
    assert data["must_include"][0]["place_id"] == "huetripo:197559"
    assert fake_generator["models"] == [("m", "http://127.0.0.1:11434")]


@requires_inputs
def test_parse_returns_extraction_exit_code_on_bad_json(
    fake_generator: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    fake_generator["content"] = "không phải json"
    code = top_cli.main(["parse", "đi Huế", "--model", "m", "--db", str(HUE_DB)])
    assert code == qu_cli.EXIT_EXTRACTION
    assert "sai schema" in capsys.readouterr().err


@requires_inputs
def test_parse_returns_generation_exit_code_on_infra_error(
    fake_generator: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    fake_generator["error"] = GenerationError("Ollama chưa chạy")
    code = top_cli.main(["parse", "đi Huế", "--model", "m", "--db", str(HUE_DB)])
    assert code == qu_cli.EXIT_GENERATION
    assert "Ollama chưa chạy" in capsys.readouterr().err


def test_parse_without_db_is_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = top_cli.main(
        ["parse", "đi Huế", "--model", "m", "--db", str(tmp_path / "missing.sqlite")]
    )
    assert code == qu_cli.EXIT_USAGE
    assert "Không tìm thấy" in capsys.readouterr().err


@requires_inputs
def test_qu_eval_test_split_needs_allow_flag(
    fake_generator: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = top_cli.main(
        [
            "qu-eval",
            "--model",
            "m",
            "--split",
            "test",
            "--out",
            str(tmp_path / "r.json"),
            "--db",
            str(HUE_DB),
            "--evalset",
            str(EVAL_FILE),
        ]
    )
    assert code == qu_cli.EXIT_USAGE
    assert "--allow-test" in capsys.readouterr().err
    assert not (tmp_path / "r.json").exists()


@requires_inputs
def test_qu_eval_writes_summary_and_items(
    fake_generator: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "reports" / "qu.json"
    code = top_cli.main(
        [
            "qu-eval",
            "--model",
            "m",
            "--split",
            "dev",
            "--limit",
            "3",
            "--out",
            str(out),
            "--db",
            str(HUE_DB),
            "--evalset",
            str(EVAL_FILE),
        ]
    )
    assert code == qu_cli.EXIT_OK
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["meta"]["split"] == "dev"
    assert report["meta"]["num_predict"] == 512
    assert report["meta"]["num_ctx"] == 4096
    assert report["meta"]["temperature"] == 0.0
    assert report["meta"]["seed"] == 0
    assert report["meta"]["limit"] == 3
    assert len(report["items"]) == 3
    assert report["summary"]["n"] == 3
    assert {"pred", "score", "latency_s", "gold", "text"} <= set(report["items"][0])
    assert "dev: 3 mục" in capsys.readouterr().out


@requires_inputs
def test_qu_eval_records_extraction_errors_and_still_exits_ok(
    fake_generator: dict[str, Any], tmp_path: Path
) -> None:
    fake_generator["content"] = "không phải json"
    out = tmp_path / "qu.json"
    code = top_cli.main(
        [
            "qu-eval",
            "--model",
            "m",
            "--limit",
            "2",
            "--out",
            str(out),
            "--db",
            str(HUE_DB),
            "--evalset",
            str(EVAL_FILE),
        ]
    )
    assert code == qu_cli.EXIT_OK
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["summary"]["errors"] == 2
    assert all(item["pred"] is None for item in report["items"])


@requires_inputs
def test_qu_eval_generation_error_is_exit_5(
    fake_generator: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_generator["error"] = GenerationError("Ollama chết")
    code = top_cli.main(
        [
            "qu-eval",
            "--model",
            "m",
            "--limit",
            "1",
            "--out",
            str(tmp_path / "q.json"),
            "--db",
            str(HUE_DB),
            "--evalset",
            str(EVAL_FILE),
        ]
    )
    assert code == qu_cli.EXIT_GENERATION
    assert not (tmp_path / "q.json").exists()


def test_qu_eval_rejects_non_positive_limit(tmp_path: Path) -> None:
    code = top_cli.main(
        [
            "qu-eval",
            "--model",
            "m",
            "--limit",
            "0",
            "--out",
            str(tmp_path / "q.json"),
            "--db",
            str(tmp_path / "no-db.sqlite"),
            "--evalset",
            str(EVAL_FILE),
        ]
    )
    assert code == qu_cli.EXIT_USAGE
