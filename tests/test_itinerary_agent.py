"""PHASE 6 itinerary construction and validation tests."""

from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, time, timedelta
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
from app.schemas.place import Place  # noqa: E402
from app.schemas.request import TripRequest  # noqa: E402
from app.services.itinerary_optimizer import (  # noqa: E402
    ItineraryAgent,
    ItineraryConfig,
    _reason,
    parse_simple_opening_window,
)
from app.services.poi_search import haversine_km  # noqa: E402
from app.schemas.itinerary import (  # noqa: E402
    ItineraryDay,
    ItineraryEvent,
    ItineraryResult,
    ItineraryValidation,
    TravelLeg,
)
from app.services.itinerary_validator import validate_itinerary  # noqa: E402
from app.services.preferences import source_type  # noqa: E402


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


def test_implausible_cau_truong_tien_duration_uses_category_default_with_warning() -> None:
    from app.services.itinerary_optimizer import visit_duration_minutes

    place = _repo().get_by_id("huetripo:664215")
    minutes, warning = visit_duration_minutes(place, ItineraryConfig())

    assert place.visit_minutes == 600
    assert minutes == 60  # category default for `park`
    assert warning is not None and "600" in warning and "category default" in warning


def test_source_duration_below_minimum_is_clamped_up_to_minimum() -> None:
    from app.services.itinerary_optimizer import visit_duration_minutes

    place = _repo().get_by_id("huetripo:531787").model_copy(update={"visit_minutes": 10})
    minutes, warning = visit_duration_minutes(place, ItineraryConfig())

    assert minutes == 30
    assert warning is not None and "clamped" in warning


def test_meal_outside_radius_prefers_the_nearer_venue_over_a_rated_specialty() -> None:
    from app.services.meal_picker import MealPicker

    base = _repo().get_by_id("huetripo:528750")
    config = ItineraryConfig()
    # About 7 km north and 9 km south of the centre: both beyond the 2 km meal radius.
    near = base.model_copy(update={
        "id": "test:near", "name": "Quán A", "summary": None,
        "lat": config.center_lat + 0.063, "lon": config.center_lon,
        "rating_value": 3.0, "rating_count": 10,
    })
    far = base.model_copy(update={
        "id": "test:far", "name": "Bún bò Huế Ngon", "summary": None,
        "lat": config.center_lat - 0.081, "lon": config.center_lon,
        "rating_value": 5.0, "rating_count": 500,
    })

    chosen = MealPicker([near, far], None, config.meal_radius_km).pick(
        "restaurant", config.center_lat, config.center_lon
    )

    assert chosen is not None and chosen.id == "test:near"


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


def _nature_request() -> TripRequest:
    return TripRequest(
        origin="Hà Nội",
        destination="Huế",
        start_date=date(2026, 11, 24),
        end_date=date(2026, 11, 26),
        people=2,
        budget_vnd=6_000_000,
        categories=["restaurant", "cafe", "market", "attraction"],
        themes=["nature"],
        preferences=["ẩm thực", "thiên nhiên", "ngắm cảnh"],
    )


def test_nature_trip_plan_has_no_park_bridge_or_mall_visit() -> None:
    request = _nature_request()
    search = asyncio.run(
        SearchAgent(_repo(), MockTransportProvider(), MockHotelProvider()).search(request)
    )
    result = ItineraryAgent(places=_repo()).plan(request, search)
    visits = [event for day in result.days for event in day.events if event.kind == "VISIT"]

    assert visits
    assert all(event.category != "park" for event in visits)
    assert not [event.name for event in visits if "Vincom" in event.name or "Siêu thị" in event.name]


def test_nature_trip_has_at_most_one_real_market_visit_per_day() -> None:
    request = _nature_request()
    search = asyncio.run(
        SearchAgent(_repo(), MockTransportProvider(), MockHotelProvider()).search(request)
    )
    result = ItineraryAgent(places=_repo()).plan(request, search)
    repo = _repo()
    day_count = (request.end_date - request.start_date).days + 1
    market_days = [
        (day.date, event)
        for day in result.days
        for event in day.events
        if event.kind == "VISIT" and event.category == "market"
    ]
    specialty_visits = [
        event.name
        for _, event in market_days
        if source_type(repo.get_by_id(event.poi_id)) == "Cửa hàng đặc sản và quà tặng"
    ]

    assert len(market_days) <= day_count
    dates = [visit_date for visit_date, _ in market_days]
    assert len(dates) == len(set(dates))
    assert specialty_visits == []


