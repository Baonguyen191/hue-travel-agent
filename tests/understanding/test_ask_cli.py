"""Lệnh `travel-agent ask`: mã thoát, đầu ra chữ và JSON. Generator và DB được thay bằng bản giả.

Các fake và dữ liệu dùng chung nằm ở test_ask.py.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests.understanding.test_ask import (
    INVALID_ONE_DAY,
    PLACES,
    VALID_ONE_DAY,
    Scripted,
    extraction,
)
from travel_agent import cli as top_cli
from travel_agent.training.generator import GenerationError
from travel_agent.understanding import cli as qu_cli

ASK_BASE = ["--ref", "2026-11-19", "--plan-model", "plan:3b"]


@pytest.fixture
def ask_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Thay _generator, _plan_generator, load_usable_places, _generation_params.

    state["qu"] và state["plan"] là generator giả; state["db"] là file DB rỗng
    (chỉ để qua kiểm tra).
    """
    db = tmp_path / "hue.sqlite"
    db.write_bytes(b"")
    state: dict[str, Any] = {
        "db": db,
        "qu": Scripted(extraction()),
        "plan": Scripted(VALID_ONE_DAY),
        "qu_models": [],
        "plan_models": [],
    }

    def qu_factory(model: str, host: str) -> Scripted:
        state["qu_models"].append(model)
        return state["qu"]

    def plan_factory(model: str, host: str, generation: dict[str, Any]) -> Scripted:
        state["plan_models"].append((model, generation))
        return state["plan"]

    monkeypatch.setattr(qu_cli, "_generator", qu_factory)
    monkeypatch.setattr(qu_cli, "_plan_generator", plan_factory)
    monkeypatch.setattr(qu_cli, "load_usable_places", lambda _db: list(PLACES))
    monkeypatch.setattr(
        qu_cli,
        "_generation_params",
        lambda _path: {"temperature": 0.3, "seed": 9, "num_predict": 700, "num_ctx": 4096},
    )
    return state


def _run(env: dict[str, Any], *args: str) -> int:
    return top_cli.main(["ask", *args, "--db", str(env["db"]), *ASK_BASE])


