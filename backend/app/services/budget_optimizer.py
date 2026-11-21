"""Integer-only budget calculation and offer-combination enumeration."""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import product

from app.repositories.hue_places import HuePlacesRepository
from app.schemas.budget import BudgetOption, BudgetResult, BudgetStatus, CostItem
from app.schemas.offer import HotelOffer, TransportOffer
from app.schemas.place import Place
from app.schemas.request import TripRequest
from app.schemas.search import SearchResult

SIGHTSEEING_CATEGORIES = frozenset({"historic", "attraction", "museum", "religious", "park", "market"})
FOOD_CATEGORIES = ("restaurant", "cafe")
HUE_SOURCE = "HUE_POI_SOURCE"
DAY_TRIP_WARNING = "Chuyến đi trong ngày: không cần lưu trú."
MEAL_UNIT = "VND_PER_PERSON_PER_MEAL_ASSUMED"
ADMISSION_UNIT = "VND_PER_PERSON"
_WITHIN_STATUSES = frozenset({"WITHIN_BUDGET", "WITHIN_BUDGET_EXCLUDING_UNKNOWN"})
_STATUS_RANK = {
    "WITHIN_BUDGET": 0,
    "WITHIN_BUDGET_EXCLUDING_UNKNOWN": 1,
    "UNKNOWN": 2,
    "OVER_BUDGET": 3,
}


@dataclass(frozen=True)
class BudgetConfig:
    """Explicit assumptions. Each one is labelled as an estimate in the output."""

    include_food: bool = True
    food_per_person_per_day_vnd: int | None = None
    restaurant_meals_per_day: int = 2
    cafe_visits_per_day: int = 1
    local_transport_per_day_vnd: int | None = 300_000
    guests_per_room: int = 2
    max_options: int = 10

    def __post_init__(self) -> None:
        if self.food_per_person_per_day_vnd is not None and self.food_per_person_per_day_vnd <= 0:
            raise ValueError("food_per_person_per_day_vnd must be positive or None")
        if self.local_transport_per_day_vnd is not None and self.local_transport_per_day_vnd < 0:
            raise ValueError("local_transport_per_day_vnd must be non-negative or None")
        if self.restaurant_meals_per_day < 0 or self.cafe_visits_per_day < 0:
            raise ValueError("meals per day must be non-negative")
        if self.guests_per_room < 1 or self.max_options < 1:
            raise ValueError("guests_per_room and max_options must be at least 1")


