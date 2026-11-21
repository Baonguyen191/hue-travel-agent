"""Booking contracts: status vocabulary and request validation."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.schemas.booking import (  # noqa: E402
    ApprovalRequest,
    BookingItem,
    BookingRequest,
    BookingStatus,
)


def test_booking_status_vocabulary_matches_spec() -> None:
    assert set(get_args(BookingStatus)) == {
        "PENDING",
        "BOOKED",
        "FAILED",
        "UNKNOWN",
        "PARTIALLY_BOOKED",
        "RECONFIRM_REQUIRED",
        "NOT_SUPPORTED_BY_DATASET",
    }


def test_poi_item_carries_contact_fields_and_no_offer() -> None:
    item = BookingItem(
        poi_id="huetripo:039509",
        kind="POI",
        status="NOT_SUPPORTED_BY_DATASET",
        source="HUE_POI_SOURCE",
        contact_url="https://huetripo.hue.gov.vn/diem-tham-quan/di-tich/dai-cung-mon-039509",
    )

    assert item.offer_id is None
    assert item.contact_phone is None


def test_booking_request_enforces_idempotency_key_length() -> None:
    with pytest.raises(ValidationError):
        BookingRequest(idempotency_key="short")

    assert BookingRequest(idempotency_key="x" * 8).idempotency_key == "x" * 8


def test_approval_request_rejects_unknown_option() -> None:
    with pytest.raises(ValidationError):
        ApprovalRequest(version=1, option="VIP")
