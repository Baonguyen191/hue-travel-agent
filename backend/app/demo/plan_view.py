"""`plan` demo: Vietnamese sentence -> rules parse -> LangGraph run -> approval -> booking.

The run uses a file checkpointer. `--approve` opens a brand-new orchestrator on that
same file before resuming, so the approval really crosses a restart. Exit codes:
0 done, 2 the request is still missing fields or the flags are inconsistent.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from argparse import Namespace
from pathlib import Path
from typing import Any

from app.agents.booking import BookingAgent, poi_names
from app.agents.checkpoint import open_checkpointer
from app.agents.orchestrator import Orchestrator
from app.agents.search import SearchAgent
from app.core.config import hue_database_path
from app.db.store import PlanStore
from app.demo.booking_view import _item_lines, _poi_lines
from app.demo.budget_view import LABEL_NAMES, label_text
from app.demo.formatting import money, money_range
from app.demo.itinerary_view import _day_lines
from app.providers.booking_mock import MockBookingProvider, Mode
from app.providers.hotel_mock import MockHotelProvider
from app.providers.transport_mock import MockTransportProvider
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.booking import BookingResult
from app.schemas.budget import BudgetResult
from app.schemas.itinerary import ItineraryResult
from app.schemas.parsed_trip import ParsedTrip
from app.schemas.request import TripRequest
from app.services.budget_optimizer import BudgetAgent
from app.services.itinerary_optimizer import ItineraryAgent
from app.services.quote import UnknownOptionError
from app.services.quote_revalidator import QuoteRevalidator
from app.services.request_parser import TripRequestParser
from app.services.vi_request_parser import finalize_parsed, with_start_date

PLAN_THREAD = "demo-plan"
DEMO_OWNER = "demo-user"
BOOK_KEY = "demo-plan-key"
POI_PREVIEW = 5
_CHECKPOINT_FILE = "checkpoints.sqlite"


def run_plan(args: Namespace) -> int:
    """Analyse the sentence, run the graph, then optionally approve and book."""
    parsed = _analysed(args)
    if parsed.request is None:
        _print_analysis(parsed)
        print(_missing_message(parsed), file=sys.stderr)
        return 2
    if args.book and not args.approve:
        print("--book cần --approve trước: chỉ phương án đã duyệt mới được đặt.", file=sys.stderr)
        return 2
    try:
        return asyncio.run(_plan_flow(parsed, args))
    except UnknownOptionError as error:
        print(str(error), file=sys.stderr)
        return 2


def _analysed(args: Namespace) -> ParsedTrip:
    """Parse the sentence, then apply `--start` (fills only a missing date) and the overrides."""
    parsed = TripRequestParser().parse(args.text)
    if args.start is not None:
        parsed = with_start_date(parsed, args.start)
    overrides = {"origin": args.origin, "people": args.people}
    fields = {**parsed.fields, **{key: value for key, value in overrides.items() if value is not None}}
    success = parsed.source if parsed.source.startswith("RULES") else "RULES"
    return finalize_parsed(fields, list(parsed.notes), success)


def _missing_message(parsed: ParsedTrip) -> str:
    missing = ", ".join(parsed.missing_fields) or "không rõ"
    return f"Thiếu: {missing}. Thêm cờ còn thiếu (ví dụ --start YYYY-MM-DD) rồi chạy lại."


def _print_analysis(parsed: ParsedTrip) -> None:
    print("\n".join(_analysis_lines(parsed)))


def _analysis_lines(parsed: ParsedTrip) -> list[str]:
    fields = parsed.fields
    lines = [
        f"Phân tích câu (nguồn: {parsed.source})",
        f"  Điểm đi: {fields.get('origin', '-')}    Điểm đến: {fields.get('destination', '-')}",
        f"  Ngày: {_date_text(fields.get('start_date'))} -> {_date_text(fields.get('end_date'))}",
        f"  Số người: {fields.get('people', '-')}    Phòng: {fields.get('rooms', 1)}",
        f"  Ngân sách: {money(fields['budget_vnd']) if 'budget_vnd' in fields else '-'}",
        f"  Sở thích: {', '.join(fields.get('preferences', [])) or '-'}",
        f"  Còn thiếu: {', '.join(parsed.missing_fields) or 'không'}",
    ]
    lines.extend(f"  Ghi chú: {note}" for note in parsed.notes)
    return lines


def _date_text(value: Any) -> str:
    return value.isoformat() if value is not None else "-"


def _checkpoint_path(args: Namespace, tmp_dir: str) -> Path:
    if args.checkpoint:
        return Path(args.checkpoint)
    return Path(tmp_dir) / _CHECKPOINT_FILE


def _orchestrator(checkpointer: Any, store: PlanStore, repository: HuePlacesRepository) -> Orchestrator:
    return Orchestrator(
        SearchAgent(repository, MockTransportProvider(), MockHotelProvider()),
        BudgetAgent(places=repository),
        ItineraryAgent(places=repository),
        store,
        checkpointer,
    )


async def _plan_flow(parsed: ParsedTrip, args: Namespace) -> int:
    store = PlanStore("sqlite://")
    repository = HuePlacesRepository(hue_database_path())
    with tempfile.TemporaryDirectory(prefix="plan-demo-") as tmp:
        path = _checkpoint_path(args, tmp)
        waiting = await _start_run(path, store, repository, parsed.request)
        lines = _analysis_lines(parsed) + _run_lines(waiting)
        if not waiting["waiting"]:
            _emit(lines, waiting, None, args)
            return 1
        lines += _plan_lines(store, repository, waiting)
        final = waiting
        if args.approve:
            final = await _approve_after_restart(path, store, repository, args.approve, waiting)
            lines += _approval_lines(final, path)
        booking = _book(store, repository, final, args) if args.book else None
        if booking is not None:
            lines += _booking_lines(booking, final["approval"]["selected_offers"], store)
    _emit(lines, final, booking, args)
    return 0


async def _start_run(
    path: Path, store: PlanStore, repository: HuePlacesRepository, request: TripRequest
) -> dict[str, Any]:
    async with open_checkpointer(str(path)) as saver:
        return await _orchestrator(saver, store, repository).start(PLAN_THREAD, request, owner_id=DEMO_OWNER)


async def _approve_after_restart(
    path: Path,
    store: PlanStore,
    repository: HuePlacesRepository,
    option: str,
    waiting: dict[str, Any],
) -> dict[str, Any]:
    answer = {"action": "approve", "option": option, "user_id": DEMO_OWNER, "version": waiting["version"]}
    async with open_checkpointer(str(path)) as saver:
        return await _orchestrator(saver, store, repository).resume(PLAN_THREAD, answer)


def _run_lines(state: dict[str, Any]) -> list[str]:
    lines = ["", "Chạy graph", "  " + " → ".join(state["trace"])]
    if state["retries"]:
        lines.append(f"  Thử lại itinerary: {state['retries']} lần")
        lines.extend(f"    - {reason}" for reason in state["attempts"])
    return lines


def _plan_lines(store: PlanStore, repository: HuePlacesRepository, state: dict[str, Any]) -> list[str]:
    payload = store.latest(PLAN_THREAD)["payload"]
    lines = _itinerary_lines(payload["itinerary"], repository)
    lines += _budget_lines(BudgetResult.model_validate(payload["budget"]))
    lines += ["", f"Trạng thái: {state['status']} (plan {state['plan_id']}, version {state['version']})"]
    return lines


def _itinerary_lines(payload: dict[str, Any], repository: HuePlacesRepository) -> list[str]:
    itinerary = ItineraryResult.model_validate(payload)
    places = {}
    for poi_id in itinerary.poi_ids():
        place = repository.get_by_id(poi_id)
        if place is not None:
            places[poi_id] = place
    lines = ["", "Lịch trình"]
    for index, day in enumerate(itinerary.days, start=1):
        lines.extend(_day_lines(index, day, places))
    return lines


def _budget_lines(budget: BudgetResult) -> list[str]:
    lines = ["", "Ngân sách (gồm vé và bữa ăn của lịch trình)"]
    for option in budget.options:
        if option.label is None:
            continue
        total = money_range(option.known_total_vnd, option.known_total_max_vnd)
        lines.append(f"  {label_text(option)}: {total}  {option.budget_status}")
    if budget.shortfall_vnd is not None:
        lines.append(f"  Thiếu so với ngân sách: {money(budget.shortfall_vnd)}")
    return lines


def _approval_lines(state: dict[str, Any], path: Path) -> list[str]:
    approval = state["approval"]
    label = LABEL_NAMES[approval["option"]]
    return [
        "",
        f"Khởi động lại orchestrator từ checkpoint {path.name}…",
        f"Duyệt phương án {label} (version {approval['version']}, quote {approval['quote_hash'][:12]}…)",
        f"Trạng thái: {state['status']}",
    ]


def _book(
    store: PlanStore,
    repository: HuePlacesRepository,
    state: dict[str, Any],
    args: Namespace,
) -> BookingResult:
    selected = state["approval"]["selected_offers"]
    provider = MockBookingProvider(modes=_fail_modes(selected, args))
    revalidator = QuoteRevalidator(MockTransportProvider(), MockHotelProvider())
    agent = BookingAgent(store, provider, revalidator, places=repository)
    return agent.book(PLAN_THREAD, BOOK_KEY, DEMO_OWNER)


def _fail_modes(selected: list[dict[str, Any]], args: Namespace) -> dict[str, Mode]:
    if args.fail != "hotel":
        return {}
    return {offer["id"]: "fail" for offer in selected if offer["kind"] == "HOTEL"}


def _booking_lines(result: BookingResult, selected: list[dict[str, Any]], store: PlanStore) -> list[str]:
    names = _poi_names(store)
    entries = {offer["id"]: offer for offer in selected}
    pois = [item for item in result.items if item.kind == "POI"]
    lines = ["", f"Đặt với khóa {BOOK_KEY} → {result.status}"]
    for item in result.items:
        if item.kind != "POI":
            lines.extend(_item_lines(item, entries, names))
    for item in pois[:POI_PREVIEW]:
        lines.extend(_poi_lines(item, names))
    if len(pois) > POI_PREVIEW:
        lines.append(f"  … và {len(pois) - POI_PREVIEW} địa điểm khác")
    return lines


def _poi_names(store: PlanStore) -> dict[str, str]:
    itinerary = ItineraryResult.model_validate(store.latest(PLAN_THREAD)["payload"]["itinerary"])
    return poi_names(itinerary)


def _emit(lines: list[str], final: dict[str, Any], booking: BookingResult | None, args: Namespace) -> None:
    if args.json:
        payload = {"plan": final, "booking": None if booking is None else booking.model_dump(mode="json")}
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return
    print("\n".join(lines))
