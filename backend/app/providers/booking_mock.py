"""Deterministic mock booking provider. It never makes a real reservation.

`book` creates a mock booking per call and records it; `get_status` only reads
the configured reconcile answer and never books anything.
"""

from __future__ import annotations

from typing import Literal

from app.schemas.booking import BookingItem, BookingKind

Mode = Literal["success", "fail", "timeout"]
ReconcileStatus = Literal["BOOKED", "FAILED", "UNKNOWN"]

TIMEOUT_MESSAGE = "Provider timed out; status will be reconciled."
FAILED_MESSAGE = "Provider did not confirm the booking."
STILL_UNKNOWN_MESSAGE = "Provider has not confirmed the booking yet."


class MockBookingProvider:
    """Scripted per-offer outcomes; `book_calls` records every create attempt."""

    def __init__(
        self,
        modes: dict[str, Mode] | None = None,
        reconcile: dict[str, ReconcileStatus] | None = None,
    ) -> None:
        self.modes: dict[str, Mode] = dict(modes or {})
        self.reconcile: dict[str, ReconcileStatus] = dict(reconcile or {})
        self.book_calls: list[tuple[str, str]] = []
        self.status_calls: list[tuple[str, str]] = []

    def book(self, offer_id: str, kind: BookingKind, intent_id: str) -> BookingItem:
        self.book_calls.append((offer_id, intent_id))
        mode = self.modes.get(offer_id, "success")
        if mode == "success":
            return _item(offer_id, kind, "BOOKED", intent_id)
        if mode == "fail":
            return _item(offer_id, kind, "FAILED", intent_id, FAILED_MESSAGE)
        return _item(offer_id, kind, "UNKNOWN", intent_id, TIMEOUT_MESSAGE)

    def get_status(self, offer_id: str, intent_id: str, kind: BookingKind) -> BookingItem:
        self.status_calls.append((offer_id, intent_id))
        status = self.reconcile.get(offer_id, "UNKNOWN")
        message = STILL_UNKNOWN_MESSAGE if status == "UNKNOWN" else None
        return _item(offer_id, kind, status, intent_id, message)


def _item(
    offer_id: str,
    kind: BookingKind,
    status: ReconcileStatus,
    intent_id: str,
    message: str | None = None,
) -> BookingItem:
    reference = f"MOCK-{intent_id[:8]}-{offer_id}" if status == "BOOKED" else None
    return BookingItem(
        offer_id=offer_id,
        kind=kind,
        status=status,
        source="MOCK",
        reference=reference,
        message=message,
    )
