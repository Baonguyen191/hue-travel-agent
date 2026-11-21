"""BookingAgent guards and saga: K01-K05, approved-only booking, price change, race."""

from __future__ import annotations

import sys
import threading
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from booking_fixtures import approve, make_plan, places, selected_ids  # noqa: E402

from app.agents.booking import ApprovalRequiredError, BookingAgent  # noqa: E402
from app.db.store import PlanStore  # noqa: E402
from app.providers.booking_mock import MockBookingProvider  # noqa: E402
from app.providers.hotel_mock import MockHotelProvider  # noqa: E402
from app.providers.transport_mock import MockTransportProvider  # noqa: E402
from app.schemas.request import TripRequest  # noqa: E402
from app.services.quote_revalidator import QuoteRevalidator  # noqa: E402

THREAD = "thread-booking"
KEY = "demo-key-agent-1"


def _agent(store: PlanStore, provider: MockBookingProvider) -> BookingAgent:
    revalidator = QuoteRevalidator(MockTransportProvider(), MockHotelProvider())
    return BookingAgent(store, provider, revalidator, places=places())


def _approved(store: PlanStore) -> dict:
    plan = make_plan(store, THREAD)
    return approve(store, plan)


def _hotel_id(approval: dict) -> str:
    return next(offer["id"] for offer in approval["selected_offers"] if offer["kind"] == "HOTEL")


def test_k01_unapproved_plan_is_blocked_before_any_provider_call() -> None:
    store = PlanStore("sqlite://")
    make_plan(store, THREAD)
    provider = MockBookingProvider()

    with pytest.raises(ApprovalRequiredError):
        _agent(store, provider).book(THREAD, KEY)

    assert provider.book_calls == []
    assert store.get_intent(KEY) is None


def test_k02_timeout_is_unknown_then_reconciled_without_a_second_create() -> None:
    store = PlanStore("sqlite://")
    approval = _approved(store)
    hotel_id = _hotel_id(approval)
    provider = MockBookingProvider(modes={hotel_id: "timeout"})
    agent = _agent(store, provider)

    first = agent.book(THREAD, KEY)
    provider.reconcile[hotel_id] = "BOOKED"
    second = agent.book(THREAD, KEY)

    hotel_first = next(item for item in first.items if item.offer_id == hotel_id)
    hotel_second = next(item for item in second.items if item.offer_id == hotel_id)
    assert hotel_first.status == "UNKNOWN"
    assert first.status == "PARTIALLY_BOOKED"
    assert len(provider.book_calls) == 3
    assert provider.status_calls == [(hotel_id, first.intent_id)]
    assert hotel_second.status == "BOOKED"
    assert hotel_second.reference is not None
    assert second.status == "BOOKED"


def test_k03_same_key_twice_returns_identical_result_and_books_once() -> None:
    store = PlanStore("sqlite://")
    _approved(store)
    provider = MockBookingProvider()
    agent = _agent(store, provider)

    first = agent.book(THREAD, KEY)
    second = agent.book(THREAD, KEY)

    assert first.model_dump() == second.model_dump()
    assert len(provider.book_calls) == 3


def test_k03_two_threads_racing_one_key_make_exactly_one_set_of_book_calls(tmp_path) -> None:
    store = PlanStore(f"sqlite:///{(tmp_path / 'race.sqlite').as_posix()}")
    _approved(store)
    provider = MockBookingProvider()
    agent = _agent(store, provider)
    results: list = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        outcome = agent.book(THREAD, KEY)
        with lock:
            results.append(outcome)

    workers = [threading.Thread(target=worker) for _ in range(2)]
    for thread in workers:
        thread.start()
    for thread in workers:
        thread.join()

    assert len(provider.book_calls) == 3
    assert len(results) == 2
    assert results[0].intent_id == results[1].intent_id


def test_k04_hotel_failure_is_partially_booked_with_transport_booked() -> None:
    store = PlanStore("sqlite://")
    approval = _approved(store)
    provider = MockBookingProvider(modes={_hotel_id(approval): "fail"})

    result = _agent(store, provider).book(THREAD, KEY)

    assert result.status == "PARTIALLY_BOOKED"
    transport = [item for item in result.items if item.kind == "TRANSPORT"]
    assert transport and all(item.status == "BOOKED" for item in transport)


def test_k05_itinerary_pois_are_never_booked_and_carry_contact_details() -> None:
    store = PlanStore("sqlite://")
    approval = _approved(store)
    provider = MockBookingProvider()

    result = _agent(store, provider).book(THREAD, KEY)

    poi_items = [item for item in result.items if item.kind == "POI"]
    assert poi_items
    assert all(item.status == "NOT_SUPPORTED_BY_DATASET" for item in poi_items)
    assert all(item.contact_url and item.contact_url.startswith("https://") for item in poi_items)
    booked_ids = {offer_id for offer_id, _ in provider.book_calls}
    assert booked_ids == selected_ids(approval)


def test_only_the_approved_offers_are_booked_out_of_all_mock_offers() -> None:
    store = PlanStore("sqlite://")
    approval = _approved(store)
    provider = MockBookingProvider()

    _agent(store, provider).book(THREAD, KEY)

    assert len(approval["selected_offers"]) == 3
    assert len(provider.book_calls) == 3
    assert {offer_id for offer_id, _ in provider.book_calls} == selected_ids(approval)


def test_price_change_requires_reconfirmation_and_books_nothing() -> None:
    store = PlanStore("sqlite://")
    approval = _approved(store)
    outbound = next(offer for offer in approval["selected_offers"] if offer["leg"] == "OUTBOUND")
    provider = MockBookingProvider()
    revalidator = QuoteRevalidator(
        MockTransportProvider(price_overrides={outbound["id"]: outbound["price"] + 100_000}),
        MockHotelProvider(),
    )
    agent = BookingAgent(store, provider, revalidator, places=places())

    result = agent.book(THREAD, KEY)

    assert result.status == "RECONFIRM_REQUIRED"
    assert provider.book_calls == []
    held = next(item for item in result.items if item.offer_id == outbound["id"])
    assert held.status == "RECONFIRM_REQUIRED"
    assert f"{outbound['price']:,}" in held.message
    assert f"{outbound['price'] + 100_000:,}" in held.message


def test_other_user_is_refused_before_any_booking() -> None:
    store = PlanStore("sqlite://")
    _approved(store)
    provider = MockBookingProvider()

    with pytest.raises(PermissionError, match="owner"):
        _agent(store, provider).book(THREAD, KEY, user_id="someone-else")

    assert provider.book_calls == []


def test_new_plan_version_after_approval_blocks_booking() -> None:
    store = PlanStore("sqlite://")
    _approved(store)
    make_plan(store, THREAD, TripRequest(
        origin="Da Nang",
        destination="Hue",
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 13),
        people=2,
    ))
    provider = MockBookingProvider()

    with pytest.raises(ApprovalRequiredError):
        _agent(store, provider).book(THREAD, KEY)

    assert provider.book_calls == []
