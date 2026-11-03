import datetime as dt

import pytest
from pydantic import ValidationError

from travel_agent.domain.models import Coordinates, Itinerary, PlanRequest


def test_coordinates_reject_out_of_range_latitude() -> None:
    with pytest.raises(ValidationError):
        Coordinates(lat=91, lon=107.58)


def test_plan_request_rejects_inverted_day_window() -> None:
    with pytest.raises(ValidationError, match="day_end must be after day_start"):
        PlanRequest(
            start_date=dt.date(2026, 11, 4),
            num_days=1,
            day_start=dt.time(18, 0),
            day_end=dt.time(8, 0),
        )


def test_plan_request_rejects_more_than_seven_days() -> None:
    with pytest.raises(ValidationError):
        PlanRequest(start_date=dt.date(2026, 11, 4), num_days=8)


def test_itinerary_parses_llm_json() -> None:
    raw = """
    {"days": [{"date": "2026-11-04",
               "stops": [{"place_id": "osm:node/1", "arrive": "08:30", "depart": "10:00",
                          "note": "Phù hợp sở thích lịch sử"}]}]}
    """
    itinerary = Itinerary.model_validate_json(raw)
    assert itinerary.days[0].stops[0].arrive == dt.time(8, 30)
    assert itinerary.days[0].date == dt.date(2026, 11, 4)


def test_itinerary_requires_at_least_one_day() -> None:
    with pytest.raises(ValidationError):
        Itinerary.model_validate({"days": []})
