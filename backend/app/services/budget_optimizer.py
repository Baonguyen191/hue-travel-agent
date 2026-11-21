"""Integer-only budget calculation and offer-combination enumeration."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from app.schemas.budget import BudgetOption, BudgetResult, BudgetStatus, CostItem
from app.schemas.offer import HotelOffer, TransportOffer
from app.schemas.request import TripRequest
from app.schemas.search import SearchResult


@dataclass(frozen=True)
class BudgetConfig:
    """Explicit assumptions. Set food_per_person_per_day_vnd to None to omit it."""

    food_per_person_per_day_vnd: int | None = 200_000

    def __post_init__(self) -> None:
        if self.food_per_person_per_day_vnd is not None and self.food_per_person_per_day_vnd <= 0:
            raise ValueError("food_per_person_per_day_vnd must be positive or None")


class BudgetAgent:
    """Select and price provider offers without fabricating missing prices."""

    def __init__(self, config: BudgetConfig | None = None) -> None:
        self.config = config or BudgetConfig()

    def build(self, request: TripRequest, search: SearchResult) -> BudgetResult:
        outbound = self._transport_choices(search.transport_offers, "OUTBOUND", request.people)
        returning = self._transport_choices(search.transport_offers, "RETURN", request.people)
        hotels = [offer for offer in search.hotel_offers if offer.rooms_available >= request.rooms] or [None]

        options = [
            self._build_option(request, search, out_offer, return_offer, hotel)
            for out_offer, return_offer, hotel in product(outbound, returning, hotels)
        ]
        options.sort(key=self._option_sort_key)
        warnings = list(search.warnings)
        if not search.transport_offers:
            warnings.append("Transport costs are unknown because no provider offer was available.")
        if not search.hotel_offers:
            warnings.append("Lodging costs are unknown because no provider offer was available.")
        return BudgetResult(options=options, warnings=warnings)

    @staticmethod
    def _transport_choices(
        offers: list[TransportOffer], leg: str, people: int
    ) -> list[TransportOffer | None]:
        matches = [offer for offer in offers if offer.leg == leg and offer.seats_available >= people]
        return matches or [None]

    def _build_option(
        self,
        request: TripRequest,
        search: SearchResult,
        outbound: TransportOffer | None,
        returning: TransportOffer | None,
        hotel: HotelOffer | None,
    ) -> BudgetOption:
        items: list[CostItem] = [
            self._transport_item("transport_outbound", "Outbound transport", outbound, request.people),
            self._transport_item("transport_return", "Return transport", returning, request.people),
            self._hotel_item(request, hotel),
        ]
        nights = (request.end_date - request.start_date).days
        if self.config.food_per_person_per_day_vnd is not None:
            quantity = request.people * nights
            items.append(
                CostItem(
                    code="food_estimate",
                    label="Food estimate",
                    amount_vnd=self.config.food_per_person_per_day_vnd * quantity,
                    quantity=quantity,
                    price_unit="VND_PER_PERSON_PER_DAY",
                    source="BUDGET_CONFIG",
                    price_kind="ESTIMATED",
                    note=f"Configured at {self.config.food_per_person_per_day_vnd} VND per person per day.",
                )
            )
        else:
            items.append(
                CostItem(
                    code="food_estimate",
                    label="Food estimate",
                    quantity=request.people * nights,
                    price_unit="VND_PER_PERSON_PER_DAY",
                    source="BUDGET_CONFIG",
                    price_kind="UNKNOWN",
                    note="No per-person-per-day food assumption was configured.",
                )
            )
        items.append(self._admission_item(search))

        known_total = sum(item.amount_vnd for item in items if item.amount_vnd is not None)
        unknown_count = sum(item.amount_vnd is None for item in items)
        status, remaining = self._budget_status(request.budget_vnd, known_total, unknown_count)
        warnings = []
        if unknown_count:
            warnings.append("Known total excludes items with an unknown amount.")
        return BudgetOption(
            transport_outbound=outbound,
            transport_return=returning,
            hotel=hotel,
            items=items,
            known_total_vnd=known_total,
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

    @staticmethod
    def _admission_item(search: SearchResult) -> CostItem:
        attractions = sum(
            candidate.place.category in {"historic", "attraction", "museum", "religious"}
            for candidate in search.poi_candidates
        )
        return CostItem(
            code="admission_fees",
            label="Attraction admission fees",
            quantity=max(attractions, 1),
            price_unit="UNVERIFIED_ADMISSION",
            source="HUE_POI_SOURCE",
            price_kind="UNKNOWN",
            note="Entry fees are not verified by the current POI source and are excluded from the known total.",
        )

    @staticmethod
    def _budget_status(
        budget_vnd: int | None, known_total: int, unknown_count: int
    ) -> tuple[BudgetStatus, int | None]:
        if budget_vnd is None:
            return "UNKNOWN", None
        remaining = budget_vnd - known_total
        # Unknown costs can only increase the final total. A known subtotal that
        # already exceeds the limit is therefore conclusively over budget.
        if remaining < 0:
            return "OVER_BUDGET", remaining
        if unknown_count:
            return "UNKNOWN", remaining
        return ("WITHIN_BUDGET" if remaining >= 0 else "OVER_BUDGET"), remaining

    @staticmethod
    def _option_sort_key(option: BudgetOption) -> tuple[int, int, int]:
        status_rank = {"WITHIN_BUDGET": 0, "UNKNOWN": 1, "OVER_BUDGET": 2}
        return status_rank[option.budget_status], option.unknown_item_count, option.known_total_vnd
