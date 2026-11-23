"""PHASE 5 deterministic Budget Agent tests."""

from __future__ import annotations

import asyncio
import statistics
import sys
from datetime import date
from pathlib import Path

from app.schemas.budget import BudgetOption, CostItem


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
from app.services.budget_optimizer import BudgetAgent, BudgetConfig  # noqa: E402

REPO = HuePlacesRepository(BACKEND / "data" / "hue.sqlite")
SIGHTSEEING = {"historic", "attraction", "museum", "religious", "park", "market"}
ALL_OPTIONS = BudgetConfig(max_options=27)


def _request(
    budget_vnd: int | None = 4_000_000, people: int = 2, rooms: int = 1
) -> TripRequest:
    return TripRequest(
        origin="Đà Nẵng", destination="Huế", start_date=date(2026, 12, 10), end_date=date(2026, 12, 12),
        people=people, rooms=rooms, budget_vnd=budget_vnd, categories=["historic"], keyword="dai noi"
    )


def _search(transport_mode: str = "normal", hotel_mode: str = "normal"):
    agent = SearchAgent(REPO, MockTransportProvider(transport_mode), MockHotelProvider(hotel_mode))  # type: ignore[arg-type]
    return asyncio.run(agent.search(_request()))


def _pick(predicate) -> Place:
    return next(place for place in REPO.list_all() if predicate(place))


def _item(option: BudgetOption, code: str) -> CostItem:
    return next(item for item in option.items if item.code == code)


def _find(result, mode: str, tier: str) -> BudgetOption:
    return next(
        option
        for option in result.options
        if option.transport_outbound is not None
        and option.transport_outbound.mode == mode
        and option.transport_return is not None
        and option.transport_return.mode == mode
        and option.hotel is not None
        and option.hotel.tier == tier
    )


def test_bus_and_three_star_option_is_priced_per_person_and_per_room_night() -> None:
    result = BudgetAgent(ALL_OPTIONS).build(_request(), _search())
    option = _find(result, "BUS", "THREE_STAR")

    outbound = _item(option, "transport_outbound")
    returning = _item(option, "transport_return")
    lodging = _item(option, "lodging")
    local = _item(option, "local_transport")
    assert outbound.amount_vnd == 800_000  # 400,000 x 2 people
    assert returning.amount_vnd == 800_000
    assert outbound.quantity == 2
    assert outbound.price_unit == "VND_PER_PERSON_PER_LEG"
    assert lodging.amount_vnd == 1_300_000  # 650,000 x 2 nights
    assert lodging.quantity == 2
    assert lodging.price_unit == "VND_PER_ROOM_PER_NIGHT"
    assert local.amount_vnd == 900_000  # 300,000 x 3 days
    assert local.quantity == 3
    assert local.price_unit == "VND_PER_GROUP_PER_DAY"
    assert local.price_kind == "ESTIMATED"
    assert local.source == "BUDGET_CONFIG"


def test_food_is_priced_over_three_days_for_a_two_night_trip() -> None:
    fixed = BudgetAgent(BudgetConfig(food_per_person_per_day_vnd=200_000), places=REPO)
    food = _item(fixed.build(_request(), _search()).options[0], "food_estimate")
    assert food.quantity == 6  # 2 people x 3 days
    assert food.amount_vnd == 1_200_000

    data = BudgetAgent(BudgetConfig(), places=REPO).build(_request(), _search()).options[0]
    assert _item(data, "food_restaurant_other").quantity == 6  # 3 days x 2 meals
    assert _item(data, "food_cafe_other").quantity == 3  # 3 days x 1 visit


def test_data_medians_equal_statistics_median_of_repository_prices() -> None:
    places = REPO.list_all()
    restaurants = [p for p in places if p.category == "restaurant" and p.price_status == "REFERENCE_RANGE"]
    cafes = [p for p in places if p.category == "cafe" and p.price_status == "REFERENCE_RANGE"]
    restaurant_min = int(statistics.median(p.price_min_vnd for p in restaurants))
    restaurant_max = int(statistics.median(p.price_max_vnd for p in restaurants))
    cafe_min = int(statistics.median(p.price_min_vnd for p in cafes))

    option = BudgetAgent(BudgetConfig(), places=REPO).build(_request(), _search()).options[0]
    other = _item(option, "food_restaurant_other")
    assert other.amount_vnd == 6 * 2 * restaurant_min  # 6 meals x 2 people
    assert other.amount_max_vnd == 6 * 2 * restaurant_max
    assert _item(option, "food_cafe_other").amount_vnd == 3 * 2 * cafe_min


