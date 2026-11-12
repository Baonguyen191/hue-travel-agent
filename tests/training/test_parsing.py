from tests.training.factories import VALID_RAW
from travel_agent.training.parsing import parse_itinerary


def test_parses_valid_json() -> None:
    itinerary = parse_itinerary(VALID_RAW)
    assert itinerary is not None
    assert [stop.place_id for stop in itinerary.days[0].stops] == [
        "t:museum",
        "t:lunch",
        "t:dinner",
    ]


def test_surrounding_whitespace_is_allowed() -> None:
    assert parse_itinerary(f"\n  {VALID_RAW}\n") is not None


def test_not_json_returns_none() -> None:
    assert parse_itinerary("Đây là lịch trình của bạn") is None


def test_code_fence_is_not_repaired() -> None:
    assert parse_itinerary(f"```json\n{VALID_RAW}\n```") is None


def test_wrong_schema_returns_none() -> None:
    assert parse_itinerary('{"days": []}') is None
    assert parse_itinerary('{"plan": "x"}') is None


def test_timezone_aware_time_returns_none() -> None:
    for suffix in ("Z", "+07:00"):
        raw = VALID_RAW.replace('"08:30"', f'"08:30:00{suffix}"')
        assert raw != VALID_RAW
        assert parse_itinerary(raw) is None
