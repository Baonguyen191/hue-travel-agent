"""Plan creation, resume and approval endpoints.

`X-User-Id` is an MVP ownership check, not authentication: any caller can send any
value. It only keeps one user's plan away from another user's plan.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.agents.orchestrator import Orchestrator
from app.agents.search import SearchAgent
from app.core.config import hue_database_path
from app.db.store import DEFAULT_OWNER, PlanStore
from app.providers.hotel_mock import MockHotelProvider
from app.providers.transport_mock import MockTransportProvider
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.booking import ApprovalRequest, ApprovalResult
from app.schemas.request import TripRequest
from app.services.budget_optimizer import BudgetAgent
from app.services.itinerary_optimizer import ItineraryAgent
from app.services.quote import UnknownOptionError, approve_option
from app.services.request_parser import TripRequestParser

router = APIRouter(prefix="/api/v1/plans", tags=["plans"])
store = PlanStore(os.environ.get("DATABASE_URL", "sqlite:///backend/data/travel_state.sqlite"))
hue_places = HuePlacesRepository(hue_database_path())
orchestrator = Orchestrator(
    SearchAgent(hue_places, MockTransportProvider(), MockHotelProvider()),
    BudgetAgent(places=hue_places),
    ItineraryAgent(places=hue_places),
    store,
)


class NaturalLanguageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def owned_plan(thread_id: str, user_id: str) -> dict[str, Any]:
    """Return the latest plan of a thread, or raise 404 when missing or 403 for another owner."""
    plan = store.latest(thread_id)
    if plan is None:
        raise HTTPException(404, "Plan thread was not found.")
    if plan["owner_id"] != user_id:
        raise HTTPException(403, "Plan belongs to another user.")
    return plan


@router.post("/parse")
def parse_request(body: NaturalLanguageRequest):
    return TripRequestParser().parse(body.text)


@router.post("/{thread_id}")
def create_or_edit(
    thread_id: str,
    request: TripRequest,
    x_user_id: str = Header(default=DEFAULT_OWNER),
):
    try:
        return asyncio.run(orchestrator.run(thread_id, request, owner_id=x_user_id))
    except PermissionError as error:
        raise HTTPException(403, str(error))


@router.get("/{thread_id}")
def resume(thread_id: str, x_user_id: str = Header(default=DEFAULT_OWNER)):
    return owned_plan(thread_id, x_user_id)


@router.post("/{thread_id}/approve", response_model=ApprovalResult)
def approve(
    thread_id: str,
    body: ApprovalRequest,
    x_user_id: str = Header(default=DEFAULT_OWNER),
):
    plan = owned_plan(thread_id, x_user_id)
    if body.version != plan["version"]:
        raise HTTPException(409, "Plan version is stale; approve the latest version.")
    try:
        return approve_option(store, plan, body.option)
    except UnknownOptionError as error:
        raise HTTPException(422, str(error))