def test_admission_is_priced_from_reference_free_and_unknown_pois() -> None:
    dai_noi = _pick(lambda p: p.name == "Đại Nội Huế")
    free = _pick(lambda p: p.category in SIGHTSEEING and p.price_status == "FREE_CLAIM")
    unknown = _pick(lambda p: p.category in SIGHTSEEING and p.price_status == "UNKNOWN")
    visits = [dai_noi.id, free.id, unknown.id]

    option = BudgetAgent(BudgetConfig(), places=REPO).build(
        _request(), _search(), visit_poi_ids=visits
    ).options[0]
    lines = {item.poi_id: item for item in option.items if item.code == "admission"}

    assert dai_noi.price_min_vnd == 200_000
    assert lines[dai_noi.id].amount_vnd == 400_000  # 200,000 x 2 people
    assert lines[dai_noi.id].price_kind == "ESTIMATED"
    assert lines[free.id].amount_vnd == 0
    assert lines[free.id].note == "Free according to source."
    assert lines[unknown.id].amount_vnd is None
    assert lines[unknown.id].price_kind == "UNKNOWN"


def test_no_visits_gives_one_unknown_admission_line() -> None:
    option = BudgetAgent(BudgetConfig(), places=REPO).build(_request(), _search()).options[0]
    line = _item(option, "admission_fees")

    assert line.amount_vnd is None
    assert line.price_kind == "UNKNOWN"
    assert line.note == "No visits selected yet"


def test_visited_restaurant_becomes_a_meal_line_and_reduces_other_meals() -> None:
    restaurant = _pick(lambda p: p.category == "restaurant" and p.price_status == "REFERENCE_RANGE")
    option = BudgetAgent(BudgetConfig(), places=REPO).build(
        _request(), _search(), visit_poi_ids=[restaurant.id]
    ).options[0]

    meal = next(item for item in option.items if item.code == "meal")
    assert meal.poi_id == restaurant.id
    assert meal.amount_vnd == restaurant.price_min_vnd * 2
    assert meal.price_kind == "ESTIMATED"
    assert meal.source == "HUE_POI_SOURCE"
    assert _item(option, "food_restaurant_other").quantity == 5  # 6 meals minus the visit


def test_unknown_poi_id_raises_value_error() -> None:
    agent = BudgetAgent(BudgetConfig(), places=REPO)
    try:
        agent.build(_request(), _search(), visit_poi_ids=["no-such-poi"])
    except ValueError as error:
        assert str(error) == "Unknown poi_id: no-such-poi"
    else:
        raise AssertionError("expected ValueError for unknown poi_id")


def test_missing_provider_prices_are_unknown_not_zero() -> None:
    result = BudgetAgent().build(_request(), _search("empty", "empty"))
    option = result.options[0]

    assert _item(option, "transport_outbound").amount_vnd is None
    assert _item(option, "transport_return").amount_vnd is None
    assert _item(option, "lodging").amount_vnd is None
    assert option.transport_outbound is None
    assert option.hotel is None
    assert any("unknown" in warning.lower() for warning in result.warnings)


def test_budget_is_repeatable_for_identical_input() -> None:
    agent = BudgetAgent(BudgetConfig(), places=REPO)
    search = _search()

    assert agent.build(_request(), search).model_dump() == agent.build(_request(), search).model_dump()


def test_include_food_false_makes_food_unknown() -> None:
    option = BudgetAgent(BudgetConfig(include_food=False), places=REPO).build(
        _request(), _search()
    ).options[0]
    food = _item(option, "food_estimate")

    assert food.amount_vnd is None
    assert food.price_kind == "UNKNOWN"


def test_known_subtotal_over_budget_is_reported_even_with_unknown_admission_fees() -> None:
    result = BudgetAgent().build(_request(budget_vnd=2_000_000), _search())

    assert result.options
    for option in result.options:
        assert option.budget_status == "OVER_BUDGET"
        assert option.budget_remaining_vnd == 2_000_000 - option.known_total_max_vnd


def test_tiny_budget_marks_every_option_over_budget_with_a_shortfall() -> None:
    result = BudgetAgent(ALL_OPTIONS).build(_request(budget_vnd=1_000_000), _search())

    assert result.options
    assert all(option.budget_status == "OVER_BUDGET" for option in result.options)
    assert result.shortfall_vnd is not None and result.shortfall_vnd > 0
    assert any("exceeds the budget" in warning for warning in result.warnings)