class BudgetAgent:
    """Select and price provider offers without fabricating missing prices."""

    def __init__(
        self,
        config: BudgetConfig | None = None,
        places: HuePlacesRepository | None = None,
    ) -> None:
        self.config = config or BudgetConfig()
        self.places = places
        self._repository_medians: dict[str, tuple[int, int]] | None = None

    def build(
        self,
        request: TripRequest,
        search: SearchResult,
        visit_poi_ids: list[str] | None = None,
    ) -> BudgetResult:
        visits = self._visited_places(search, visit_poi_ids or [])
        medians = self._food_medians(search)
        outbound = self._transport_choices(search.transport_offers, "OUTBOUND", request.people)
        returning = self._transport_choices(search.transport_offers, "RETURN", request.people)
        hotels = [offer for offer in search.hotel_offers if offer.rooms_available >= request.rooms] or [None]

        options = [
            self._build_option(request, out_offer, return_offer, hotel, visits, medians)
            for out_offer, return_offer, hotel in product(outbound, returning, hotels)
        ]
        options.sort(key=self._option_sort_key)
        self._assign_labels(options)
        shortfall = self._shortfall(request.budget_vnd, options)
        warnings = self._result_warnings(request, search, shortfall)
        capped = self._cap(options, self.config.max_options)
        return BudgetResult(options=capped, warnings=warnings, shortfall_vnd=shortfall)

    def _food_medians(self, search: SearchResult) -> dict[str, tuple[int, int]]:
        """Median reference range per food category; repository results are cached."""
        if self.places is None:
            return _category_medians([item.place for item in search.poi_candidates])
        if self._repository_medians is None:
            self._repository_medians = _category_medians(self.places.list_all())
        return self._repository_medians

    def _visited_places(self, search: SearchResult, poi_ids: list[str]) -> list[Place]:
        candidates = {item.place.id: item.place for item in search.poi_candidates}
        visits: list[Place] = []
        for poi_id in poi_ids:
            place = candidates[poi_id] if poi_id in candidates else self._lookup(poi_id)
            if place is None:
                raise ValueError(f"Unknown poi_id: {poi_id}")
            visits.append(place)
        return visits

    def _lookup(self, poi_id: str) -> Place | None:
        return self.places.get_by_id(poi_id) if self.places is not None else None

    @staticmethod
    def _transport_choices(
        offers: list[TransportOffer], leg: str, people: int
    ) -> list[TransportOffer | None]:
        matches = [offer for offer in offers if offer.leg == leg and offer.seats_available >= people]
        return matches or [None]

    def _build_option(
        self,
        request: TripRequest,
        outbound: TransportOffer | None,
        returning: TransportOffer | None,
        hotel: HotelOffer | None,
        visits: list[Place],
        medians: dict[str, tuple[int, int]],
    ) -> BudgetOption:
        days = (request.end_date - request.start_date).days + 1
        items: list[CostItem] = [
            self._transport_item("transport_outbound", "Outbound transport", outbound, request.people),
            self._transport_item("transport_return", "Return transport", returning, request.people),
            *self._lodging_items(request, hotel),
        ]
        local = self._local_transport_item(days)
        if local is not None:
            items.append(local)
        items.extend(self._food_items(request.people, days, visits, medians))
        items.extend(self._admission_items(visits, request.people))

        known_total = sum(item.amount_vnd for item in items if item.amount_vnd is not None)
        known_max = sum(_max_amount(item) for item in items)
        unknown_count = sum(item.amount_vnd is None for item in items)
        status, remaining, status_warnings = self._budget_status(
            request.budget_vnd, known_total, known_max, unknown_count
        )
        warnings: list[str] = [DAY_TRIP_WARNING] if request.is_day_trip else []
        if unknown_count:
            warnings.append("Known total excludes items with an unknown amount.")
        warnings.extend(status_warnings)
        return BudgetOption(
            transport_outbound=outbound,
            transport_return=returning,
            hotel=hotel,
            items=items,
            known_total_vnd=known_total,
            known_total_max_vnd=known_max,
            unknown_item_count=unknown_count,
            budget_status=status,
            budget_remaining_vnd=remaining,
            warnings=warnings,
        )

    @staticmethod
    def _transport_item(
        code: str, label: str, offer: TransportOffer | None, people: int
    ) -> CostItem:
        if offer is None:
            return CostItem(code=code, label=label, quantity=people, price_unit="VND_PER_PERSON_PER_LEG", source="UNAVAILABLE", price_kind="UNKNOWN", note="No compatible provider offer.")
        return CostItem(
            code=code,
            label=label,
            amount_vnd=offer.price_vnd * people,
            quantity=people,
            price_unit=offer.price_unit,
            source=offer.source,
            price_kind="QUOTED",
            note=f"{offer.provider} ({offer.id})",
        )

    def _lodging_items(self, request: TripRequest, hotel: HotelOffer | None) -> list[CostItem]:
        """A same-day trip has no lodging line at all."""
        if request.is_day_trip:
            return []
        return [self._hotel_item(request, hotel)]

    @staticmethod
    def _hotel_item(request: TripRequest, hotel: HotelOffer | None) -> CostItem:
        nights = (request.end_date - request.start_date).days
        quantity = request.rooms * nights
        if hotel is None:
            return CostItem(code="lodging", label="Lodging", quantity=quantity, price_unit="VND_PER_ROOM_PER_NIGHT", source="UNAVAILABLE", price_kind="UNKNOWN", note="No compatible provider offer.")
        return CostItem(
            code="lodging",
            label="Lodging",
            amount_vnd=hotel.price_per_room_night_vnd * quantity,
            quantity=quantity,
            price_unit=hotel.price_unit,
            source=hotel.source,
            price_kind="QUOTED",
            note=f"{hotel.hotel_name} ({hotel.id})",
        )

    def _local_transport_item(self, days: int) -> CostItem | None:
        per_day = self.config.local_transport_per_day_vnd
        if per_day is None:
            return None
        return CostItem(
            code="local_transport",
            label="Local transport in Hue",
            amount_vnd=per_day * days,
            quantity=days,
            price_unit="VND_PER_GROUP_PER_DAY",
            source="BUDGET_CONFIG",
            price_kind="ESTIMATED",
            note="Assumed group cost per day; the source has no in-city transport prices.",
        )

    def _food_items(
        self,
        people: int,
        days: int,
        visits: list[Place],
        medians: dict[str, tuple[int, int]],
    ) -> list[CostItem]:
        if not self.config.include_food:
            return [
                CostItem(
                    code="food_estimate",
                    label="Food estimate",
                    quantity=people * days,
                    price_unit="VND_PER_PERSON_PER_DAY",
                    source="BUDGET_CONFIG",
                    price_kind="UNKNOWN",
                    note="Food is excluded by configuration.",
                )
            ]
        if self.config.food_per_person_per_day_vnd is not None:
            return [_fixed_food_item(self.config.food_per_person_per_day_vnd, people * days)]
        return self._data_food_items(people, days, visits, medians)

    def _data_food_items(
        self,
        people: int,
        days: int,
        visits: list[Place],
        medians: dict[str, tuple[int, int]],
    ) -> list[CostItem]:
        items = [
            _meal_item(place, people, medians)
            for place in visits
            if place.category in FOOD_CATEGORIES
        ]
        visited = Counter(place.category for place in visits)
        plan = (
            ("restaurant", "food_restaurant_other", "Other restaurant meals", self.config.restaurant_meals_per_day),
            ("cafe", "food_cafe_other", "Other cafe visits", self.config.cafe_visits_per_day),
        )
        for category, code, label, per_day in plan:
            remaining = max(days * per_day - visited[category], 0)
            if remaining:
                items.append(_remaining_item(code, label, category, remaining, people, medians))
        return items

    @staticmethod
    def _admission_items(visits: list[Place], people: int) -> list[CostItem]:
        if not visits:
            return [
                CostItem(
                    code="admission_fees",
                    label="Attraction admission fees",
                    quantity=1,
                    price_unit=ADMISSION_UNIT,
                    source=HUE_SOURCE,
                    price_kind="UNKNOWN",
                    note="No visits selected yet",
                )
            ]
        return [_admission_item(place, people) for place in visits if place.category in SIGHTSEEING_CATEGORIES]

    @staticmethod
    def _budget_status(
        budget_vnd: int | None, known_total: int, known_max: int, unknown_count: int
    ) -> tuple[BudgetStatus, int | None, list[str]]:
        if budget_vnd is None:
            return "UNKNOWN", None, []
        remaining = budget_vnd - known_max
        # Unknown costs can only increase the final total. A known minimum above
        # the limit is therefore conclusively over budget.
        if known_total > budget_vnd:
            return "OVER_BUDGET", remaining, []
        if known_max <= budget_vnd:
            status: BudgetStatus = "WITHIN_BUDGET_EXCLUDING_UNKNOWN" if unknown_count else "WITHIN_BUDGET"
            return status, remaining, []
        return "UNKNOWN", remaining, ["Estimated range straddles the budget."]

    @staticmethod
    def _option_sort_key(option: BudgetOption) -> tuple[int, int, int]:
        return _STATUS_RANK[option.budget_status], option.known_total_max_vnd, option.unknown_item_count

    @staticmethod
    def _assign_labels(options: list[BudgetOption]) -> None:
        """Label BUDGET, COMFORT and BALANCED on the full list, each at most once."""
        if not options:
            return
        budget = min(options, key=lambda option: option.known_total_max_vnd)
        budget.label = "BUDGET"
        within = [option for option in options if option.budget_status in _WITHIN_STATUSES]
        if not within:
            return
        top = max(within, key=lambda option: option.known_total_max_vnd)
        if top.label is None:
            top.label = "COMFORT"
        # Compare doubled values so the midpoint stays an integer.
        midpoint_x2 = budget.known_total_max_vnd + top.known_total_max_vnd
        unlabelled = [option for option in within if option.label is None]
        if unlabelled:
            balanced = min(
                unlabelled,
                key=lambda option: (
                    abs(2 * option.known_total_max_vnd - midpoint_x2),
                    option.known_total_max_vnd,
                ),
            )
            balanced.label = "BALANCED"

    @staticmethod
    def _cap(options: list[BudgetOption], max_options: int) -> list[BudgetOption]:
        """Keep every labelled option, then the best others up to max_options."""
        labelled = [option for option in options if option.label is not None]
        others = [option for option in options if option.label is None]
        room = max(max_options - len(labelled), 0)
        kept = {id(option) for option in labelled + others[:room]}
        return [option for option in options if id(option) in kept]

    @staticmethod
    def _shortfall(budget_vnd: int | None, options: list[BudgetOption]) -> int | None:
        if budget_vnd is None or not options:
            return None
        if any(option.budget_status in _WITHIN_STATUSES for option in options):
            return None
        gap = min(option.known_total_vnd for option in options) - budget_vnd
        return gap if gap > 0 else None

    def _result_warnings(
        self, request: TripRequest, search: SearchResult, shortfall: int | None
    ) -> list[str]:
        warnings = list(search.warnings)
        if not search.transport_offers:
            warnings.append("Transport costs are unknown because no provider offer was available.")
        if not search.hotel_offers and not request.is_day_trip:
            warnings.append("Lodging costs are unknown because no provider offer was available.")
        if request.people > request.rooms * self.config.guests_per_room:
            warnings.append(f"{request.people} people may not fit in {request.rooms} room(s)")
        if shortfall is not None:
            warnings.append(f"Cheapest option exceeds the budget by {shortfall:,} VND.")
        return warnings


