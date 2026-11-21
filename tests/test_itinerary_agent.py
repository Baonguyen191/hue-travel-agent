"""PHASE 6 itinerary construction and validation tests."""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.search import SearchAgent  # noqa: E402
from app.providers.hotel_mock import MockHotelProvider  # noqa: E402
from app.providers.transport_mock import MockTransportProvider  # noqa: E402
from app.repositories.hue_places import HuePlacesRepository  # noqa: E402
from app.schemas.request import TripRequest  # noqa: E402
from app.services.itinerary_optimizer import ItineraryAgent, parse_simple_opening_window  # noqa: E402
from app.services.itinerary_validator import validate_itinerary  # noqa: E402


def _request() -> TripRequest:
    return TripRequest(
        origin="Đà Nẵng", destination="Huế", start_date=date(2026, 12, 10), end_date=date(2026, 12, 12), people=2
    )


def _search():
    return asyncio.run(SearchAgent(
        HuePlacesRepository(BACKEND / "data" / "hue.sqlite"), MockTransportProvider(), MockHotelProvider()
    ).search(_request()))


def test_itinerary_uses_real_poi_ids_without_overlapping_events() -> None:
    search = _search()
    result = ItineraryAgent().plan(_request(), search)
    events = [event for day in result.days for event in day.events]
    visits = [event for event in events if event.kind == "VISIT"]
    source_ids = {candidate.place.id for candidate in search.poi_candidates}

    assert len(result.days) == 3  # 3 calendar days, 2 hotel nights
    assert visits
    assert {visit.poi_id for visit in visits}.issubset(source_ids)
    assert len({visit.poi_id for visit in visits}) == len(visits)
    assert result.validation.valid
    assert all(visit.travel_minutes_estimated is not None for visit in visits)
    assert all("Opening hours require verification" in visit.warnings[0] for visit in visits)


def test_validator_detects_a_duplicate_poi() -> None:
    result = ItineraryAgent().plan(_request(), _search())
    first_visit = next(event for event in result.days[0].events if event.kind == "VISIT")
    duplicated_day = result.days[1].model_copy(update={"events": [first_visit]})

    validation = validate_itinerary([result.days[0], duplicated_day])

    assert not validation.valid
    assert any("more than once" in warning for warning in validation.warnings)


def test_opening_window_parser_only_accepts_unambiguous_same_day_ranges() -> None:
    assert parse_simple_opening_window("07:30-17:30") is not None
    assert parse_simple_opening_window("mở 16:00") is None
    assert parse_simple_opening_window("22:00-02:00") is None
