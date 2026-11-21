"""Must-include and exclude constraints on real Hue data: search, itinerary, meals and budget."""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pydantic
import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
HUE_DB = BACKEND / "data" / "hue.sqlite"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.search import SearchAgent  # noqa: E402
from app.providers.hotel_mock import MockHotelProvider  # noqa: E402
from app.providers.transport_mock import MockTransportProvider  # noqa: E402
from app.repositories.hue_places import HuePlacesRepository  # noqa: E402
from app.schemas.itinerary import ItineraryResult  # noqa: E402
from app.schemas.request import TripRequest  # noqa: E402
from app.services.budget_optimizer import BudgetAgent  # noqa: E402
from app.services.constraints import (  # noqa: E402
    ConstraintConflictError,
    UnknownPoiError,
    check_constraints,
)
from app.services.itinerary_optimizer import ItineraryAgent  # noqa: E402

GIA_LONG = "huetripo:689381"  # Lăng vua Gia Long, about 12 km from the centre
CHO_DONG_BA = "huetripo:759007"  # Chợ Đông Ba, category market, a landmark id
THIEN_MU = "huetripo:197559"  # Chùa Thiên Mụ, a landmark id


def _request(**overrides: Any) -> TripRequest:
    payload: dict[str, Any] = {
        "origin": "Hà Nội",
        "destination": "Huế",
        "start_date": date(2026, 12, 5),
        "end_date": date(2026, 12, 7),
        "people": 2,
        "rooms": 1,
        "budget_vnd": 6_000_000,
        "preferences": ["di tích", "đặc sản"],
    }
    payload.update(overrides)
    return TripRequest(**payload)


def _repository() -> HuePlacesRepository:
    return HuePlacesRepository(HUE_DB)


def _search(request: TripRequest):
    agent = SearchAgent(_repository(), MockTransportProvider(), MockHotelProvider())
    return asyncio.run(agent.search(request))


def _itinerary(request: TripRequest) -> ItineraryResult:
    repository = _repository()
    search = _search(request)
    return ItineraryAgent(places=repository).plan(request, search)


def _events(itinerary: ItineraryResult) -> list:
    return [event for day in itinerary.days for event in day.events]


def _candidate_ids(request: TripRequest) -> set[str]:
    return {item.place.id for item in _search(request).poi_candidates}


def test_baseline_plan_contains_the_three_ids_the_constraints_will_remove() -> None:
    """Guards the meaning of the tests below: without constraints these places are chosen."""
    request = _request()
    scheduled = {event.poi_id for event in _events(_itinerary(request))}

    assert CHO_DONG_BA in scheduled
    assert THIEN_MU in scheduled


def test_must_include_gia_long_is_visited_even_though_it_is_outside_the_default_fillers() -> None:
    request = _request(must_include_poi_ids=[GIA_LONG])

    itinerary = _itinerary(request)

    visits = [event for event in _events(itinerary) if event.kind == "VISIT"]
    assert GIA_LONG in {event.poi_id for event in visits}
    assert GIA_LONG not in itinerary.unplanned_poi_ids
    assert GIA_LONG not in itinerary.excluded_poi_ids


def test_must_include_is_planned_on_the_first_day_as_the_top_priority_seed() -> None:
    request = _request(must_include_poi_ids=[GIA_LONG])

    itinerary = _itinerary(request)

    first_day_visits = {event.poi_id for event in itinerary.days[0].events if event.kind == "VISIT"}
    assert GIA_LONG in first_day_visits


def test_excluded_category_market_removes_cho_dong_ba_from_search_and_itinerary() -> None:
    request = _request(exclude_categories=["market"])

    assert CHO_DONG_BA not in _candidate_ids(request)
    assert CHO_DONG_BA not in {event.poi_id for event in _events(_itinerary(request))}


def test_excluded_poi_id_removes_thien_mu_from_search_and_itinerary() -> None:
    request = _request(exclude_poi_ids=[THIEN_MU])

    assert THIEN_MU not in _candidate_ids(request)
    assert THIEN_MU not in {event.poi_id for event in _events(_itinerary(request))}


