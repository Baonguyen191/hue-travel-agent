"""Phase 7 plan creation, resume and approval endpoints."""
from __future__ import annotations
import asyncio
import os
from fastapi import APIRouter, HTTPException
from app.agents.orchestrator import Orchestrator
from app.agents.search import SearchAgent
from app.core.config import hue_database_path
from app.db.store import PlanStore
from app.providers.hotel_mock import MockHotelProvider
from app.providers.transport_mock import MockTransportProvider
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.request import TripRequest
from app.services.budget_optimizer import BudgetAgent
from app.services.itinerary_optimizer import ItineraryAgent
from app.services.request_parser import TripRequestParser
from pydantic import BaseModel, Field

router=APIRouter(prefix="/api/v1/plans",tags=["plans"])
store=PlanStore(os.environ.get("DATABASE_URL", "sqlite:///backend/data/travel_state.sqlite"))
orchestrator=Orchestrator(SearchAgent(HuePlacesRepository(hue_database_path()),MockTransportProvider(),MockHotelProvider()),BudgetAgent(),ItineraryAgent(),store)
class NaturalLanguageRequest(BaseModel): text:str=Field(min_length=1,max_length=4000)
@router.post("/parse")
def parse_request(body:NaturalLanguageRequest): return TripRequestParser().parse(body.text)
@router.post("/{thread_id}")
def create_or_edit(thread_id:str,request:TripRequest): return asyncio.run(orchestrator.run(thread_id,request))
@router.get("/{thread_id}")
def resume(thread_id:str):
    plan=store.latest(thread_id)
    if not plan: raise HTTPException(404,"Plan thread was not found.")
    return plan
@router.post("/{thread_id}/approve")
def approve(thread_id:str):
    plan=store.latest(thread_id)
    if not plan: raise HTTPException(404,"Plan thread was not found.")
    store.approve(plan["plan_id"])
    return {"status":"APPROVED","plan_id":plan["plan_id"],"version":plan["version"]}
