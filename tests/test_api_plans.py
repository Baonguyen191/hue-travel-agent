"""Plan API on the orchestrator: checkpoint status, refused answers, rules-first parse."""

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
from app.services import request_parser  # noqa: E402

client: TestClient
ALICE = {"X-User-Id": "alice"}
BOB = {"X-User-Id": "bob"}
DOD_TRIP = {
    "origin": "Hà Nội",
    "destination": "Huế",
    "start_date": "2026-12-05",
    "end_date": "2026-12-07",
    "people": 2,
    "rooms": 1,
    "budget_vnd": 6_000_000,
}
DOD_TEXT = (
    "Tôi đi Huế 3 ngày 2 đêm, xuất phát Hà Nội, 2 người, "
    "ngân sách 6 triệu, thích di tích và đặc sản"
)


@pytest.fixture(autouse=True, scope="module")
def _api_client() -> Iterator[None]:
    global client
    with TestClient(app) as test_client:
        client = test_client
        yield


def _thread() -> str:
    return f"plans-{uuid.uuid4().hex}"


def _create(thread: str, headers: dict[str, str] = ALICE):
    return client.post(f"/api/v1/plans/{thread}", json=DOD_TRIP, headers=headers)


def _approve(thread: str, version: int, headers: dict[str, str] = ALICE):
    return client.post(
        f"/api/v1/plans/{thread}/approve",
        json={"version": version, "option": "BUDGET"},
        headers=headers,
    )


def test_create_reports_waiting_for_approval_with_a_trace() -> None:
    thread = _thread()

    response = _create(thread)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "AWAITING_APPROVAL"
    assert body["waiting"] is True
    assert body["trace"] == ["search", "itinerary", "budget", "validate", "approval"]


def test_get_plan_includes_the_checkpoint_status() -> None:
    thread = _thread()
    _create(thread)

    body = client.get(f"/api/v1/plans/{thread}", headers=ALICE).json()

    assert body["checkpoint"]["waiting"] is True
    assert body["checkpoint"]["status"] == "AWAITING_APPROVAL"


def test_second_approval_of_the_same_version_is_409_because_nothing_waits() -> None:
    thread = _thread()
    _create(thread)
    assert _approve(thread, 1).status_code == 200

    response = _approve(thread, 1)

    assert response.status_code == 409


def test_a_refused_edit_does_not_block_the_owner_from_approving() -> None:
    thread = _thread()
    _create(thread)

    refused = client.post(f"/api/v1/plans/{thread}", json=DOD_TRIP, headers=BOB)

    assert refused.status_code == 403
    assert _approve(thread, 1).status_code == 200


def test_parse_uses_rules_and_never_calls_openai_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(request_parser, "openai_api_key", lambda: None)

    response = client.post("/api/v1/plans/parse", json={"text": DOD_TEXT})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "FORM_FALLBACK"
    assert body["fields"]["destination"] == "Huế"
    assert body["fields"]["people"] == 2
    assert "start_date" in body["missing_fields"]