_NATURE_ATTRACTION_TYPES = {"Thiên nhiên", "Văn hoá", "Nông thôn", "Làng nghề truyền thống"}


def test_nature_trip_fills_each_day_and_takes_a_cafe_break_on_the_first_two_days() -> None:
    request = _nature_request()
    search = asyncio.run(
        SearchAgent(_repo(), MockTransportProvider(), MockHotelProvider()).search(request)
    )
    repo = _repo()
    result = ItineraryAgent(places=repo).plan(request, search)

    for day in result.days:
        visits = [event for event in day.events if event.kind == "VISIT"]
        assert len(visits) >= 3, day.date
        assert sum(1 for event in visits if event.category == "market") <= 1, day.date
        for event in visits:
            if event.category == "attraction":
                assert source_type(repo.get_by_id(event.poi_id)) in _NATURE_ATTRACTION_TYPES, event.name
    for day in result.days[:2]:
        assert any(event.kind == "MEAL" and event.meal == "CAFE" for event in day.events), day.date


_NATURE_THEME_ATTRIBUTES = {"Loại hình (theo nguồn)": "Điểm du lịch, tài nguyên / Thiên nhiên"}


def _nature_plan(
    pace: str = "moderate", origin: str = "Hà Nội", transport_mode: str | None = None
) -> ItineraryResult:
    request = _nature_request().model_copy(
        update={"pace": pace, "origin": origin, "transport_mode": transport_mode}
    )
    search = asyncio.run(
        SearchAgent(_repo(), MockTransportProvider(), MockHotelProvider()).search(request)
    )
    return ItineraryAgent(places=_repo()).plan(request, search)


def _full_days(result: ItineraryResult) -> list[ItineraryDay]:
    """Every day but the return day when the trip has a return leg."""
    return result.days[:-1] if result.travel_legs else result.days


@pytest.mark.parametrize("pace,expected", [("relaxed", [3, 3]), ("moderate", [4, 4]), ("packed", [4, 5])])
def test_pace_gives_exact_sightseeing_stops_on_the_first_two_days(pace: str, expected: list[int]) -> None:
    # Sunset included. Day 1 starts at 08:34 after the bus, which leaves room for 4 stops only.
    result = _nature_plan(pace)
    counts = [sum(1 for event in day.events if event.kind == "VISIT") for day in result.days]

    assert counts[:2] == expected
    assert all(count <= {"relaxed": 3, "moderate": 4, "packed": 5}[pace] for count in counts)


def test_cafe_ends_within_twenty_minutes_before_the_sunset_stop() -> None:
    for day in _nature_plan("packed").days[:2]:
        cafe = next(event for event in day.events if event.slot == "cafe")
        sunset = next(event for event in day.events if event.slot == "sunset")
        assert timedelta(0) <= sunset.start_at - cafe.end_at <= timedelta(minutes=20), day.date


def test_stroll_and_long_visits_are_capped_at_their_length() -> None:
    from app.services.itinerary_optimizer import visit_duration_minutes

    lake = _repo().get_by_id("huetripo:528750").model_copy(update={
        "name": "Hồ Thái Dịch", "category": "attraction", "visit_minutes": 120,
        "raw_attributes": _NATURE_THEME_ATTRIBUTES,
    })
    hill = lake.model_copy(update={"name": "Đồi Thiên An", "visit_minutes": 150})
    assert visit_duration_minutes(lake, ItineraryConfig())[0] == 60
    assert visit_duration_minutes(hill, ItineraryConfig())[0] == 90