def _max_amount(item: CostItem) -> int:
    if item.amount_max_vnd is not None:
        return item.amount_max_vnd
    return item.amount_vnd or 0


def _category_medians(places: Iterable[Place]) -> dict[str, tuple[int, int]]:
    """Integer medians of the min and max reference price for each food category."""
    pool = list(places)
    medians: dict[str, tuple[int, int]] = {}
    for category in FOOD_CATEGORIES:
        ranges = [
            (place.price_min_vnd, place.price_max_vnd)
            for place in pool
            if place.category == category
            and place.price_status == "REFERENCE_RANGE"
            and place.price_min_vnd is not None
            and place.price_max_vnd is not None
        ]
        if ranges:
            low = int(statistics.median(low for low, _ in ranges))
            high = int(statistics.median(high for _, high in ranges))
            medians[category] = (low, high)
    return medians


def _fixed_food_item(per_day: int, quantity: int) -> CostItem:
    return CostItem(
        code="food_estimate",
        label="Food estimate",
        amount_vnd=per_day * quantity,
        quantity=quantity,
        price_unit="VND_PER_PERSON_PER_DAY",
        source="BUDGET_CONFIG",
        price_kind="ESTIMATED",
        note=f"Configured at {per_day} VND per person per day.",
    )


def _meal_item(place: Place, people: int, medians: dict[str, tuple[int, int]]) -> CostItem:
    """One visited restaurant or cafe is one group meal."""
    if place.price_min_vnd is not None and place.price_max_vnd is not None:
        low, high = place.price_min_vnd, place.price_max_vnd
        note = "Reference range from huetripo; assumed per person per meal; verify before travel."
    elif place.category in medians:
        low, high = medians[place.category]
        note = "No price on this POI; category median used. Assumed per person per meal."
    else:
        return CostItem(
            code="meal",
            label=place.name,
            quantity=1,
            price_unit=MEAL_UNIT,
            source=HUE_SOURCE,
            price_kind="UNKNOWN",
            note="No price on this POI and no priced POIs in its category.",
            poi_id=place.id,
        )
    return CostItem(
        code="meal",
        label=place.name,
        amount_vnd=low * people,
        amount_max_vnd=high * people,
        quantity=1,
        price_unit=MEAL_UNIT,
        source=HUE_SOURCE,
        price_kind="ESTIMATED",
        note=note,
        poi_id=place.id,
    )