def test_out_of_scope_exit_0_and_refusal(
    ask_env: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    ask_env["qu"] = Scripted(extraction(intent="out_of_scope"))
    assert _run(ask_env, "viết thơ") == 0
    assert "Mình chỉ lập lịch trình du lịch Huế" in capsys.readouterr().out
    assert ask_env["plan"].calls == []


def test_unsupported_exit_0(ask_env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    ask_env["qu"] = Scripted(extraction(intent="modify_plan"))
    assert _run(ask_env, "đổi giờ ăn trưa") == 0
    assert "chưa hỗ trợ" in capsys.readouterr().out


def test_clarification_exit_4(ask_env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    ask_env["qu"] = Scripted(extraction(duration_text="2 ngày"))
    assert _run(ask_env, "đi Huế 2 ngày") == 4
    out = capsys.readouterr().out
    assert "Bạn muốn đi Huế từ ngày nào?" in out
    assert ask_env["plan"].calls == []


def test_plan_valid_exit_0_human_output_uses_plan_model_and_eval_generation(
    ask_env: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    ask_env["qu"] = Scripted(extraction(date_text="20/12", duration_text="1 ngày"))
    assert _run(ask_env, "đi Huế 20/12, 1 ngày") == 0
    out = capsys.readouterr().out
    # Giờ xếp lại theo quy tắc (retime): điểm đầu ngày được đẩy về 08:00, nên chỉ kiểm định dạng.
    assert re.search(r"\d{2}:\d{2}–\d{2}:\d{2} Bảo tàng Cổ vật \(bảo tàng\)", out)
    assert "Mình giả định: đi xe máy, nhịp vừa phải, khung giờ 08:00–21:00." in out
    assert ask_env["qu_models"] == ["qwen3.5:4b"]
    model, generation = ask_env["plan_models"][0]
    assert model == "plan:3b"
    assert generation == {"temperature": 0.3, "seed": 9, "num_predict": 700, "num_ctx": 4096}


def test_plan_invalid_exit_3(ask_env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    ask_env["qu"] = Scripted(extraction(date_text="20/12", duration_text="1 ngày"))
    ask_env["plan"] = Scripted(INVALID_ONE_DAY)
    assert _run(ask_env, "đi Huế 20/12, 1 ngày", "--max-repairs", "0") == 3
    assert "Lỗi còn lại" in capsys.readouterr().out


def test_must_and_exclude_reach_candidates_and_missing_must_json(
    ask_env: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    ask_env["qu"] = Scripted(
        extraction(
            date_text="20/12",
            duration_text="1 ngày",
            must_include_mentions=["Chùa Thiên Mụ"],
            exclude_mentions=["Cà phê Ba Lần"],
        )
    )
    # Model giả không đưa chùa vào lịch: chùa nằm trong missing_must nhưng không làm lịch thành lỗi.
    assert _run(ask_env, "đi Huế 20/12, 1 ngày", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert "t:pagoda" in payload["plan"]["candidates_ids"]
    assert "t:cafe" not in payload["plan"]["candidates_ids"]
    assert payload["plan"]["missing_must"] == ["t:pagoda"]


def test_json_shape_for_plan(ask_env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    ask_env["qu"] = Scripted(extraction(date_text="20/12", duration_text="1 ngày"))
    assert _run(ask_env, "đi Huế 20/12, 1 ngày", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"outcome", "query", "plan"}
    assert payload["outcome"] == "plan"
    assert payload["query"]["intent"] == "plan_new"
    assert payload["query"]["request"]["start_date"] == "2026-12-20"
    assert set(payload["plan"]) >= {
        "itinerary",
        "report",
        "valid",
        "attempts",
        "dropped",
        "candidates_ids",
        "missing_must",
    }
    assert payload["plan"]["valid"] is True
    assert payload["plan"]["missing_must"] == []


def test_json_plan_is_null_for_refusal(
    ask_env: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    ask_env["qu"] = Scripted(extraction(intent="out_of_scope"))
    assert _run(ask_env, "viết thơ", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] == "out_of_scope"
    assert payload["plan"] is None


def test_extraction_error_exit_6(
    ask_env: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    ask_env["qu"] = Scripted("không phải json", "vẫn không phải json")
    assert _run(ask_env, "đi Huế") == 6
    assert "Không đọc được" in capsys.readouterr().err


def test_generation_error_exit_5(
    ask_env: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    ask_env["qu"] = Scripted(GenerationError("Ollama không chạy"))
    assert _run(ask_env, "đi Huế") == 5
    assert "Ollama không chạy" in capsys.readouterr().err


def test_plan_generation_error_exit_5(
    ask_env: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    ask_env["qu"] = Scripted(extraction(date_text="20/12", duration_text="1 ngày"))
    ask_env["plan"] = Scripted(GenerationError("model chưa pull"))
    assert _run(ask_env, "đi Huế 20/12, 1 ngày") == 5
    assert "model chưa pull" in capsys.readouterr().err


def test_usage_errors_exit_2(
    ask_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(qu_cli, "_rl_final_model", lambda _path: None)
    assert top_cli.main(["ask", "đi Huế", "--db", str(ask_env["db"])]) == 2
    assert "--plan-model" in capsys.readouterr().err
    assert _run(ask_env, "đi Huế", "--max-repairs", "-1") == 2
    missing_db = ["ask", "đi Huế", "--db", str(ask_env["db"]) + ".khong-co", *ASK_BASE]
    assert top_cli.main(missing_db) == 2


def test_plan_model_defaults_to_rl_yaml(
    ask_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(qu_cli, "_rl_final_model", lambda _path: "tu-rl-yaml")
    ask_env["qu"] = Scripted(extraction(intent="out_of_scope"))
    assert top_cli.main(["ask", "viết thơ", "--db", str(ask_env["db"])]) == 0
    assert ask_env["plan_models"][0][0] == "tu-rl-yaml"
    assert ask_env["plan"].calls == []
