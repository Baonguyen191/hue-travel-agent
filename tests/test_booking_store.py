"""Plan, approval and booking-intent persistence."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.store import PlanStore  # noqa: E402


def _draft(intent_id: str, key_status: str = "PENDING") -> dict:
    return {"intent_id": intent_id, "status": key_status, "items": []}


def test_save_plan_increments_version_for_same_owner() -> None:
    store = PlanStore("sqlite://")

    _, first = store.save_plan("thread-a", {"n": 1}, owner_id="alice")
    _, second = store.save_plan("thread-a", {"n": 2}, owner_id="alice")

    assert (first, second) == (1, 2)
    assert store.latest("thread-a")["owner_id"] == "alice"


def test_save_plan_rejects_a_different_owner_on_the_same_thread() -> None:
    store = PlanStore("sqlite://")
    store.save_plan("thread-b", {"n": 1}, owner_id="alice")

    with pytest.raises(PermissionError):
        store.save_plan("thread-b", {"n": 2}, owner_id="bob")


def test_approve_stores_option_quote_and_selected_offers() -> None:
    store = PlanStore("sqlite://")
    plan_id, _ = store.save_plan("thread-c", {"n": 1})
    selected = [{"kind": "HOTEL", "id": "mock-hotel-homestay", "price": 350000}]

    approval_id = store.approve(plan_id, "BUDGET", "abc123", selected)
    active = store.active_approval(plan_id)

    assert active["approval_id"] == approval_id
    assert active["option"] == "BUDGET"
    assert active["quote_hash"] == "abc123"
    assert active["selected_offers"] == selected


def test_second_approval_of_same_plan_deactivates_the_first() -> None:
    store = PlanStore("sqlite://")
    plan_id, _ = store.save_plan("thread-d", {"n": 1})
    store.approve(plan_id, "BUDGET", "h1", [])
    second_id = store.approve(plan_id, "BUDGET", "h2", [])

    assert store.active_approval(plan_id)["approval_id"] == second_id


def test_new_plan_version_invalidates_approval_of_older_version() -> None:
    store = PlanStore("sqlite://")
    old_plan, _ = store.save_plan("thread-e", {"n": 1})
    store.approve(old_plan, "BUDGET", "h1", [])

    new_plan, _ = store.save_plan("thread-e", {"n": 2})

    assert store.active_approval(old_plan) is None
    assert store.active_approval(new_plan) is None


def test_claim_intent_first_caller_wins_and_second_gets_stored_row() -> None:
    store = PlanStore("sqlite://")
    store.save_plan("thread-f", {"n": 1})
    trip_id = store.latest("thread-f")["trip_id"]

    first, first_is_new = store.claim_intent("key-00000001", trip_id, _draft("intent-1"))
    second, second_is_new = store.claim_intent("key-00000001", trip_id, _draft("intent-2"))

    assert first_is_new is True
    assert second_is_new is False
    assert first["intent_id"] == "intent-1"
    assert second["intent_id"] == "intent-1"
    assert store.get_intent("key-00000001")["intent_id"] == "intent-1"


def test_get_intent_returns_none_when_key_was_never_claimed() -> None:
    store = PlanStore("sqlite://")

    assert store.get_intent("never-used-key") is None


def test_update_intent_rewrites_status_and_payload() -> None:
    store = PlanStore("sqlite://")
    store.save_plan("thread-g", {"n": 1})
    trip_id = store.latest("thread-g")["trip_id"]
    store.claim_intent("key-00000002", trip_id, _draft("intent-3"))

    store.update_intent("key-00000002", _draft("intent-3", key_status="BOOKED"))

    stored = store.get_intent("key-00000002")
    assert stored["status"] == "BOOKED"


def test_concurrent_claims_on_a_file_database_have_exactly_one_winner(tmp_path: Path) -> None:
    store = PlanStore(f"sqlite:///{(tmp_path / 'race.sqlite').as_posix()}")
    store.save_plan("thread-race", {"n": 1})
    trip_id = store.latest("thread-race")["trip_id"]
    outcomes: list[tuple[dict, bool]] = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def claim(index: int) -> None:
        barrier.wait()
        outcome = store.claim_intent("race-key-00001", trip_id, _draft(f"intent-{index}"))
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=claim, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    winners = [stored for stored, is_new in outcomes if is_new]
    assert len(winners) == 1
    assert {stored["intent_id"] for stored, _ in outcomes} == {winners[0]["intent_id"]}
