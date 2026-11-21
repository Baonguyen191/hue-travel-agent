"""Approval quotes: selected offers for one option, and a hash that binds them to a version."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from booking_fixtures import DEFAULT_REQUEST, make_plan  # noqa: E402

from app.db.store import PlanStore  # noqa: E402
from app.services.quote import UnknownOptionError, build_selected_offers, quote_hash  # noqa: E402


def _budget_with_one_option(price: int = 400_000) -> dict:
    outbound = {
        "id": "mock-transport-outbound-standard",
        "provider": "Hue Sleeper Bus Demo",
        "leg": "OUTBOUND",
        "price_vnd": price,
        "price_unit": "VND_PER_PERSON_PER_LEG",
        "departure_date": "2026-12-10",
    }
    hotel = {
        "id": "mock-hotel-homestay",
        "hotel_name": "Old Quarter Homestay Demo",
        "price_per_room_night_vnd": 350_000,
        "price_unit": "VND_PER_ROOM_PER_NIGHT",
        "check_in": "2026-12-10",
        "check_out": "2026-12-12",
    }
    return {
        "options": [
            {
                "label": "BUDGET",
                "transport_outbound": outbound,
                "transport_return": None,
                "hotel": hotel,
            }
        ]
    }


def test_selected_offers_list_each_present_leg_and_the_hotel() -> None:
    selected = build_selected_offers(_budget_with_one_option(), "BUDGET")

    assert [offer["kind"] for offer in selected] == ["TRANSPORT", "HOTEL"]
    assert selected[0]["price"] == 400_000
    assert selected[1]["dates"] == "2026-12-10..2026-12-12"


def test_unknown_label_raises_unknown_option_error() -> None:
    with pytest.raises(UnknownOptionError):
        build_selected_offers(_budget_with_one_option(), "COMFORT")


def test_quote_hash_is_stable_for_the_same_offers_and_version() -> None:
    selected = build_selected_offers(_budget_with_one_option(), "BUDGET")

    assert quote_hash(selected, 1) == quote_hash(selected, 1)


def test_quote_hash_changes_when_a_price_changes() -> None:
    original = build_selected_offers(_budget_with_one_option(400_000), "BUDGET")
    changed = build_selected_offers(_budget_with_one_option(450_000), "BUDGET")

    assert quote_hash(original, 1) != quote_hash(changed, 1)


def test_quote_hash_changes_with_plan_version() -> None:
    selected = build_selected_offers(_budget_with_one_option(), "BUDGET")

    assert quote_hash(selected, 1) != quote_hash(selected, 2)


def test_real_plan_budget_exposes_the_budget_option_with_three_offers() -> None:
    store = PlanStore("sqlite://")
    plan = make_plan(store, "thread-quote", DEFAULT_REQUEST)

    selected = build_selected_offers(plan["payload"]["budget"], "BUDGET")

    assert len(selected) == 3
