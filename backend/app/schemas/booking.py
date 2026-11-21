"""Booking contracts: statuses, per-item results, approval payloads and quotes.

Every booking in this MVP is a mock (`source="MOCK"`). Itinerary POIs are never
booked; they appear as `NOT_SUPPORTED_BY_DATASET` items with contact details.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

BookingStatus = Literal[
    "PENDING",
    "BOOKED",
    "FAILED",
    "UNKNOWN",
    "PARTIALLY_BOOKED",
    "RECONFIRM_REQUIRED",
    "NOT_SUPPORTED_BY_DATASET",
]
BookingKind = Literal["TRANSPORT", "HOTEL", "POI"]
BookingSource = Literal["MOCK", "HUE_POI_SOURCE"]
OptionLabel = Literal["BUDGET", "BALANCED", "COMFORT"]


class BookingRequest(BaseModel):
    """Client-chosen idempotency key; the same key always returns the same intent."""

    idempotency_key: str = Field(min_length=8, max_length=200)


class BookingItem(BaseModel):
    """One line of a booking result: an offer, a POI contact, or a held item."""

    offer_id: str | None = None
    poi_id: str | None = None
    kind: BookingKind
    status: BookingStatus
    source: BookingSource
    reference: str | None = None
    price_vnd: int | None = None
    contact_url: str | None = None
    contact_address: str | None = None
    contact_phone: str | None = None
    message: str | None = None


class BookingResult(BaseModel):
    """The stored outcome of one idempotency key, bound to one approval."""

    intent_id: str
    status: BookingStatus
    items: list[BookingItem]
    plan_version: int
    approval_id: str
    quote_hash: str
    explanation: list[str] = Field(default_factory=list)
    source: Literal["MOCK"] = "MOCK"


class ApprovalRequest(BaseModel):
    """Approve one budget option of one plan version."""

    version: int = Field(ge=1)
    option: OptionLabel


class ApprovalResult(BaseModel):
    """The approved option, its quote hash and the exact offers it covers."""

    approval_id: str
    plan_id: str
    version: int
    option: OptionLabel
    quote_hash: str
    selected_offers: list[dict[str, Any]]
    status: Literal["APPROVED"] = "APPROVED"