def test_full_days_have_rest_after_lunch_a_cafe_a_sunset_and_dinner_after_it() -> None:
    result = _nature_plan()
    for day in _full_days(result):
        lunch = next(event for event in day.events if event.slot == "lunch")
        rest = next(event for event in day.events if event.kind == "REST")
        sunset = next(event for event in day.events if event.slot == "sunset")
        dinner = next(event for event in day.events if event.slot == "dinner")

        assert rest.start_at == lunch.end_at
        assert rest.end_at - rest.start_at == timedelta(minutes=60)
        assert any(event.kind == "MEAL" and event.meal == "CAFE" for event in day.events), day.date
        assert sunset.kind == "VISIT" and sunset.poi_id is not None
        assert sunset.start_at.time() == time(16, 40)  # 17:10 sunset in November, minus 30 min
        assert sunset.end_at - sunset.start_at == timedelta(minutes=45)
        assert dinner.start_at >= sunset.end_at, day.date


def test_sunset_estimate_is_stored_for_the_first_trip_month() -> None:
    assert _nature_plan().sunset_estimate == "17:10"


def test_every_non_buffer_event_has_a_slot_and_the_slot_matches_its_kind() -> None:
    expected_meal_slot = {"LUNCH": "lunch", "DINNER": "dinner", "CAFE": "cafe"}
    for day in _nature_plan().days:
        for event in day.events:
            if event.kind == "BUFFER":
                assert event.slot is None
                continue
            assert event.slot is not None, (day.date, event.name)
            if event.kind == "MEAL":
                assert event.slot == expected_meal_slot[event.meal]
            elif event.kind == "MEAL_BREAK":
                assert event.slot == "lunch"
            elif event.kind == "REST":
                assert event.slot == "rest"
            elif event.slot != "sunset":
                assert event.slot in ("morning", "afternoon"), event.name


@pytest.mark.parametrize("mode,outbound,inbound,back_out,back_in", [
    ("bus", "2026-11-23 19:00", "2026-11-24 07:30", "2026-11-26 19:00", "2026-11-27 07:30"),
    ("train", "2026-11-23 19:30", "2026-11-24 09:00", "2026-11-26 19:30", "2026-11-27 09:00"),
    ("flight", "2026-11-24 06:00", "2026-11-24 07:20", "2026-11-26 18:30", "2026-11-26 19:50"),
])
def test_travel_legs_for_hanoi_use_fixed_times_per_mode(
    mode: str, outbound: str, inbound: str, back_out: str, back_in: str
) -> None:
    legs = _nature_plan(transport_mode=mode).travel_legs

    assert [leg.direction for leg in legs] == ["OUTBOUND", "RETURN"]
    assert all(leg.mode == mode.upper() and leg.estimated and leg.mock for leg in legs)
    assert legs[0].origin == "Hà Nội" and legs[0].destination == "Huế"
    assert legs[1].origin == "Huế" and legs[1].destination == "Hà Nội"
    assert legs[0].depart_at == datetime.fromisoformat(outbound)
    assert legs[0].arrive_at == datetime.fromisoformat(inbound)
    assert legs[1].depart_at == datetime.fromisoformat(back_out)
    assert legs[1].arrive_at == datetime.fromisoformat(back_in)


def test_day_one_starts_after_the_bus_arrival_plus_an_hour() -> None:
    first = next(event for event in _nature_plan(transport_mode="bus").days[0].events if event.kind != "BUFFER")

    assert first.start_at.time() >= time(8, 30)


def test_no_travel_legs_when_the_trip_starts_in_hue() -> None:
    result = _nature_plan(origin="Huế")

    assert result.travel_legs == []
    assert result.days[0].events


def test_last_day_has_no_event_after_the_return_departure_minus_an_hour() -> None:
    last = _nature_plan(transport_mode="bus").days[-1]
    deadline = datetime.combine(last.date, time(18, 0))  # bus departs 19:00

    assert all(event.end_at <= deadline for event in last.events if event.kind != "BUFFER")


def test_return_day_dinner_is_late_afternoon_not_right_after_the_last_stop() -> None:
    last = _nature_plan(transport_mode="bus").days[-1]
    dinners = [event for event in last.events if event.slot == "dinner"]

    # Bus at 19:00: dinner ends by 18:00 and starts no earlier than 18:00 - 75 min.
    assert dinners, "the return day keeps an early dinner"
    assert dinners[0].start_at.time() >= time(16, 45)
    assert dinners[0].end_at.time() <= time(18, 0)


def _synthetic(poi_id: str, **updates) -> Place:
    base = _repo().get_by_id("huetripo:528750")
    return base.model_copy(update={"id": poi_id, "summary": None, **updates})


