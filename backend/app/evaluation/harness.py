"""A chat service for evaluation: in-memory stores, mock providers, tool spies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from app.agents.booking import BookingAgent
from app.agents.orchestrator import Orchestrator
from app.agents.search import SearchAgent
from app.chat import texts
from app.chat.draft import next_questions
from app.chat.schemas import BookingCard, ChatReply, PlanCard
from app.chat.service import ChatService
from app.chat.store import ChatStore
from app.core.config import hue_database_path
from app.db.store import PlanStore
from app.evaluation.spies import CallLog, spy_method
from app.providers.booking_mock import MockBookingProvider
from app.providers.hotel_mock import MockHotelProvider
from app.providers.transport_mock import MockTransportProvider
from app.repositories.hue_places import HuePlacesRepository
from app.services.budget_optimizer import BudgetAgent
from app.services.itinerary_optimizer import ItineraryAgent
from app.services.quote_revalidator import QuoteRevalidator

USER = "eval-user"


@dataclass
class EvalHarness:
    """One isolated chat service plus the handles the runner reads afterwards."""

    service: ChatService
    store: PlanStore
    chats: ChatStore
    repo: HuePlacesRepository
    log: CallLog


def build_harness(understand_fn: Callable[..., Any], rag: Any | None) -> EvalHarness:
    """A fresh in-memory chat service; providers and `rag.answer` record into `log`."""
    store = PlanStore("sqlite://")
    repo = HuePlacesRepository(hue_database_path())
    log = CallLog()
    transport, hotel, booking_provider = MockTransportProvider(), MockHotelProvider(), MockBookingProvider()
    spy_method(transport, "search", "transport", log)
    spy_method(hotel, "search", "hotel", log)
    spy_method(booking_provider, "book", "booking", log)
    if rag is not None:
        spy_method(rag, "answer", "rag", log)
    orchestrator = Orchestrator(
        SearchAgent(repo, transport, hotel),
        BudgetAgent(places=repo),
        ItineraryAgent(places=repo),
        store,
        InMemorySaver(),
    )
    booking = BookingAgent(store, booking_provider, QuoteRevalidator(transport, hotel), places=repo)
    chats = ChatStore(store.engine)
    service = ChatService(understand_fn, orchestrator, store, booking, repo, chats, rag=rag)
    service.handler_log = []
    return EvalHarness(service=service, store=store, chats=chats, repo=repo, log=log)


def final_state(handler: str, reply: ChatReply, h: EvalHarness, conversation_id: str) -> str:
    """The scenario outcome after its last turn; the first matching rule wins."""
    if any(isinstance(card, BookingCard) for card in reply.cards):
        return "booked"
    if handler == "run_approve":
        thread_id = h.chats.context(conversation_id).thread_id
        plan = h.store.latest(thread_id) if thread_id else None
        if plan is not None and h.store.active_approval(plan["plan_id"]) is not None:
            return "approved"
    if any(isinstance(card, PlanCard) for card in reply.cards):
        return "awaiting_approval"
    if handler == "place_info":
        rag = h.service.last_rag
        if (rag is not None and not rag.answerable) or reply.text == texts.PLACE_MISSING:
            return "refused"
        return "answered"
    if handler == "out_of_scope":
        return "refused"
    if handler == "smalltalk":
        return "answered"
    if handler == "guide":
        return "answered"
    if handler == "cancel":
        return "cancelled"
    pending = reply.pending_confirmation or {}
    if pending.get("kind") in {"approve", "book", "confirm_trip"}:
        return "confirming"
    if handler == "plan_new":
        # A turn that asks the open slots carries no buttons; the question text is recomputed from the draft.
        # The one-time budget note is in the turn only before it is marked noted, so both forms count.
        draft = h.chats.context(conversation_id).draft
        if reply.text in {next_questions(draft), next_questions({**draft, "precheck_noted": False})}:
            return "clarifying"
    return "failed"
