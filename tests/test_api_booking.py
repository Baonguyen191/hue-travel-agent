"""Booking API: owner checks (A01), edits and stale approvals (O02), unknown option (422)."""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402

client: TestClient


@pytest.fixture(autouse=True, scope="module")
def _api_client() -> Iterator[None]:
    """Run the app lifespan (orchestrator and checkpointer) around this module's tests."""
    global client
    with TestClient(app) as test_client:
        client = test_client
        yield


ALICE = {"X-User-Id": "alice"}
BOB = {"X-User-Id": "bob"}
BOOK_KEY = {"idempotency_key": "api-key-00000001"}
DOD_TRIP = {
    "origin": "Hà Nội",
    "destination": "Huế",
    "start_date": "2026-12-05",
    "end_date": "2026-12-07",
    "people": 2,
    "rooms": 1,
    "budget_vnd": 6_000_000,
}


def _thread() -> str:
    return f"api-{uuid.uuid4().hex}"


def _create(thread: str, headers: dict[str, str] = ALICE) -> None:
    response = client.post(f"/api/v1/plans/{thread}", json=DOD_TRIP, headers=headers)
    assert response.status_code == 200, response.text


def _approve(thread: str, version: int, option: str = "BUDGET", headers: dict[str, str] = ALICE):
    body = {"version": version, "option": option}
    return client.post(f"/api/v1/plans/{thread}/approve", json=body, headers=headers)


def _book(thread: str, headers: dict[str, str] = ALICE):
    return client.post(f"/api/v1/plans/{thread}/book", json=BOOK_KEY, headers=headers)


def test_a01_other_user_is_refused_on_get_approve_book_and_edit() -> None:
    thread = _thread()
    _create(thread)

    assert client.get(f"/api/v1/plans/{thread}", headers=BOB).status_code == 403
    assert _approve(thread, 1, headers=BOB).status_code == 403
    assert _book(thread, headers=BOB).status_code == 403
    assert client.post(f"/api/v1/plans/{thread}", json=DOD_TRIP, headers=BOB).status_code == 403


def test_owner_approves_then_books_only_the_approved_option() -> None:
    thread = _thread()
    _create(thread)

    approval = _approve(thread, 1)
    booking = _book(thread)

    assert approval.status_code == 200, approval.text
    assert approval.json()["selected_offers"]
    assert booking.status_code == 200, booking.text
    assert booking.json()["status"] == "BOOKED"
    assert booking.json()["quote_hash"] == approval.json()["quote_hash"]


def test_o02_edit_after_approval_blocks_booking_and_stale_approval_is_409() -> None:
    thread = _thread()
    _create(thread)
    assert _approve(thread, 1).status_code == 200

    _create(thread)

    assert _book(thread).status_code == 409
    assert _approve(thread, 1).status_code == 409
    assert _approve(thread, 2).status_code == 200
    assert _book(thread).status_code == 200


def test_approving_an_option_the_plan_does_not_have_is_422() -> None:
    thread = _thread()
    _create(thread)

    response = _approve(thread, 1, option="COMFORT")

    assert response.status_code == 422


def test_missing_user_header_defaults_to_anonymous_owner() -> None:
    thread = _thread()
    client.post(f"/api/v1/plans/{thread}", json=DOD_TRIP)

    assert client.get(f"/api/v1/plans/{thread}").status_code == 200
    assert client.get(f"/api/v1/plans/{thread}", headers=ALICE).status_code == 403


def test_unknown_thread_is_404_for_get_and_book() -> None:
    thread = _thread()

    assert client.get(f"/api/v1/plans/{thread}").status_code == 404
    assert _book(thread).status_code == 404