def test_large_budget_marks_options_with_unknown_admission_as_excluding_unknown() -> None:
    result = BudgetAgent(ALL_OPTIONS).build(_request(budget_vnd=50_000_000), _search())

    assert result.shortfall_vnd is None
    assert all(option.budget_status == "WITHIN_BUDGET_EXCLUDING_UNKNOWN" for option in result.options)


def test_labels_mark_lowest_and_highest_within_budget_each_at_most_once() -> None:
    result = BudgetAgent(ALL_OPTIONS).build(_request(budget_vnd=50_000_000), _search())
    labels = [option.label for option in result.options if option.label is not None]

    assert len(labels) == len(set(labels))
    budget_option = next(option for option in result.options if option.label == "BUDGET")
    comfort_option = next(option for option in result.options if option.label == "COMFORT")
    assert budget_option.known_total_max_vnd == min(o.known_total_max_vnd for o in result.options)
    assert comfort_option.known_total_max_vnd == max(o.known_total_max_vnd for o in result.options)


def test_max_options_caps_the_list_and_keeps_labelled_options() -> None:
    full = BudgetAgent(ALL_OPTIONS).build(_request(budget_vnd=50_000_000), _search())
    capped = BudgetAgent(BudgetConfig(max_options=10)).build(_request(budget_vnd=50_000_000), _search())

    assert len(capped.options) <= 10
    capped_dumps = [option.model_dump() for option in capped.options]
    for option in full.options:
        if option.label is not None:
            assert option.model_dump() in capped_dumps


def test_five_people_in_one_room_gets_a_room_warning() -> None:
    result = BudgetAgent(BudgetConfig(), places=REPO).build(_request(people=5, rooms=1), _search())

    assert "5 people may not fit in 1 room(s)" in result.warnings


def test_hue_origin_has_no_transport_lines_and_says_no_intercity_transport_is_needed() -> None:
    request = TripRequest(
        origin="Huế", destination="Huế", start_date=date(2026, 12, 10), end_date=date(2026, 12, 12),
        people=2, budget_vnd=None, categories=["historic"], keyword="dai noi",
    )
    search = asyncio.run(SearchAgent(REPO, MockTransportProvider(), MockHotelProvider()).search(request))

    result = BudgetAgent(ALL_OPTIONS, places=REPO).build(request, search)

    assert result.options
    for option in result.options:
        codes = {item.code for item in option.items}
        assert not codes & {"transport_outbound", "transport_return"}
        assert option.transport_outbound is None
        assert option.transport_return is None
        assert "Bạn đã ở Huế: không cần xe liên tỉnh." in option.warnings
        assert option.hotel is not None


def _chosen_request(**changes: object) -> TripRequest:
    return _request().model_copy(update=changes)


def test_bus_and_homestay_choice_makes_every_budget_option_use_them() -> None:
    request = _chosen_request(transport_mode="bus", hotel_tier="homestay")
    search = asyncio.run(
        SearchAgent(REPO, MockTransportProvider(), MockHotelProvider()).search(request)
    )
    result = BudgetAgent(ALL_OPTIONS).build(request, search)

    assert result.options
    for option in result.options:
        assert option.transport_outbound is not None and option.transport_return is not None
        assert option.transport_outbound.provider == "Hue Sleeper Bus Demo"
        assert option.transport_return.provider == "Hue Sleeper Bus Demo"
        assert option.hotel is not None and option.hotel.hotel_name == "Old Quarter Homestay Demo"


def test_flight_and_resort_choice_makes_the_cheapest_option_use_them() -> None:
    request = _chosen_request(transport_mode="flight", hotel_tier="resort")
    search = asyncio.run(
        SearchAgent(REPO, MockTransportProvider(), MockHotelProvider()).search(request)
    )
    result = BudgetAgent(ALL_OPTIONS).build(request, search)
    cheapest = _find(result, "FLIGHT", "FOUR_STAR")

    assert cheapest.transport_outbound.provider == "Hue Air Demo"
    assert cheapest.transport_return.provider == "Hue Air Demo"
    assert cheapest.hotel.hotel_name == "Perfume River Demo Resort"
    assert all(option.transport_outbound.mode == "FLIGHT" for option in result.options)