def test_excluded_restaurant_category_never_appears_as_a_meal() -> None:
    request = _request(exclude_categories=["restaurant"])

    events = _events(_itinerary(request))

    assert all(event.category != "restaurant" for event in events if event.poi_id)
    assert any(event.kind == "MEAL_BREAK" for event in events)


def test_excluded_cafe_category_never_appears_as_a_cafe_break() -> None:
    request = _request(exclude_categories=["cafe"])

    events = _events(_itinerary(request))

    assert all(event.category != "cafe" for event in events if event.poi_id)
    assert not [event for event in events if event.meal == "CAFE"]


def test_budget_does_not_price_remaining_meals_of_an_excluded_category() -> None:
    request = _request(exclude_categories=["restaurant"])
    repository = _repository()
    search = _search(request)
    itinerary = ItineraryAgent(places=repository).plan(request, search)

    budget = BudgetAgent(places=repository).build(request, search, visit_poi_ids=itinerary.poi_ids())

    codes = {item.code for option in budget.options for item in option.items}
    assert "food_restaurant_other" not in codes


def test_exclusions_are_applied_to_the_whole_plan_not_only_the_first_day() -> None:
    request = _request(exclude_poi_ids=[THIEN_MU], exclude_categories=["market"])

    itinerary = _itinerary(request)

    ids = {event.poi_id for event in _events(itinerary)}
    assert THIEN_MU not in ids
    assert CHO_DONG_BA not in ids


def test_unknown_must_include_id_is_refused_by_the_constraint_check() -> None:
    request = _request(must_include_poi_ids=["huetripo:does-not-exist"])

    with pytest.raises(UnknownPoiError):
        check_constraints(request, _repository())


def test_unknown_must_include_id_is_refused_by_the_itinerary_too() -> None:
    request = _request(must_include_poi_ids=["huetripo:does-not-exist"])

    with pytest.raises(UnknownPoiError):
        _itinerary(request)


def test_must_include_in_an_excluded_category_is_a_conflict() -> None:
    request = _request(must_include_poi_ids=[CHO_DONG_BA], exclude_categories=["market"])

    with pytest.raises(ConstraintConflictError):
        check_constraints(request, _repository())


def test_a_poi_cannot_be_both_must_include_and_excluded() -> None:
    with pytest.raises(pydantic.ValidationError):
        _request(must_include_poi_ids=[GIA_LONG], exclude_poi_ids=[GIA_LONG])


def test_constraint_fields_default_to_empty_lists() -> None:
    request = _request()

    assert request.must_include_poi_ids == []
    assert request.exclude_poi_ids == []
    assert request.exclude_categories == []


def test_api_refuses_an_unknown_must_include_id_with_422() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    body = {
        "origin": "Hà Nội",
        "destination": "Huế",
        "start_date": "2026-12-05",
        "end_date": "2026-12-07",
        "people": 2,
        "must_include_poi_ids": ["huetripo:does-not-exist"],
    }
    with TestClient(app) as client:
        response = client.post("/api/v1/plans/constraints-422-unknown", json=body)

    assert response.status_code == 422
    assert "does-not-exist" in response.text


def test_api_plans_a_must_include_gia_long_and_respects_the_exclusions() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    body = {
        "origin": "Hà Nội",
        "destination": "Huế",
        "start_date": "2026-12-05",
        "end_date": "2026-12-07",
        "people": 2,
        "budget_vnd": 6_000_000,
        "preferences": ["di tích", "đặc sản"],
        "must_include_poi_ids": [GIA_LONG],
        "exclude_poi_ids": [THIEN_MU],
        "exclude_categories": ["market"],
    }
    with TestClient(app) as client:
        response = client.post("/api/v1/plans/constraints-api-ok", json=body, headers={"X-User-Id": "alice"})

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace[-1] == "approval"
