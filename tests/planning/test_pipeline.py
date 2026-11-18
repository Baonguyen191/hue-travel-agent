"""Vòng lặp lập lịch: sinh, xếp giờ, kiểm, sửa. Generator là bản giả trả output có sẵn."""

import json
from typing import Any

import pytest

from tests.planning.factories import make_place, make_request
from tests.validation.factories import FixedTravelTime
from travel_agent.data.place_repository import InMemoryPlaceRepository
from travel_agent.domain.models import Category, PlanRequest
from travel_agent.planning.candidates import select_candidates
from travel_agent.planning.pipeline import PlanResult, plan_trip
from travel_agent.planning.prompt import (
    REPAIR_ISSUES_HEADER,
    REPAIR_PLAN_HEADER,
    build_messages,
    format_issue,
)
from travel_agent.planning.schedule import retime
from travel_agent.training.generator import Generation
from travel_agent.training.parsing import parse_itinerary
from travel_agent.training.requests import EvalEntry, Split, request_key
from travel_agent.training.runner import candidate_seed, run_eval
from travel_agent.validation.validator import validate_itinerary

TRAVEL = FixedTravelTime(minutes=10.0)
REQUEST: PlanRequest = make_request()  # 1 ngày, 2026-12-01, moderate, khung 08:00-21:00
PLACES = [
    make_place("t:museum", Category.MUSEUM),
    make_place("t:cafe", Category.CAFE),
    make_place("t:lunch", Category.RESTAURANT),
    make_place("t:dinner", Category.RESTAURANT),
]


def _itinerary_json(stops: list[tuple[str, str, str]], date: str = "2026-12-01") -> str:
    days = [
        {
            "date": date,
            "stops": [{"place_id": pid, "arrive": a, "depart": d} for pid, a, d in stops],
        }
    ]
    return json.dumps({"days": days})


VALID_RAW = _itinerary_json(
    [("t:museum", "08:30", "10:30"), ("t:lunch", "11:30", "12:30"), ("t:dinner", "18:00", "19:00")]
)
# Cà phê ngay sau bảo tàng, không có thời gian đi: lỗi travel_time_insufficient.
TIGHT_RAW = _itinerary_json(
    [
        ("t:museum", "08:30", "10:30"),
        ("t:cafe", "10:30", "11:00"),
        ("t:lunch", "11:30", "12:30"),
        ("t:dinner", "18:00", "19:00"),
    ]
)
UNKNOWN_RAW = _itinerary_json(
    [("t:museum", "08:30", "10:30"), ("x:404", "11:30", "12:30"), ("t:dinner", "18:00", "19:00")]
)
TWO_DAYS_UNKNOWN_RAW = json.dumps(
    {
        "days": [
            {
                "date": "2026-12-01",
                "stops": [{"place_id": "x:404", "arrive": "09:00", "depart": "10:00"}],
            },
            {
                "date": "2026-12-02",
                "stops": [{"place_id": "x:405", "arrive": "09:00", "depart": "10:00"}],
            },
        ]
    }
)
NOT_JSON = "không phải json"


class ScriptedGenerator:
    """Trả lần lượt các output đã cho; gọi quá số lượt thì báo lỗi rõ ràng."""

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.seen: list[list[dict[str, str]]] = []
        self.schemas: list[dict[str, Any] | None] = []

    def generate(
        self, messages: list[dict[str, str]], format_schema: dict[str, Any] | None = None
    ) -> Generation:
        self.seen.append(messages)
        self.schemas.append(format_schema)
        if len(self.seen) > len(self.outputs):
            raise AssertionError("generator bị gọi nhiều lần hơn kịch bản")
        return Generation(content=self.outputs[len(self.seen) - 1], done_reason="stop")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1.5
        return self.now


def _plan(generator: ScriptedGenerator, **kwargs: Any) -> PlanResult:
    return plan_trip(REQUEST, PLACES, generator, TRAVEL, clock=FakeClock(), **kwargs)


def _user(messages: list[dict[str, str]]) -> str:
    return messages[1]["content"]


def test_valid_first_output_takes_one_call() -> None:
    generator = ScriptedGenerator([VALID_RAW])
    result = _plan(generator)
    assert result.valid is True
    assert len(generator.seen) == 1
    assert [attempt.kind for attempt in result.attempts] == ["generate"]
    assert result.attempts[0].parsed is True
    assert result.attempts[0].error_count == 0
    assert result.attempts[0].latency_s == 1.5


def test_schema_is_pinned_to_the_request_day_count() -> None:
    generator = ScriptedGenerator([VALID_RAW])
    _plan(generator)
    [schema] = generator.schemas
    assert schema is not None
    assert (schema["properties"]["days"]["minItems"], schema["properties"]["days"]["maxItems"]) == (
        1,
        1,
    )


def test_invalid_output_is_repaired_with_broken_plan_and_issues() -> None:
    generator = ScriptedGenerator([UNKNOWN_RAW, VALID_RAW])
    result = _plan(generator)

    assert result.valid is True
    assert [attempt.kind for attempt in result.attempts] == ["generate", "repair"]
    # Prompt sửa phải đúng bằng prompt dựng từ lịch đã xếp giờ và các lỗi ERROR của lượt đầu.
    candidates = select_candidates(REQUEST, PLACES, candidate_seed(request_key(REQUEST)))
    lookup = InMemoryPlaceRepository(candidates)
    retimed = retime(REQUEST, parse_itinerary(UNKNOWN_RAW), lookup, TRAVEL).itinerary
    report = validate_itinerary(REQUEST, retimed, lookup, TRAVEL)
    expected = build_messages(REQUEST, candidates, broken=retimed, issues=report.issues)
    assert generator.seen[1] == expected
    user = _user(generator.seen[1])
    assert REPAIR_PLAN_HEADER in user
    assert REPAIR_ISSUES_HEADER in user
    assert "x:404" in user
    assert any(format_issue(issue) in user for issue in report.errors())


