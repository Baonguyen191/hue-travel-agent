"""Same-day trips (start == end): search, itinerary, budget and orchestrator with no hotel night."""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
HUE_DB = BACKEND / "data" / "hue.sqlite"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.orchestrator import Orchestrator  # noqa: E402
from app.agents.search import SearchAgent  # noqa: E402
from app.db.store import PlanStore  # noqa: E402
from app.providers.hotel_mock import MockHotelProvider  # noqa: E402
from app.providers.transport_mock import MockTransportProvider  # noqa: E402
from app.repositories.hue_places import HuePlacesRepository  # noqa: E402
from app.schemas.offer import TransportSearchRequest  # noqa: E402
from app.schemas.request import TripRequest  # noqa: E402
from app.services.budget_optimizer import DAY_TRIP_WARNING, BudgetAgent  # noqa: E402
from app.services.itinerary_optimizer import ItineraryAgent  # noqa: E402

ONE_DAY_REQUEST = TripRequest(
    origin="Hà Nội",
    destination="Huế",
    start_date=date(2026, 12, 5),
    end_date=date(2026, 12, 5),
    people=2,
    rooms=1,
    budget_vnd=6_000_000,
    preferences=["di tích", "đặc sản"],
)


def _repository() -> HuePlacesRepository:
    return HuePlacesRepository(HUE_DB)


def _search_agent(hotel: MockHotelProvider | None = None) -> SearchAgent:
    return SearchAgent(_repository(), MockTransportProvider(), hotel or MockHotelProvider())


def _orchestrator(store: PlanStore) -> Orchestrator:
    repository = _repository()
    return Orchestrator(
        SearchAgent(repository, MockTransportProvider(), MockHotelProvider()),
        BudgetAgent(places=repository),
        ItineraryAgent(places=repository),
        store,
        InMemorySaver(),
    )


class _ExplodingHotelProvider(MockHotelProvider):
    """Fails the test if a same-day search ever reaches the hotel provider."""

    def search(self, request: Any) -> Any:
        raise AssertionError("hotel provider must not be called on a same-day trip")


def test_transport_return_on_the_same_day_is_allowed() -> None:
    request = TransportSearchRequest(
        origin="Hà Nội",
        destination="Huế",
        departure_date=date(2026, 12, 5),
        return_date=date(2026, 12, 5),
        passengers=2,
    )

    offers = MockTransportProvider().search(request)

    assert {offer.leg for offer in offers} == {"OUTBOUND", "RETURN"}


def test_search_skips_the_hotel_provider_and_warns_about_no_hotel() -> None:
    result = asyncio.run(_search_agent(_ExplodingHotelProvider()).search(ONE_DAY_REQUEST))

    assert result.status == "READY"
    assert result.hotel_offers == []
    assert result.transport_offers
    assert result.poi_candidates


def test_itinerary_plans_exactly_one_day_with_visits() -> None:
    search = asyncio.run(_search_agent().search(ONE_DAY_REQUEST))

    itinerary = ItineraryAgent(places=_repository()).plan(ONE_DAY_REQUEST, search)

    assert [day.date for day in itinerary.days] == [date(2026, 12, 5)]
    assert any(event.kind == "VISIT" for event in itinerary.days[0].events)
    assert itinerary.validation.valid, itinerary.validation.warnings


def test_budget_has_no_lodging_line_and_carries_the_day_trip_warning() -> None:
    search = asyncio.run(_search_agent().search(ONE_DAY_REQUEST))
    repository = _repository()
    itinerary = ItineraryAgent(places=repository).plan(ONE_DAY_REQUEST, search)

    budget = BudgetAgent(places=repository).build(
        ONE_DAY_REQUEST, search, visit_poi_ids=itinerary.poi_ids()
    )

    assert budget.options
    for option in budget.options:
        assert option.hotel is None
        assert all(item.code != "lodging" for item in option.items)
        assert DAY_TRIP_WARNING in option.warnings
    assert all("hotel" not in warning.lower() for warning in budget.warnings)


def test_revalidation_of_a_same_day_quote_does_not_call_the_hotel_provider() -> None:
    from app.services.quote_revalidator import QuoteRevalidator

    transport = MockTransportProvider().search(
        TransportSearchRequest(
            origin="Hà Nội",
            destination="Huế",
            departure_date=date(2026, 12, 5),
            return_date=date(2026, 12, 5),
            passengers=2,
        )
    )
    approved = [
        {"id": offer.id, "kind": "TRANSPORT", "leg": offer.leg, "price": offer.price_vnd}
        for offer in transport
        if offer.mode == "BUS"
    ]

    checks = QuoteRevalidator(MockTransportProvider(), _ExplodingHotelProvider()).check(
        ONE_DAY_REQUEST, approved
    )

    assert [check.status for check in checks] == ["OK", "OK"]


def test_orchestrator_waits_for_approval_on_a_one_day_trip() -> None:
    store = PlanStore("sqlite://")

    result = asyncio.run(_orchestrator(store).start("same-day-1", ONE_DAY_REQUEST, owner_id="alice"))

    assert result["status"] == "AWAITING_APPROVAL"
    assert result["waiting"] is True
    assert result["trace"] == ["search", "itinerary", "budget", "validate", "approval"]
    assert result["options"]
