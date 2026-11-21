"""PHASE 6 itinerary construction and validation tests."""

from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.search import SearchAgent  # noqa: E402
from app.providers.hotel_mock import MockHotelProvider  # noqa: E402
from app.providers.transport_mock import MockTransportProvider  # noqa: E402
from app.repositories.hue_places import HuePlacesRepository  # noqa: E402
from app.schemas.request import TripRequest  # noqa: E402
from app.services.itinerary_optimizer import (  # noqa: E402
    ItineraryAgent,
    ItineraryConfig,
    parse_simple_opening_window,
)
from app.services.poi_search import haversine_km  # noqa: E402
from app.schemas.itinerary import (  # noqa: E402
    ItineraryDay,
    ItineraryEvent,
    ItineraryResult,
    ItineraryValidation,
)
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


def test_each_day_has_exactly_one_lunch() -> None:
    # _search() uses the Search Agent default mix (no categories, keyword or preferences).
    result = ItineraryAgent().plan(_request(), _search())

    for day in result.days:
        lunches = [
            event for event in day.events
            if event.kind == "MEAL_BREAK" or (event.kind == "MEAL" and event.meal == "LUNCH")
        ]
        assert len(lunches) == 1, f"{day.date} has {len(lunches)} lunches"


def _at(hour: int, minute: int = 0, day: int = 5) -> datetime:
    return datetime(2026, 12, day, hour, minute)


def _day(events: list[ItineraryEvent], day: int = 5) -> ItineraryDay:
    return ItineraryDay(date=date(2026, 12, day), events=events)


def _visit(poi_id: str, category: str, hour: int, day: int = 5) -> ItineraryEvent:
    return ItineraryEvent(
        kind="VISIT", poi_id=poi_id, name=f"Visit {poi_id}", category=category,
        start_at=_at(hour, day=day), end_at=_at(hour + 1, day=day),
    )


def _meal(poi_id: str, meal: str, hour: int, day: int = 5) -> ItineraryEvent:
    return ItineraryEvent(
        kind="MEAL", poi_id=poi_id, meal=meal, name=f"Meal {poi_id}", category="restaurant",
        start_at=_at(hour, day=day), end_at=_at(hour + 1, day=day),
    )


def test_meal_event_needs_a_poi_id_and_keeps_its_meal_kind() -> None:
    with pytest.raises(ValidationError):
        ItineraryEvent(kind="MEAL", meal="LUNCH", name="Lunch", start_at=_at(11), end_at=_at(12))

    assert _meal("huetripo:1", "LUNCH", 11).meal == "LUNCH"


def test_result_poi_ids_are_visit_and_meal_ids_in_order_without_duplicates() -> None:
    days = [
        _day([_visit("huetripo:A", "historic", 9), _meal("huetripo:B", "LUNCH", 12)]),
        _day([_visit("huetripo:C", "religious", 9, day=6), _meal("huetripo:B", "DINNER", 18, day=6)], day=6),
    ]
    result = ItineraryResult(
        days=days,
        unplanned_poi_ids=[],
        warnings=[],
        validation=ItineraryValidation(valid=True, warnings=[]),
    )

    assert result.excluded_poi_ids == []
    assert result.merged_poi_ids == []
    assert result.poi_ids() == ["huetripo:A", "huetripo:B", "huetripo:C"]


def test_validator_flags_a_food_venue_scheduled_as_a_visit() -> None:
    validation = validate_itinerary(
        [_day([_visit("huetripo:R", "restaurant", 9), _meal("huetripo:L", "LUNCH", 12)])]
    )

    assert not validation.valid
    assert any("scheduled as a visit" in warning for warning in validation.warnings)


def test_validator_flags_a_day_with_visits_but_no_lunch() -> None:
    validation = validate_itinerary(
        [_day([_visit("huetripo:A", "historic", 9), _meal("huetripo:D", "DINNER", 18)])]
    )

    assert not validation.valid
    assert any("no lunch" in warning for warning in validation.warnings)


