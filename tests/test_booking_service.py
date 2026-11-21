from __future__ import annotations
import asyncio,sys
from datetime import date
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1];BACKEND=ROOT/"backend";sys.path.insert(0,str(BACKEND))
from app.agents.orchestrator import Orchestrator
from app.agents.search import SearchAgent
from app.db.store import PlanStore
from app.providers.booking_mock import MockBookingProvider
from app.providers.hotel_mock import MockHotelProvider
from app.providers.transport_mock import MockTransportProvider
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.request import TripRequest
from app.services.booking_service import BookingService
from app.services.budget_optimizer import BudgetAgent
from app.services.itinerary_optimizer import ItineraryAgent
def test_booking_requires_approval_and_idempotency():
 s=PlanStore("sqlite://");o=Orchestrator(SearchAgent(HuePlacesRepository(BACKEND/"data"/"hue.sqlite"),MockTransportProvider(),MockHotelProvider()),BudgetAgent(),ItineraryAgent(),s)
 r=TripRequest(origin="Da Nang",destination="Hue",start_date=date(2026,12,10),end_date=date(2026,12,12),people=2);state=asyncio.run(o.run("b",r));service=BookingService(s,MockBookingProvider())
 with pytest.raises(PermissionError): service.book("b","idempotency-1")
 s.approve(state["plan_id"]);first=service.book("b","idempotency-1");second=service.book("b","idempotency-1")
 assert first.status=="BOOKED" and first.model_dump()==second.model_dump()