def _remaining_item(
    code: str,
    label: str,
    category: str,
    quantity: int,
    people: int,
    medians: dict[str, tuple[int, int]],
) -> CostItem:
    """Meals not yet chosen, priced at the category median."""
    if category not in medians:
        return CostItem(
            code=code,
            label=label,
            quantity=quantity,
            price_unit=MEAL_UNIT,
            source=HUE_SOURCE,
            price_kind="UNKNOWN",
            note=f"No priced {category} POI in the source; amount unknown.",
        )
    low, high = medians[category]
    return CostItem(
        code=code,
        label=label,
        amount_vnd=low * people * quantity,
        amount_max_vnd=high * people * quantity,
        quantity=quantity,
        price_unit=MEAL_UNIT,
        source=HUE_SOURCE,
        price_kind="ESTIMATED",
        note=f"Median of {category} reference ranges in huetripo; assumed per person per meal; verify before travel.",
    )


def _admission_item(place: Place, people: int) -> CostItem:
    if place.price_status == "REFERENCE_RANGE" and place.price_min_vnd is not None and place.price_max_vnd is not None:
        return CostItem(
            code="admission",
            label=place.name,
            amount_vnd=place.price_min_vnd * people,
            amount_max_vnd=place.price_max_vnd * people,
            quantity=people,
            price_unit=ADMISSION_UNIT,
            source=HUE_SOURCE,
            price_kind="ESTIMATED",
            note="Reference price from huetripo; assumed per person; verify before travel.",
            poi_id=place.id,
        )
    if place.price_status == "FREE_CLAIM":
        return CostItem(
            code="admission",
            label=place.name,
            amount_vnd=0,
            quantity=people,
            price_unit=ADMISSION_UNIT,
            source=HUE_SOURCE,
            price_kind="ESTIMATED",
            note="Free according to source.",
            poi_id=place.id,
        )
    return CostItem(
        code="admission",
        label=place.name,
        quantity=people,
        price_unit=ADMISSION_UNIT,
        source=HUE_SOURCE,
        price_kind="UNKNOWN",
        note="No admission price in the source.",
        poi_id=place.id,
    )
