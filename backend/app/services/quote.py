"""Approval quotes: the offers covered by one budget option, and a hash that binds them.

The quote hash covers the selected offers (kind, leg, id, price, unit, dates) and the
plan version, so an approval cannot silently cover a different price or version.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.db.store import PlanStore
from app.schemas.booking import ApprovalResult

_HASHED_FIELDS = ("kind", "leg", "id", "price", "unit", "dates")


class UnknownOptionError(ValueError):
    """The plan's budget has no option with the requested label."""


def build_selected_offers(budget: dict[str, Any], label: str) -> list[dict[str, Any]]:
    """Return the outbound, return and hotel offers of the labelled budget option."""
    option = _find_option(budget, label)
    selected: list[dict[str, Any]] = []
    if option.get("transport_outbound"):
        selected.append(_transport_entry(option["transport_outbound"]))
    if option.get("transport_return"):
        selected.append(_transport_entry(option["transport_return"]))
    if option.get("hotel"):
        selected.append(_hotel_entry(option["hotel"]))
    return selected


def quote_hash(selected_offers: list[dict[str, Any]], version: int) -> str:
    """Stable SHA-256 over the hashed fields of each offer plus the plan version."""
    offers = [{field: offer[field] for field in _HASHED_FIELDS} for offer in selected_offers]
    canonical = json.dumps(
        {"version": version, "offers": offers},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def approve_option(store: PlanStore, plan: dict[str, Any], label: str) -> ApprovalResult:
    """Approve one budget option of the latest plan version and persist its quote."""
    selected = build_selected_offers(plan["payload"]["budget"], label)
    digest = quote_hash(selected, plan["version"])
    approval_id = store.approve(plan["plan_id"], label, digest, selected)
    return ApprovalResult(
        approval_id=approval_id,
        plan_id=plan["plan_id"],
        version=plan["version"],
        option=label,
        quote_hash=digest,
        selected_offers=selected,
    )


def _find_option(budget: dict[str, Any], label: str) -> dict[str, Any]:
    for option in budget.get("options", []):
        if option.get("label") == label:
            return option
    raise UnknownOptionError(f"Plan has no budget option labelled {label}.")


def _transport_entry(offer: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "TRANSPORT",
        "leg": offer["leg"],
        "id": offer["id"],
        "name": offer["provider"],
        "price": offer["price_vnd"],
        "unit": offer["price_unit"],
        "dates": offer["departure_date"],
    }


def _hotel_entry(offer: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "HOTEL",
        "leg": None,
        "id": offer["id"],
        "name": offer["hotel_name"],
        "price": offer["price_per_room_night_vnd"],
        "unit": offer["price_unit"],
        "dates": f"{offer['check_in']}..{offer['check_out']}",
    }