def test_stops_when_out_of_repairs_and_reports_invalid() -> None:
    generator = ScriptedGenerator([UNKNOWN_RAW, UNKNOWN_RAW, UNKNOWN_RAW])
    result = _plan(generator, max_repairs=2)
    assert result.valid is False
    assert len(generator.seen) == 3
    assert [attempt.kind for attempt in result.attempts] == ["generate", "repair", "repair"]
    assert result.itinerary is not None
    assert result.report is not None and not result.report.is_valid


def test_no_repairs_when_max_repairs_is_zero() -> None:
    generator = ScriptedGenerator([UNKNOWN_RAW])
    result = _plan(generator, max_repairs=0)
    assert len(generator.seen) == 1
    assert result.valid is False


def test_negative_max_repairs_is_rejected() -> None:
    with pytest.raises(ValueError):
        _plan(ScriptedGenerator([VALID_RAW]), max_repairs=-1)


def test_stops_as_soon_as_repair_is_valid() -> None:
    generator = ScriptedGenerator([UNKNOWN_RAW, VALID_RAW, UNKNOWN_RAW])
    result = _plan(generator, max_repairs=2)
    assert result.valid is True
    assert len(generator.seen) == 2


def test_unparseable_output_is_regenerated_from_scratch() -> None:
    generator = ScriptedGenerator([NOT_JSON, VALID_RAW])
    result = _plan(generator)

    assert result.valid is True
    assert [attempt.kind for attempt in result.attempts] == ["generate", "generate"]
    assert result.attempts[0].parsed is False
    assert result.attempts[0].error_count == 0
    fresh = build_messages(
        REQUEST, select_candidates(REQUEST, PLACES, candidate_seed(request_key(REQUEST)))
    )
    assert generator.seen[1] == fresh
    assert REPAIR_PLAN_HEADER not in _user(generator.seen[1])


def test_retime_fixes_tight_timing_without_a_repair_call() -> None:
    generator = ScriptedGenerator([TIGHT_RAW])
    result = _plan(generator, retime=True)
    assert result.valid is True
    assert len(generator.seen) == 1


def test_without_retime_the_tight_timing_needs_a_repair() -> None:
    generator = ScriptedGenerator([TIGHT_RAW, VALID_RAW])
    result = _plan(generator, retime=False)
    assert [attempt.kind for attempt in result.attempts] == ["generate", "repair"]
    assert result.attempts[0].error_count >= 1


def test_best_attempt_is_returned_when_none_is_valid() -> None:
    # Lượt đầu có một lỗi, lượt sửa có hai lỗi, lượt cuối không parse được.
    generator = ScriptedGenerator([UNKNOWN_RAW, TWO_DAYS_UNKNOWN_RAW, NOT_JSON])
    result = _plan(generator, max_repairs=2)
    parsed_counts = [attempt.error_count for attempt in result.attempts if attempt.parsed]
    assert result.valid is False
    assert result.report is not None
    assert len(result.report.errors()) == min(parsed_counts)
    assert result.attempts[0].error_count == min(parsed_counts)


def test_valid_plan_drops_nothing() -> None:
    generator = ScriptedGenerator([VALID_RAW])
    result = _plan(generator)
    assert result.dropped == []
    assert result.candidates_ids == [
        place.id
        for place in select_candidates(REQUEST, PLACES, candidate_seed(request_key(REQUEST)))
    ]


def test_candidates_and_messages_match_eval_for_the_same_request() -> None:
    plan_generator = ScriptedGenerator([VALID_RAW])
    result = _plan(plan_generator)

    eval_generator = ScriptedGenerator([VALID_RAW])
    entry = EvalEntry(key=request_key(REQUEST), split=Split.DEV, request=REQUEST)
    run_eval([entry], PLACES, eval_generator, TRAVEL, clock=FakeClock())

    assert plan_generator.seen == eval_generator.seen
    assert plan_generator.schemas == eval_generator.schemas
    assert result.candidates_ids == [
        place.id
        for place in select_candidates(REQUEST, PLACES, candidate_seed(request_key(REQUEST)))
    ]


def test_explicit_seed_equal_to_default_gives_same_candidates() -> None:
    default_ids = _plan(ScriptedGenerator([VALID_RAW])).candidates_ids
    same = plan_trip(
        REQUEST,
        PLACES,
        ScriptedGenerator([VALID_RAW]),
        TRAVEL,
        seed=candidate_seed(request_key(REQUEST)),
        clock=FakeClock(),
    )
    assert same.candidates_ids == default_ids


def test_repair_is_not_attempted_for_warnings_only() -> None:
    # Thiếu bữa tối chỉ là WARNING: plan vẫn hợp lệ, không gọi lượt sửa.
    no_dinner = _itinerary_json(
        [
            ("t:museum", "08:30", "10:30"),
            ("t:lunch", "11:30", "12:30"),
            ("t:cafe", "14:00", "15:00"),
        ]
    )
    generator = ScriptedGenerator([no_dinner])
    result = _plan(generator)
    assert result.valid is True
    assert len(generator.seen) == 1
    assert result.report is not None and result.report.issues
    assert all(issue.severity.value == "warning" for issue in result.report.issues)