def test_validator_accepts_a_named_lunch_or_an_anonymous_meal_break() -> None:
    named = _day([_visit("huetripo:A", "historic", 9), _meal("huetripo:L", "LUNCH", 12)])
    anonymous = _day([
        _visit("huetripo:A", "historic", 9),
        ItineraryEvent(kind="MEAL_BREAK", name="Meal break", start_at=_at(12), end_at=_at(13)),
    ])

    assert validate_itinerary([named]).valid
    assert validate_itinerary([anonymous]).valid


def test_validator_flags_a_restaurant_used_for_two_meals_across_the_trip() -> None:
    validation = validate_itinerary([
        _day([_meal("huetripo:L", "LUNCH", 12)]),
        _day([_meal("huetripo:L", "LUNCH", 12, day=6)], day=6),
    ])

    assert not validation.valid
    assert any("more than once" in warning for warning in validation.warnings)


def _repo() -> HuePlacesRepository:
    return HuePlacesRepository(BACKEND / "data" / "hue.sqlite")


def _dod_request() -> TripRequest:
    return TripRequest(
        origin="Hà Nội", destination="Huế", start_date=date(2026, 12, 5), end_date=date(2026, 12, 7),
        people=2, rooms=1, budget_vnd=6_000_000, preferences=["di tích", "đặc sản"],
    )


@lru_cache(maxsize=1)
def _dod_plan() -> ItineraryResult:
    """Repository-backed plan for the DoD request (Hà Nội -> Huế, di tích + đặc sản)."""
    request = _dod_request()
    search = asyncio.run(SearchAgent(_repo(), MockTransportProvider(), MockHotelProvider()).search(request))
    return ItineraryAgent(places=_repo()).plan(request, search)


def _dod_visits() -> list[ItineraryEvent]:
    return [event for day in _dod_plan().days for event in day.events if event.kind == "VISIT"]


def test_dod_no_visit_is_a_restaurant_or_cafe() -> None:
    assert _dod_visits()
    assert all(visit.category not in {"restaurant", "cafe"} for visit in _dod_visits())


def test_dod_every_day_has_one_named_lunch_and_one_named_dinner_from_real_pois() -> None:
    repo = _repo()
    for day in _dod_plan().days:
        meals = [event for event in day.events if event.kind == "MEAL"]
        lunches = [event for event in meals if event.meal == "LUNCH"]
        dinners = [event for event in meals if event.meal == "DINNER"]

        assert len(lunches) == 1, day.date
        assert len(dinners) == 1, day.date
        for meal in meals:
            assert repo.get_by_id(meal.poi_id) is not None
        for meal in lunches + dinners:
            assert meal.category == "restaurant"


def test_dod_schedules_dai_noi_hue() -> None:
    assert "huetripo:531787" in [visit.poi_id for visit in _dod_visits()]


def test_dod_visits_are_within_15_km_and_hai_van_quan_is_excluded() -> None:
    config = ItineraryConfig()
    for visit in _dod_visits():
        distance = haversine_km(config.center_lat, config.center_lon, visit.lat, visit.lon)
        assert distance <= config.max_distance_km, visit.name

    plan = _dod_plan()
    assert "huetripo:657208" in plan.excluded_poi_ids
    assert any("farther than 15 km" in warning for warning in plan.warnings)


def test_dod_no_restaurant_or_cafe_is_used_twice_across_the_trip() -> None:
    meal_ids = [event.poi_id for day in _dod_plan().days for event in day.events if event.kind == "MEAL"]

    assert len(meal_ids) == len(set(meal_ids))


def test_dod_plan_is_valid_and_every_visit_ends_by_sightseeing_end() -> None:
    plan = _dod_plan()

    assert plan.validation.valid, plan.validation.warnings
    assert all(visit.end_at.time() <= time(17, 30) for visit in _dod_visits())


