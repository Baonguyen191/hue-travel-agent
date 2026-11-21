from __future__ import annotations
import asyncio, sys
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; BACKEND=ROOT/"backend"; sys.path.insert(0,str(BACKEND))
from app.agents.orchestrator import Orchestrator
from app.agents.search import SearchAgent
from app.db.store import PlanStore
from app.providers.hotel_mock import MockHotelProvider
from app.providers.transport_mock import MockTransportProvider
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.request import TripRequest
from app.services.budget_optimizer import BudgetAgent
from app.services.itinerary_optimizer import ItineraryAgent

def test_workflow_persists_awaiting_approval_and_versions():
 o=Orchestrator(SearchAgent(HuePlacesRepository(BACKEND/"data"/"hue.sqlite"),MockTransportProvider(),MockHotelProvider()),BudgetAgent(),ItineraryAgent(),PlanStore("sqlite://"))
 r=TripRequest(origin="Da Nang",destination="Hue",start_date=date(2026,12,10),end_date=date(2026,12,12),people=2)
 first=asyncio.run(o.run("thread-1",r)); second=asyncio.run(o.run("thread-1",r))
 assert first["status"]=="AWAITING_APPROVAL" and first["version"]==1
 assert second["version"]==2 and first["plan_id"]!=second["plan_id"]
