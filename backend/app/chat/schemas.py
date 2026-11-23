"""Chat reply contract: the text, typed cards, quick replies, the pending confirmation and the
understanding that produced them."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.schemas.booking import BookingResult


class UnderstandingInfo(BaseModel):
    """Which path understood the message (OLLAMA or RULES) and what the rules noted."""

    intent: str
    source: Literal["OLLAMA", "RULES"]
    notes: list[str] = Field(default_factory=list)


class PlanItem(BaseModel):
    time: str
    name: str
    kind: str
    meal: str | None = None
    poi_id: str | None = None
    slot: str | None = None
    reason: str | None = None
    intro: str | None = None


class PlanDay(BaseModel):
    date: str
    items: list[PlanItem]


class BudgetOptionView(BaseModel):
    label: str
    known_total_vnd: int
    known_total_max_vnd: int
    budget_status: str


class PlanCard(BaseModel):
    kind: Literal["plan_summary"] = "plan_summary"
    thread_id: str
    status: str
    version: int
    days: list[PlanDay]
    budget_options: list[BudgetOptionView]


class PlaceCard(BaseModel):
    kind: Literal["place"] = "place"
    poi_id: str
    name: str
    category: str
    address: str | None = None
    opening_hours_raw: str | None = None
    opening_hours_note: str = "chưa xác minh"
    price_min_vnd: int | None = None
    price_max_vnd: int | None = None
    phone: str | None = None
    source_url: str | None = None
    photo_illustrative: bool = False


class BookingCard(BaseModel):
    kind: Literal["booking"] = "booking"
    result: BookingResult


Card = Annotated[PlanCard | PlaceCard | BookingCard, Field(discriminator="kind")]


class ChatReply(BaseModel):
    """One assistant turn."""

    message_id: str = ""
    text: str
    cards: list[Card] = Field(default_factory=list)
    quick_replies: list[str] = Field(default_factory=list)
    pending_confirmation: dict[str, Any] | None = None
    understanding: UnderstandingInfo


class ChatMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