def test_cau_truong_tien_duration_is_clamped_to_180_minutes_with_warning() -> None:
    from app.services.itinerary_optimizer import visit_duration_minutes

    place = _repo().get_by_id("huetripo:664215")
    minutes, warning = visit_duration_minutes(place, ItineraryConfig())

    assert place.visit_minutes == 600
    assert minutes == 180
    assert warning is not None and "600" in warning and "180" in warning


def test_missing_duration_uses_category_default_without_a_clamp_warning() -> None:
    from app.services.itinerary_optimizer import visit_duration_minutes

    place = _repo().get_by_id("huetripo:759007")  # Chợ Đông Ba: no visit minutes in source
    minutes, warning = visit_duration_minutes(place, ItineraryConfig())

    assert place.visit_minutes is None
    assert minutes == 60
    assert warning is None


def test_default_landmarks_are_real_hue_poi_ids() -> None:
    config = ItineraryConfig()
    repo = _repo()

    assert len(config.landmark_ids) == 7
    assert all(repo.get_by_id(poi_id) is not None for poi_id in config.landmark_ids)


def test_config_rejects_inverted_ranges() -> None:
    with pytest.raises(ValueError):
        ItineraryConfig(min_visit_minutes=200, max_visit_minutes=180)
    with pytest.raises(ValueError):
        ItineraryConfig(cafe_earliest=time(16, 30), cafe_latest=time(15, 0))
    with pytest.raises(ValueError):
        ItineraryConfig(day_start=time(18, 0), sightseeing_end=time(17, 0))
    with pytest.raises(ValueError):
        ItineraryConfig(min_separation_km=-0.1)
    with pytest.raises(ValueError):
        ItineraryConfig(cluster_radius_km=0)


def test_dod_no_two_visits_are_closer_than_the_minimum_separation() -> None:
    separation = ItineraryConfig().min_separation_km
    visits = _dod_visits()
    for index, first in enumerate(visits):
        for second in visits[index + 1:]:
            distance = haversine_km(first.lat, first.lon, second.lat, second.lon)
            assert distance >= separation, (first.name, second.name, distance)


def test_dod_merges_sub_sites_co_located_with_dai_noi() -> None:
    scheduled = {visit.poi_id for visit in _dod_visits()}
    plan = _dod_plan()

    assert "huetripo:531787" in scheduled
    assert "huetripo:860594" not in scheduled  # Kinh Thành Huế, 0.04 km from Đại Nội
    assert "huetripo:200310" not in scheduled  # Điện Thái Hòa, 0.06 km from Đại Nội
    assert {"huetripo:860594", "huetripo:200310"} <= set(plan.merged_poi_ids)
    assert any("sharing a location" in warning for warning in plan.warnings)


def test_dod_schedules_all_three_tombs_plus_dai_noi_and_thien_mu() -> None:
    scheduled = {visit.poi_id for visit in _dod_visits()}

    for poi_id in (
        "huetripo:531787",  # Đại Nội Huế
        "huetripo:197559",  # Chùa Thiên Mụ
        "huetripo:483480",  # Lăng vua Tự Đức
        "huetripo:627150",  # Lăng vua Khải Định
        "huetripo:424131",  # Lăng vua Minh Mạng
    ):
        assert poi_id in scheduled, poi_id


def test_no_landmark_is_reported_unfit_while_a_non_landmark_is_scheduled_that_day() -> None:
    config = ItineraryConfig()
    repo = _repo()
    landmark_names = {repo.get_by_id(poi_id).name for poi_id in config.landmark_ids}
    for day in _dod_plan().days:
        visits = [event for event in day.events if event.kind == "VISIT"]
        if not any(visit.poi_id not in config.landmark_ids for visit in visits):
            continue
        for warning in day.warnings:
            assert not any(name in warning for name in landmark_names), (day.date, warning)
