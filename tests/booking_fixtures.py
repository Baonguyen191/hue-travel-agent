"""Shared helpers for booking tests: build a real plan through the Orchestrator, then approve it.

Pytest puts this folder on sys.path, so test modules import it as `booking_fixtures`.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.orchestrator import Orchestrator  # noqa: E402
from app.agents.search import SearchAgent  # noqa: E402
from app.db.store import PlanStore  # noqa: E402
from app.providers.hotel_mock import MockHotelProvider  # noqa: E402
from app.providers.transport_mock import MockTransportProvider  # noqa: E402
from app.repositories.hue_places import HuePlacesRepository  # noqa: E402
from app.schemas.request import TripRequest  # noqa: E402
from app.services.budget_optimizer import BudgetAgent  # noqa: E402
from app.services.itinerary_optimizer import ItineraryAgent  # noqa: E402
from app.services.quote import approve_option  # noqa: E402

HUE_DB = BACKEND / "data" / "hue.sqlite"
DEFAULT_REQUEST = TripRequest(
    origin="Da Nang",
    destination="Hue",
    start_date=date(2026, 12, 10),
    end_date=date(2026, 12, 12),
    people=2,
)


def places() -> HuePlacesRepository:
    return HuePlacesRepository(HUE_DB)


def make_plan(
    store: PlanStore,
    thread_id: str = "thread-booking",
    request: TripRequest = DEFAULT_REQUEST,
) -> dict[str, Any]:
    """Run search, budget and itinerary through the real Orchestrator and return the latest plan."""
    repository = places()
    orchestrator = Orchestrator(
        SearchAgent(repository, MockTransportProvider(), MockHotelProvider()),
        BudgetAgent(places=repository),
        ItineraryAgent(places=repository),
        store,
    )
    asyncio.run(orchestrator.run(thread_id, request))
    plan = store.latest(thread_id)
    assert plan is not None
    return plan


def approve(store: PlanStore, plan: dict[str, Any], label: str = "BUDGET") -> dict[str, Any]:
    return approve_option(store, plan, label).model_dump()


def selected_ids(approval: dict[str, Any]) -> set[str]:
    return {offer["id"] for offer in approval["selected_offers"]}