def _reason_of(
    place: Place, *, kind: str = "VISIT", meal: str | None = None, slot: str | None = None,
    must: tuple[str, ...] = (), categories: tuple[str, ...] = (), themes: tuple[str, ...] = (),
) -> str | None:
    request = TripRequest(
        origin="Hà Nội", destination="Huế", start_date=date(2026, 11, 24), end_date=date(2026, 11, 26),
        people=2, categories=list(categories), themes=list(themes), must_include_poi_ids=list(must),
    )
    event = ItineraryEvent(
        kind=kind, meal=meal, slot=slot, poi_id=place.id, name=place.name, category=place.category,
        start_at=_at(11), end_at=_at(12),
    )
    return _reason(event, place, request, "nature" in themes)


def test_reason_must_include_wins_over_every_other_fact() -> None:
    place = _synthetic("test:must", name="Cafe Riverside", category="cafe", rating_value=4.9, rating_count=900)

    assert _reason_of(place, kind="MEAL", meal="CAFE", must=("test:must",)) == "bạn muốn đến"


def test_reason_sunset_slot_and_view_cafe_and_specialty() -> None:
    sunset_place = _synthetic("test:sunset", name="Sông Đông Ba", category="attraction", raw_attributes={})
    view_cafe = _synthetic("test:cafe", name="Riverside Garden Cafe", category="cafe")
    specialty = _synthetic("test:bun", name="Bún bò Huế Ngon", category="restaurant")

    assert _reason_of(sunset_place, slot="sunset") == "điểm ngắm hoàng hôn"
    assert _reason_of(view_cafe, kind="MEAL", meal="CAFE", slot="cafe") == "cà phê có view"
    assert _reason_of(specialty, kind="MEAL", meal="LUNCH", slot="lunch") == "đặc sản Huế"


def test_reason_nature_needs_the_nature_theme_then_category_then_rating() -> None:
    nature = _synthetic(
        "test:doi", name="Đồi Thiên An", category="attraction", raw_attributes=_NATURE_THEME_ATTRIBUTES
    )

    assert _reason_of(nature, themes=("nature",)) == "hợp sở thích thiên nhiên"
    assert _reason_of(nature, categories=("attraction",)) == "hợp sở thích tham quan"
    assert _reason_of(nature) is None


def test_reason_category_and_rating_formats() -> None:
    market = _synthetic("test:cho", name="Chợ Test", category="market", raw_attributes={})
    rated = _synthetic("test:rated", name="Điểm đẹp", category="historic", rating_value=4.5, rating_count=197)
    weak = _synthetic("test:weak", name="Điểm thường", category="historic", rating_value=4.2, rating_count=300)
    few = _synthetic("test:few", name="Điểm mới", category="historic", rating_value=4.8, rating_count=12)

    assert _reason_of(market, categories=("market",)) == "hợp sở thích chợ"
    assert _reason_of(rated) == "4,5/5, 197 lượt"
    assert _reason_of(weak) is None
    assert _reason_of(few) is None


def test_travel_leg_and_slot_fields_round_trip_through_json() -> None:
    leg = TravelLeg(
        direction="OUTBOUND", mode="BUS", origin="Hà Nội", destination="Huế",
        depart_at=datetime(2026, 11, 23, 19, 0), arrive_at=datetime(2026, 11, 24, 7, 30),
    )
    rest = ItineraryEvent(kind="REST", start_at=_at(12), end_at=_at(13), name="Nghỉ trưa", slot="rest")
    sunset = _visit("huetripo:A", "attraction", 16).model_copy(
        update={"slot": "sunset", "reason": "điểm ngắm hoàng hôn"}
    )
    result = ItineraryResult(
        days=[_day([rest, sunset])],
        unplanned_poi_ids=[],
        warnings=[],
        validation=ItineraryValidation(valid=True, warnings=[]),
        travel_legs=[leg],
        sunset_estimate="17:10",
    )

    payload = result.model_dump(mode="json")
    restored = ItineraryResult.model_validate(payload)

    assert restored == result
    assert payload["travel_legs"][0]["mock"] is True
    assert payload["days"][0]["events"][0]["kind"] == "REST"
    assert ItineraryResult.model_validate({**payload, "travel_legs": []}).travel_legs == []
