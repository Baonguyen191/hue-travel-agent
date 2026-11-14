import datetime as dt
import json
import os
import unicodedata
from pathlib import Path

import pytest

from tests.planning.factories import make_place, make_request
from travel_agent.data.place_repository import InMemoryPlaceRepository
from travel_agent.domain.models import Category, Itinerary, PlannedDay, PlannedStop, TravelMode
from travel_agent.planning.prompt import (
    SYSTEM_PROMPT,
    build_messages,
    format_candidate,
    format_issue,
    format_itinerary,
)
from travel_agent.routing.travel_time import HaversineEstimator
from travel_agent.training.parsing import parse_itinerary
from travel_agent.validation.report import Issue, IssueCode, Severity
from travel_agent.validation.validator import validate_itinerary

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


REPAIR_SNAPSHOT = Path(__file__).parent / "snapshots" / "repair_messages.json"
BROKEN = Itinerary(
    days=[
        PlannedDay(
            date=REQUEST.start_date,
            stops=[
                PlannedStop(place_id="t:a", arrive=dt.time(16, 0), depart=dt.time(17, 30)),
                PlannedStop(place_id="t:x", arrive=dt.time(18, 0), depart=dt.time(19, 0)),
                PlannedStop(place_id="t:b", arrive=dt.time(19, 15), depart=dt.time(20, 0)),
            ],
        )
    ]
)


def broken_issues() -> list[Issue]:
    report = validate_itinerary(
        REQUEST, BROKEN, InMemoryPlaceRepository(CANDIDATES), HaversineEstimator()
    )
    return report.issues


def test_format_itinerary_matches_the_system_prompt_example() -> None:
    text = format_itinerary(BROKEN)
    assert text.startswith(
        '{"days":[{"date":"2026-12-01","stops":[{"place_id":"t:a","arrive":"16:00",'
        '"depart":"17:30","note":null},'
    )
    assert parse_itinerary(text) == BROKEN


def test_repair_prompt_extends_the_generation_prompt() -> None:
    generation = build_messages(REQUEST, CANDIDATES)
    repair = build_messages(REQUEST, CANDIDATES, broken=BROKEN, issues=broken_issues())
    assert repair[0] == generation[0]
    assert repair[1]["content"].startswith(generation[1]["content"] + "\n\n")
    assert format_itinerary(BROKEN) in repair[1]["content"]


def test_repair_prompt_lists_only_errors_with_position_and_message() -> None:
    issues = broken_issues()
    content = build_messages(REQUEST, CANDIDATES, broken=BROKEN, issues=issues)[1]["content"]
    errors = [issue for issue in issues if issue.severity is Severity.ERROR]
    warnings = [issue for issue in issues if issue.severity is Severity.WARNING]
    assert errors and warnings
    for issue in errors:
        assert format_issue(issue) in content
    for issue in warnings:
        assert issue.message not in content
    unknown = next(issue for issue in errors if issue.code is IssueCode.UNKNOWN_PLACE)
    assert format_issue(unknown) == f"- unknown_place (ngày 1, điểm 2, t:x): {unknown.message}"


def test_repair_prompt_needs_a_broken_plan_and_an_error() -> None:
    warning_only = [issue for issue in broken_issues() if issue.severity is Severity.WARNING]
    with pytest.raises(ValueError):
        build_messages(REQUEST, CANDIDATES, broken=BROKEN, issues=warning_only)
    with pytest.raises(ValueError):
        build_messages(REQUEST, CANDIDATES, issues=broken_issues())


def test_repair_messages_match_snapshot() -> None:
    """Snapshot riêng cho prompt repair; snapshot sinh plan ở trên giữ nguyên."""
    messages = build_messages(REQUEST, CANDIDATES, broken=BROKEN, issues=broken_issues())
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        REPAIR_SNAPSHOT.write_text(
            json.dumps(messages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    assert messages == json.loads(REPAIR_SNAPSHOT.read_text(encoding="utf-8"))


def test_candidate_names_are_nfc_normalised() -> None:
    decomposed = unicodedata.normalize("NFD", "Chùa Bảo Lâm")
    assert decomposed != "Chùa Bảo Lâm"
    place = make_place("t:nfd", Category.RELIGIOUS, name=decomposed)
    row = format_candidate(place)
    assert "t:nfd | Chùa Bảo Lâm | religious" in row
    assert unicodedata.is_normalized("NFC", row)


def test_issue_messages_are_nfc_normalised() -> None:
    message = unicodedata.normalize("NFD", "Chùa Bảo Lâm không mở cửa")
    issue = Issue(code=IssueCode.CLOSED_DURING_VISIT, severity=Severity.ERROR, message=message)
    assert format_issue(issue) == "- closed_during_visit: Chùa Bảo Lâm không mở cửa"
