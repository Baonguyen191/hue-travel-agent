import json
import os
from pathlib import Path

import pytest

from tests.planning.factories import make_place, make_request
from travel_agent.domain.models import Category, TravelMode
from travel_agent.planning.prompt import SYSTEM_PROMPT, build_messages
from travel_agent.routing.travel_time import HaversineEstimator

SNAPSHOT = Path(__file__).parent / "snapshots" / "generation_messages.json"

REQUEST = make_request(interests=["food", "history"])
CANDIDATES = [
    make_place("t:a", Category.MUSEUM, hours="Mo-Su 07:00-17:00", name="Bảo tàng A"),
    make_place("t:b", Category.RESTAURANT, name="Quán B"),
]

EXPECTED_USER = """YÊU CẦU
city: hue
start_date: 2026-12-01 (Tu)
num_days: 1
day_start: 08:00
day_end: 21:00
travel_mode: motorbike
pace: moderate
interests: food, history

ĐỊA ĐIỂM (place_id | tên | loại | lat,lon | giờ mở cửa)
t:a | Bảo tàng A | museum | 16.4700,107.5800 | Mo-Su 07:00-17:00
t:b | Quán B | restaurant | 16.4700,107.5800 | unknown"""


def test_two_messages_system_then_user() -> None:
    messages = build_messages(REQUEST, CANDIDATES)
    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[0]["content"] == SYSTEM_PROMPT


def test_user_message_lists_request_and_candidates() -> None:
    assert build_messages(REQUEST, CANDIDATES)[1]["content"] == EXPECTED_USER


def test_no_interests_is_stated() -> None:
    content = build_messages(make_request(), CANDIDATES)[1]["content"]
    assert "interests: không có" in content


def test_newline_in_name_does_not_break_the_row() -> None:
    place = make_place("t:c", Category.CAFE, name="Cà phê\nC")
    content = build_messages(REQUEST, [place])[1]["content"]
    assert "t:c | Cà phê C | cafe" in content


def test_pipe_in_place_name_does_not_break_the_row() -> None:
    place = make_place("t:p", Category.CAFE, name="Cà phê | Muối")
    content = build_messages(REQUEST, [place])[1]["content"]
    [row] = [line for line in content.splitlines() if line.startswith("t:p ")]
    assert row.count("|") == 4
    assert "t:p | Cà phê / Muối | cafe" in row


def test_messages_match_snapshot() -> None:
    """Đổi prompt là đổi dữ liệu train. Test này vỡ có chủ đích khi prompt đổi."""
    messages = build_messages(REQUEST, CANDIDATES)
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(
            json.dumps(messages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    assert messages == json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def _rule_5() -> str:
    [rule] = [line for line in SYSTEM_PROMPT.splitlines() if line.startswith("5. ")]
    return rule


def test_rule_5_states_the_travel_time_estimate_the_validator_uses() -> None:
    """Số trong prompt lấy từ HaversineEstimator, nên prompt và validator không lệch nhau."""
    rule = _rule_5()
    assert "ước tính" in rule
    assert f"× {HaversineEstimator.DETOUR_FACTOR:g}" in rule
    for mode in TravelMode:
        assert f"{mode.value} {HaversineEstimator.SPEED_KMH[mode]:g} km/h" in rule
        assert f"{mode.value} {HaversineEstimator.START_OVERHEAD_MIN[mode]:g} phút" in rule


def test_rule_5_tracks_estimator_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    from travel_agent.planning import prompt

    monkeypatch.setattr(HaversineEstimator, "DETOUR_FACTOR", 1.7)
    monkeypatch.setitem(HaversineEstimator.SPEED_KMH, TravelMode.CAR, 31.0)
    try:
        reloaded = importlib.reload(prompt)
        assert "× 1.7" in reloaded.SYSTEM_PROMPT
        assert "car 31 km/h" in reloaded.SYSTEM_PROMPT
    finally:
        monkeypatch.undo()
        importlib.reload(prompt)
