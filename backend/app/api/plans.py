"""Plan endpoints on top of the LangGraph orchestrator.

`X-User-Id` is an MVP ownership check, not authentication: any caller can send any
value. It only keeps one user's plan away from another user's plan.

The orchestrator and its checkpointer are created in the FastAPI lifespan (see
`app.main`) and stored on `app.state.orchestrator`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel, Field

from app.agents.orchestrator import NotWaitingError, Orchestrator, StalePlanError
from app.agents.search import SearchAgent
from app.core.config import database_url, hue_database_path
from app.db.store import DEFAULT_OWNER, PlanStore
from app.providers.hotel_mock import MockHotelProvider
from app.providers.transport_mock import MockTransportProvider
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.booking import ApprovalRequest, ApprovalResult
from app.schemas.request import TripRequest
from app.services.budget_optimizer import BudgetAgent
from app.services.itinerary_optimizer import ItineraryAgent
from app.services.quote import UnknownOptionError
from app.services.request_parser import TripRequestParser

router = APIRouter(prefix="/api/v1/plans", tags=["plans"])
store = PlanStore(database_url())
hue_places = HuePlacesRepository(hue_database_path())


class NaturalLanguageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def build_orchestrator(checkpointer: BaseCheckpointSaver) -> Orchestrator:
    """Wire the agents, the plan store and the given checkpointer into one orchestrator."""
    return Orchestrator(
        SearchAgent(hue_places, MockTransportProvider(), MockHotelProvider()),
        BudgetAgent(places=hue_places),
        ItineraryAgent(places=hue_places),
        store,
        checkpointer,
    )


def get_orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator


def owned_plan(thread_id: str, user_id: str) -> dict[str, Any]:
    """Return the latest plan of a thread, or raise 404 when missing or 403 for another owner."""
    plan = store.latest(thread_id)
    if plan is None:
        raise HTTPException(404, "Plan thread was not found.")
    if plan["owner_id"] != user_id:
        raise HTTPException(403, "Plan belongs to another user.")
    return plan


@router.post("/parse")
async def parse_request(body: NaturalLanguageRequest):
    """Rules first; OpenAI runs in a worker thread only to fill fields the rules missed."""
    return await asyncio.to_thread(TripRequestParser().parse, body.text)


@router.post("/{thread_id}")
async def create_or_edit(
    thread_id: str,
    request: TripRequest,
    orchestrator: Orchestrator = Depends(get_orchestrator),
    x_user_id: str = Header(default=DEFAULT_OWNER),
):
    """Start a plan, or edit the one waiting for approval (which creates the next version)."""
    try:
        current = await orchestrator.state(thread_id)
        if current is not None and current["waiting"]:
            answer = {"action": "edit", "request": request.model_dump(mode="json"), "user_id": x_user_id}
            return await orchestrator.resume(thread_id, answer)
        return await orchestrator.start(thread_id, request, owner_id=x_user_id)
    except PermissionError as error:
        raise HTTPException(403, str(error))


@router.get("/{thread_id}")
async def get_plan(
    thread_id: str,
    orchestrator: Orchestrator = Depends(get_orchestrator),
    x_user_id: str = Header(default=DEFAULT_OWNER),
):
    plan = owned_plan(thread_id, x_user_id)
    return {**plan, "checkpoint": await orchestrator.state(thread_id)}


@router.post("/{thread_id}/approve", response_model=ApprovalResult)
async def approve(
    thread_id: str,
    body: ApprovalRequest,
    orchestrator: Orchestrator = Depends(get_orchestrator),
    x_user_id: str = Header(default=DEFAULT_OWNER),
):
    plan = owned_plan(thread_id, x_user_id)
    if body.version != plan["version"]:
        raise HTTPException(409, "Plan version is stale; approve the latest version.")
    answer = {"action": "approve", "option": body.option, "user_id": x_user_id, "version": body.version}
    try:
        state = await orchestrator.resume(thread_id, answer)
    except PermissionError as error:
        raise HTTPException(403, str(error))
    except (StalePlanError, NotWaitingError) as error:
        raise HTTPException(409, str(error))
    except UnknownOptionError as error:
        raise HTTPException(422, str(error))
    return ApprovalResult.model_validate(state["approval"])
