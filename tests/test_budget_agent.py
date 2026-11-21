"""PHASE 5 deterministic Budget Agent tests."""

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
from app.services.budget_optimizer import BudgetAgent, BudgetConfig  # noqa: E402


def _request(budget_vnd: int | None = 4_000_000) -> TripRequest:
    return TripRequest(
        origin="Đà Nẵng", destination="Huế", start_date=date(2026, 12, 10), end_date=date(2026, 12, 12),
        people=2, rooms=1, budget_vnd=budget_vnd, categories=["historic"], keyword="dai noi"
    )


def _search(transport_mode: str = "normal", hotel_mode: str = "normal"):
    agent = SearchAgent(HuePlacesRepository(BACKEND / "data" / "hue.sqlite"), MockTransportProvider(transport_mode), MockHotelProvider(hotel_mode))  # type: ignore[arg-type]
    return asyncio.run(agent.search(_request()))


def test_budget_uses_correct_units_for_two_legs_two_people_and_two_nights() -> None:
    result = BudgetAgent(BudgetConfig(food_per_person_per_day_vnd=200_000)).build(_request(), _search())
    option = result.options[0]
    amounts = {item.code: item.amount_vnd for item in option.items}

    assert amounts["transport_outbound"] == 560_000
    assert amounts["transport_return"] == 560_000
    assert amounts["lodging"] == 1_300_000
    assert amounts["food_estimate"] == 800_000
    assert option.known_total_vnd == 3_220_000
    assert option.budget_status == "UNKNOWN"  # admission fees remain unverified
    assert option.unknown_item_count == 1


def test_missing_provider_prices_are_unknown_not_zero() -> None:
    result = BudgetAgent().build(_request(), _search("empty", "empty"))
    option = result.options[0]
    amounts = {item.code: item.amount_vnd for item in option.items}

    assert amounts["transport_outbound"] is None
    assert amounts["transport_return"] is None
    assert amounts["lodging"] is None
    assert option.known_total_vnd == 800_000
    assert option.unknown_item_count == 4
    assert any("unknown" in warning.lower() for warning in result.warnings)


def test_budget_is_repeatable_and_can_omit_food_assumption() -> None:
    agent = BudgetAgent(BudgetConfig(food_per_person_per_day_vnd=None))
    search = _search()
    first = agent.build(_request(), search)
    second = agent.build(_request(), search)

    assert first.model_dump() == second.model_dump()
    assert next(item for item in first.options[0].items if item.code == "food_estimate").amount_vnd is None


def test_known_subtotal_over_budget_is_reported_even_with_unknown_admission_fees() -> None:
    result = BudgetAgent().build(_request(budget_vnd=2_000_000), _search())
    option = result.options[0]

    assert option.budget_status == "OVER_BUDGET"
    assert option.budget_remaining_vnd == -1_220_000
