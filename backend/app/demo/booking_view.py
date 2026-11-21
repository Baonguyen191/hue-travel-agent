"""Text rendering for the `book` demo: numbered steps, booking items and the explanation."""

from __future__ import annotations

from typing import Any

from app.demo.budget_view import LABEL_NAMES
from app.demo.formatting import money
from app.schemas.booking import ApprovalResult, BookingItem, BookingResult

LEG_LABELS = {"OUTBOUND": "Chuyến đi", "RETURN": "Chuyến về"}
HOTEL_LABEL = "Khách sạn"
Entries = dict[str, dict[str, Any]]


def blocked_lines(message: str) -> list[str]:
    return ["", "1. Đặt khi chưa duyệt → bị chặn (409)", f"   {message}"]


def approval_lines(approval: ApprovalResult) -> list[str]:
    label = LABEL_NAMES[approval.option]
    return [
        "",
        f"2. Duyệt phương án {label} (version {approval.version}, "
        f"quote_hash {approval.quote_hash[:12]}…)",
    ]


def forbidden_lines(message: str) -> list[str]:
    return ["", "Người khác cố đặt cùng plan → bị từ chối (403)", f"   {message}"]


def booking_lines(result: BookingResult, key: str, entries: Entries, names: dict[str, str]) -> list[str]:
    lines = ["", f"3. Đặt với khóa {key} → {result.status}"]
    for item in result.items:
        lines.extend(_item_lines(item, entries, names))
    return lines


def retry_lines(
    first: BookingResult, second: BookingResult, entries: Entries, book_calls: int
) -> list[str]:
    if not _has_unknown(first):
        return [
            "",
            f"4. Bấm lại cùng khóa → cùng intent {second.intent_id[:8]}…, "
            f"không đặt trùng (provider book calls: {book_calls})",
        ]
    lines = [
        "",
        f"4. Bấm lại cùng khóa → đối soát (get_status), không đặt lại "
        f"(provider book calls: {book_calls})",
    ]
    before = {item.offer_id: item.status for item in first.items}
    for item in second.items:
        if before.get(item.offer_id) == "UNKNOWN":
            lines.append(f"   {_offer_label(item, entries)}: UNKNOWN → {item.status}")
    lines.append(f"   Trạng thái: {first.status} → {second.status}")
    return lines


def explanation_lines(result: BookingResult) -> list[str]:
    return ["", "Giải thích:"] + [f"  - {line}" for line in result.explanation]


def _has_unknown(result: BookingResult) -> bool:
    return any(item.status == "UNKNOWN" for item in result.items)


def _item_lines(item: BookingItem, entries: Entries, names: dict[str, str]) -> list[str]:
    if item.kind == "POI":
        return _poi_lines(item, names)
    line = (
        f"  [MOCK] {_offer_label(item, entries)}, {money(item.price_vnd or 0)}  "
        f"{item.status}  mã {item.reference or '-'}  (MÔ PHỎNG)"
    )
    return [line] + ([f"      ↳ {item.message}"] if item.message else [])


def _offer_label(item: BookingItem, entries: Entries) -> str:
    entry = entries.get(item.offer_id or "", {})
    if item.kind == "HOTEL":
        return f"{HOTEL_LABEL}: {entry.get('name', item.offer_id)}"
    leg_label = LEG_LABELS.get(entry.get("leg") or "", "Chuyến")
    return f"{leg_label}: {entry.get('name', item.offer_id)}"


def _poi_lines(item: BookingItem, names: dict[str, str]) -> list[str]:
    name = names.get(item.poi_id or "", item.poi_id or "-")
    lines = [f"  [TỰ LIÊN HỆ] {name} — {item.contact_url or '-'}"]
    details: list[str] = []
    if item.contact_phone:
        details.append(f"SĐT: {item.contact_phone}")
    if item.contact_address:
        details.append(f"địa chỉ: {item.contact_address}")
    if details:
        lines.append("      " + "; ".join(details))
    return lines
