"""Approval-bound booking saga: guards, idempotency, revalidation and reconciliation.

Guard order (plan section 9.2):
1. The plan exists and belongs to the caller (LookupError -> 404, PermissionError -> 403).
2. The latest plan version has an active approval (ApprovalRequiredError -> 409).
3. The idempotency key is claimed. An existing key returns its stored result; only
   UNKNOWN items are reconciled with `get_status`, never created again.
4. Approved offers are revalidated. Any price change holds the whole booking.
5. Saga: outbound, return, then hotel, and only the approved offers.
6. Itinerary POIs are listed with contact details and are never booked.
7. Overall status comes from transport and hotel items only. No automatic cancellation.
8. The trip status and the stored result are updated.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.db.store import DEFAULT_OWNER, PlanStore
from app.providers.base import BookingProvider
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.booking import BookingItem, BookingResult, BookingStatus
from app.schemas.itinerary import ItineraryResult
from app.schemas.place import Place
from app.schemas.request import TripRequest
from app.services.quote_revalidator import OfferCheck, QuoteRevalidator

PHONE_KEY = "Điện thoại"
POI_MESSAGE = "Đặt trực tiếp với cơ sở; hệ thống không đặt chỗ này."
HELD_MESSAGE = "Chưa đặt: cần xác nhận lại giá trước."
_STATUS_TEXT: dict[str, str] = {
    "BOOKED": "Tất cả dịch vụ đã đặt.",
    "PARTIALLY_BOOKED": "Chỉ một phần dịch vụ được đặt; các mục còn lại cần xử lý.",
    "UNKNOWN": "Nhà cung cấp chưa xác nhận; bấm lại cùng khóa để đối soát.",
    "FAILED": "Không có dịch vụ nào được đặt.",
    "RECONFIRM_REQUIRED": "Giá hoặc tình trạng đã đổi; chưa đặt gì. Hãy duyệt lại với khóa mới.",
}


class ApprovalRequiredError(PermissionError):
    """The latest plan version has no active approval."""


class BookingAgent:
    """Books exactly the approved offers, at most once per idempotency key."""

    def __init__(
        self,
        store: PlanStore,
        provider: BookingProvider,
        revalidator: QuoteRevalidator,
        places: HuePlacesRepository | None = None,
    ) -> None:
        self.store = store
        self.provider = provider
        self.revalidator = revalidator
        self.places = places

    def book(
        self, thread_id: str, idempotency_key: str, user_id: str = DEFAULT_OWNER
    ) -> BookingResult:
        plan = self._owned_plan(thread_id, user_id)
        approval = self._require_approval(plan["plan_id"])
        draft = _draft(plan, approval)
        stored, is_new = self.store.claim_intent(
            idempotency_key, plan["trip_id"], draft.model_dump(mode="json")
        )
        if not is_new:
            return self._resume(BookingResult.model_validate(stored), idempotency_key, plan["trip_id"])
        result = self._run_saga(plan, approval, draft)
        self._persist(idempotency_key, plan["trip_id"], result)
        return result

    def _owned_plan(self, thread_id: str, user_id: str) -> dict[str, Any]:
        plan = self.store.latest(thread_id)
        if plan is None:
            raise LookupError("Plan thread was not found.")
        if plan["owner_id"] != user_id:
            raise PermissionError("owner: plan belongs to another user")
        return plan

    def _require_approval(self, plan_id: str) -> dict[str, Any]:
        approval = self.store.active_approval(plan_id)
        if approval is None:
            raise ApprovalRequiredError("Current plan version has not been approved.")
        return approval

    def _run_saga(
        self, plan: dict[str, Any], approval: dict[str, Any], draft: BookingResult
    ) -> BookingResult:
        request = TripRequest.model_validate(plan["payload"]["request"])
        checks = self.revalidator.check(request, approval["selected_offers"])
        items = self._core_items(checks, draft.intent_id)
        items.extend(self._poi_items(plan["payload"]["itinerary"]))
        return _with_items(draft, items)

    def _core_items(self, checks: list[OfferCheck], intent_id: str) -> list[BookingItem]:
        if any(check.status == "RECONFIRM_REQUIRED" for check in checks):
            return [_held_item(check) for check in checks]
        return [self._book_item(check, intent_id) for check in checks]

    def _book_item(self, check: OfferCheck, intent_id: str) -> BookingItem:
        if check.status == "FAILED":
            return _core_item(check, "FAILED", check.message)
        item = self.provider.book(check.offer["id"], check.offer["kind"], intent_id)
        return item.model_copy(update={"price_vnd": check.offer["price"]})

    def _poi_items(self, itinerary_payload: dict[str, Any]) -> list[BookingItem]:
        itinerary = ItineraryResult.model_validate(itinerary_payload)
        return [self._poi_item(poi_id) for poi_id in itinerary.poi_ids()]

    def _poi_item(self, poi_id: str) -> BookingItem:
        place = self.places.get_by_id(poi_id) if self.places is not None else None
        return BookingItem(
            poi_id=poi_id,
            kind="POI",
            status="NOT_SUPPORTED_BY_DATASET",
            source="HUE_POI_SOURCE",
            contact_url=place.source_url if place is not None else None,
            contact_address=place.address if place is not None else None,
            contact_phone=_phone(place),
            message=POI_MESSAGE,
        )

    def _resume(self, result: BookingResult, idempotency_key: str, trip_id: str) -> BookingResult:
        """Return a stored result unchanged, unless it still has UNKNOWN items."""
        if not _has_unknown(result):
            return result
        items = [
            self._reconciled(item, result.intent_id) if item.status == "UNKNOWN" else item
            for item in result.items
        ]
        updated = _with_items(result, items)
        self._persist(idempotency_key, trip_id, updated)
        return updated

    def _reconciled(self, item: BookingItem, intent_id: str) -> BookingItem:
        status_item = self.provider.get_status(item.offer_id or "", intent_id, item.kind)
        return status_item.model_copy(update={"price_vnd": item.price_vnd})

    def _persist(self, idempotency_key: str, trip_id: str, result: BookingResult) -> None:
        self.store.update_intent(idempotency_key, result.model_dump(mode="json"))
        self.store.set_trip_status(trip_id, result.status)


def poi_names(itinerary: ItineraryResult) -> dict[str, str]:
    """Map each VISIT or MEAL poi_id to the name shown in the itinerary."""
    names: dict[str, str] = {}
    for day in itinerary.days:
        for event in day.events:
            if event.kind in ("VISIT", "MEAL") and event.poi_id is not None:
                names.setdefault(event.poi_id, event.name)
    return names


def overall_status(items: list[BookingItem]) -> BookingStatus:
    """Derive the status from transport and hotel items only (POIs never count)."""
    if any(item.status == "RECONFIRM_REQUIRED" for item in items):
        return "RECONFIRM_REQUIRED"
    core = {item.status for item in items if item.kind != "POI"}
    if not core:
        return "FAILED"
    if core == {"BOOKED"}:
        return "BOOKED"
    if "BOOKED" in core:
        return "PARTIALLY_BOOKED"
    if "UNKNOWN" in core:
        return "UNKNOWN"
    return "FAILED"


def _draft(plan: dict[str, Any], approval: dict[str, Any]) -> BookingResult:
    return BookingResult(
        intent_id=str(uuid.uuid4()),
        status="PENDING",
        items=[],
        plan_version=plan["version"],
        approval_id=approval["approval_id"],
        quote_hash=approval["quote_hash"],
    )


def _with_items(result: BookingResult, items: list[BookingItem]) -> BookingResult:
    status = overall_status(items)
    return result.model_copy(
        update={
            "items": items,
            "status": status,
            "explanation": _explain(status, result.plan_version, result.quote_hash),
        }
    )


def _has_unknown(result: BookingResult) -> bool:
    return result.status == "UNKNOWN" or any(item.status == "UNKNOWN" for item in result.items)


def _core_item(check: OfferCheck, status: BookingStatus, message: str | None) -> BookingItem:
    return BookingItem(
        offer_id=check.offer["id"],
        kind=check.offer["kind"],
        status=status,
        source="MOCK",
        price_vnd=check.offer["price"],
        message=message,
    )


def _held_item(check: OfferCheck) -> BookingItem:
    if check.status == "RECONFIRM_REQUIRED":
        return _core_item(check, "RECONFIRM_REQUIRED", check.message)
    if check.status == "FAILED":
        return _core_item(check, "FAILED", check.message)
    return _core_item(check, "PENDING", HELD_MESSAGE)


def _phone(place: Place | None) -> str | None:
    if place is None:
        return None
    value = place.raw_attributes.get(PHONE_KEY)
    return str(value) if value else None


def _explain(status: str, plan_version: int, quote_hash: str) -> list[str]:
    return [
        f"Chỉ đặt dịch vụ trong phương án đã duyệt (version {plan_version}, quote {quote_hash[:12]}).",
        "Vé xe và khách sạn là đặt chỗ MÔ PHỎNG (MOCK); không có giao dịch thật.",
        "Điểm tham quan và quán ăn không đặt qua hệ thống; dùng thông tin liên hệ để tự đặt.",
        _STATUS_TEXT[status],
        "Hủy hoặc hoàn tiền theo chính sách của nhà cung cấp; hệ thống không tự hủy.",
    ]
