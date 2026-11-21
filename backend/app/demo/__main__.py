"""CLI demos for the Search, Budget and Itinerary Agents, run from `backend/`.

    python -m app.demo search --scenario dod
    python -m app.demo budget --scenario dod
    python -m app.demo itinerary --scenario dod
    python -m app.demo book --scenario dod

All use the local Hue SQLite source and deterministic mock providers, so every
transport and hotel offer is labelled `[MOCK]`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any, get_args

from pydantic import ValidationError

from app.agents.booking import ApprovalRequiredError, BookingAgent, poi_names
from app.agents.search import SearchAgent
from app.core.config import hue_database_path
from app.db.store import PlanStore
from app.demo.booking_view import (
    approval_lines,
    blocked_lines,
    booking_lines,
    explanation_lines,
    forbidden_lines,
    retry_lines,
)
from app.demo.budget_view import render_budget
from app.demo.formatting import format_table, money, request_lines, unit_label, warning_lines
from app.demo.itinerary_view import render_itinerary
from app.providers.booking_mock import MockBookingProvider, Mode, ReconcileStatus
from app.providers.hotel_mock import MockHotelProvider
from app.providers.transport_mock import MockTransportProvider
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.booking import BookingResult
from app.schemas.offer import HotelOffer, TransportOffer
from app.schemas.itinerary import ItineraryResult
from app.schemas.place import Place, PlaceCategory, PlaceSearchResult
from app.schemas.request import TripRequest
from app.schemas.search import SearchResult
from app.services.budget_optimizer import SIGHTSEEING_CATEGORIES, BudgetAgent
from app.services.itinerary_optimizer import ItineraryAgent
from app.services.quote import UnknownOptionError, approve_option, build_selected_offers
from app.services.quote_revalidator import QuoteRevalidator

SCENARIOS: dict[str, dict[str, Any]] = {
    "dod": {
        "origin": "Hà Nội",
        "destination": "Huế",
        "start_date": "2026-12-05",
        "end_date": "2026-12-07",
        "people": 2,
        "rooms": 1,
        "budget_vnd": 6_000_000,
        "preferences": ["di tích", "đặc sản"],
    },
}

_TABLE_HEADERS = ["#", "Name", "poi_id", "Score", "Rating", "Distance", "Source URL"]
_DEFAULT_VISIT_COUNT = 6
_BOOK_OPTIONS = ("BUDGET", "BALANCED", "COMFORT")
_BOOK_THREAD = "demo-book"
_BOOK_KEY = "demo-key-1"
_OTHER_USER = "other-user"
_PRICE_BUMP_VND = 100_000


def _request_parent() -> argparse.ArgumentParser:
    """Request flags shared by every subcommand that builds a TripRequest."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--scenario", choices=sorted(SCENARIOS))
    parent.add_argument("--origin")
    parent.add_argument("--destination")
    parent.add_argument("--start", help="Start date, YYYY-MM-DD.")
    parent.add_argument("--end", help="End date, YYYY-MM-DD.")
    parent.add_argument("--people", type=int)
    parent.add_argument("--rooms", type=int)
    parent.add_argument("--budget", type=int, help="Budget in VND.")
    parent.add_argument("--pref", action="append", help="Preference text; repeatable.")
    parent.add_argument(
        "--category", action="append", choices=sorted(get_args(PlaceCategory)),
        help="Place category; repeatable.",
    )
    parent.add_argument("--keyword")
    return parent


def _book_parser(subparsers: Any, shared: argparse.ArgumentParser) -> None:
    book = subparsers.add_parser(
        "book", parents=[shared],
        help="Approve one budget option, then book it with mock providers.",
    )
    book.add_argument("--option", choices=_BOOK_OPTIONS, default="BUDGET", help="Budget option to approve.")
    book.add_argument("--fail", choices=["transport", "hotel"], help="Make the provider refuse these offers.")
    book.add_argument("--timeout", choices=["hotel"], help="Time out the hotel booking; the second press reconciles it.")
    book.add_argument("--price-change", action="store_true", help="Change the outbound price after approval.")
    book.add_argument("--other-user", action="store_true", help="Also show another user's refused attempt.")
    book.add_argument("--json", action="store_true", help="Print only the final BookingResult JSON.")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with the `search`, `budget`, `itinerary` and `book` subcommands."""
    parser = argparse.ArgumentParser(prog="python -m app.demo", description="Agent demos.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    shared = _request_parent()
    search = subparsers.add_parser(
        "search", parents=[shared], help="Run the Search Agent on a trip request."
    )
    search.add_argument("--per-category", type=int, default=5, help="Rows shown per category.")
    search.add_argument("--json", action="store_true", help="Print the raw SearchResult JSON.")
    budget = subparsers.add_parser(
        "budget", parents=[shared], help="Price a trip and rank budget options."
    )
    budget.add_argument(
        "--visit", action="append", metavar="POI_ID",
        help="A visited POI id; repeatable. Default: sample sightseeing candidates.",
    )
    budget.add_argument("--json", action="store_true", help="Print the raw BudgetResult JSON.")
    itinerary = subparsers.add_parser(
        "itinerary", parents=[shared],
        help="Plan days from Search results, then price the itinerary's visits and meals.",
    )
    itinerary.add_argument("--json", action="store_true", help="Print the raw ItineraryResult JSON.")
    _book_parser(subparsers, shared)
    return parser


def _overrides(args: argparse.Namespace) -> dict[str, Any]:
    """Collect flags that were given; flags always override the scenario preset."""
    fields = {
        "origin": args.origin,
        "destination": args.destination,
        "start_date": args.start,
        "end_date": args.end,
        "people": args.people,
        "rooms": args.rooms,
        "budget_vnd": args.budget,
        "keyword": args.keyword,
    }
    overrides = {name: value for name, value in fields.items() if value is not None}
    if args.pref:
        overrides["preferences"] = args.pref
    if args.category:
        overrides["categories"] = args.category
    return overrides


def build_request(args: argparse.Namespace) -> TripRequest:
    """Merge the optional scenario preset with explicit flags into a TripRequest."""
    if args.scenario:
        values: dict[str, Any] = dict(SCENARIOS[args.scenario])
    else:
        # Without a scenario, reuse only the DoD trip basics so ad-hoc
        # `--keyword`/`--category` runs work without five required flags.
        values = {k: v for k, v in SCENARIOS["dod"].items() if k != "preferences"}
    values.update(_overrides(args))
    return TripRequest(**values)


def _source_tag(source: str) -> str:
    return "[MOCK] " if source == "MOCK" else ""


def _rating_text(item: PlaceSearchResult) -> str:
    place = item.place
    if place.rating_value is None:
        return "-"
    return f"{place.rating_value:.1f} ({place.rating_count or 0})"


def _distance_text(item: PlaceSearchResult) -> str:
    return "-" if item.distance_km is None else f"{item.distance_km:.2f} km"


def _category_table(items: list[PlaceSearchResult]) -> list[str]:
    rows = [_TABLE_HEADERS]
    for rank, item in enumerate(items, start=1):
        rows.append(
            [
                str(rank),
                item.place.name,
                item.place.id,
                f"{item.score:.1f}",
                _rating_text(item),
                _distance_text(item),
                item.place.source_url or "-",
            ]
        )
    return format_table(rows)


def _candidate_lines(candidates: list[PlaceSearchResult], per_category: int) -> list[str]:
    groups: dict[str, list[PlaceSearchResult]] = {}
    for item in candidates:
        groups.setdefault(item.place.category, []).append(item)
    lines: list[str] = []
    for category, items in groups.items():
        shown = items[:per_category]
        lines.append("")
        lines.append(f"== {category}: {len(items)} candidates, showing {len(shown)} ==")
        lines.extend(_category_table(shown))
    return lines or ["", "No POI candidates."]


def _transport_lines(offers: list[TransportOffer]) -> list[str]:
    if not offers:
        return ["", "Transport offers: none"]
    lines = ["", "Transport offers"]
    for offer in offers:
        lines.append(
            f"  {_source_tag(offer.source)}{offer.leg.title()}: {offer.provider}, "
            f"{offer.origin} -> {offer.destination}, {offer.departure_date}, "
            f"{money(offer.price_vnd)} {unit_label(offer.price_unit)}"
        )
    return lines


def _hotel_lines(offers: list[HotelOffer]) -> list[str]:
    if not offers:
        return ["", "Hotel offers: none"]
    lines = ["", "Hotel offers"]
    for offer in offers:
        lines.append(
            f"  {_source_tag(offer.source)}{offer.hotel_name}, {offer.destination}, "
            f"{offer.check_in} -> {offer.check_out} ({offer.nights} nights), "
            f"{money(offer.price_per_room_night_vnd)} {unit_label(offer.price_unit)}"
        )
    return lines


def render_text(request: TripRequest, result: SearchResult, per_category: int) -> str:
    """Render a request summary, POI tables per category, and labelled offers."""
    lines = request_lines(request)
    lines.append("")
    lines.append(f"Status: {result.status}")
    lines.extend(warning_lines(result.warnings))
    lines.extend(_candidate_lines(result.poi_candidates, per_category))
    lines.extend(_transport_lines(result.transport_offers))
    lines.extend(_hotel_lines(result.hotel_offers))
    return "\n".join(lines)


def _repository() -> HuePlacesRepository:
    return HuePlacesRepository(hue_database_path())


def _build_agent() -> SearchAgent:
    return SearchAgent(_repository(), MockTransportProvider(), MockHotelProvider())


def _default_visits(search: SearchResult) -> list[str]:
    sightseeing = [
        item.place.id for item in search.poi_candidates if item.place.category in SIGHTSEEING_CATEGORIES
    ]
    return sightseeing[:_DEFAULT_VISIT_COUNT]


def _visit_labels(search: SearchResult, visits: list[str]) -> list[str]:
    names = {item.place.id: item.place.name for item in search.poi_candidates}
    return [f"{names[poi_id]} ({poi_id})" if poi_id in names else poi_id for poi_id in visits]


def _places_by_id(repository: HuePlacesRepository, itinerary: ItineraryResult) -> dict[str, Place]:
    places: dict[str, Place] = {}
    for poi_id in itinerary.poi_ids():
        place = repository.get_by_id(poi_id)
        if place is not None:
            places[poi_id] = place
    return places


def _run_search(request: TripRequest, args: argparse.Namespace) -> int:
    result = asyncio.run(_build_agent().search(request))
    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        print(render_text(request, result, args.per_category))
    return 0


def _run_budget(request: TripRequest, args: argparse.Namespace) -> int:
    search = asyncio.run(_build_agent().search(request))
    visits = args.visit or _default_visits(search)
    try:
        result = BudgetAgent(places=_repository()).build(request, search, visit_poi_ids=visits)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        print(render_budget(request, _visit_labels(search, visits), not args.visit, result))
    return 0


def _run_itinerary(request: TripRequest, args: argparse.Namespace) -> int:
    repository = _repository()
    search = asyncio.run(
        SearchAgent(repository, MockTransportProvider(), MockHotelProvider()).search(request)
    )
    itinerary = ItineraryAgent(places=repository).plan(request, search)
    if args.json:
        print(itinerary.model_dump_json(indent=2))
        return 0
    budget = BudgetAgent(places=repository).build(request, search, visit_poi_ids=itinerary.poi_ids())
    print(render_itinerary(request, itinerary, budget, _places_by_id(repository, itinerary)))
    return 0


def _book_payload(request: TripRequest, repository: HuePlacesRepository) -> dict[str, Any]:
    """Build the plan payload the way the Orchestrator does, with visit ids for the budget."""
    search = asyncio.run(
        SearchAgent(repository, MockTransportProvider(), MockHotelProvider()).search(request)
    )
    itinerary = ItineraryAgent(places=repository).plan(request, search)
    budget = BudgetAgent(places=repository).build(request, search, visit_poi_ids=itinerary.poi_ids())
    return {
        "request": request.model_dump(mode="json"),
        "search": search.model_dump(mode="json"),
        "budget": budget.model_dump(mode="json"),
        "itinerary": itinerary.model_dump(mode="json"),
    }


def _offer_ids(selected: list[dict[str, Any]], kind: str) -> list[str]:
    return [offer["id"] for offer in selected if offer["kind"] == kind]


def _failure_modes(selected: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Mode]:
    modes: dict[str, Mode] = {}
    if args.fail == "transport":
        modes.update({offer_id: "fail" for offer_id in _offer_ids(selected, "TRANSPORT")})
    if args.fail == "hotel":
        modes.update({offer_id: "fail" for offer_id in _offer_ids(selected, "HOTEL")})
    if args.timeout == "hotel":
        modes.update({offer_id: "timeout" for offer_id in _offer_ids(selected, "HOTEL")})
    return modes


def _reconcile_answers(
    selected: list[dict[str, Any]], args: argparse.Namespace
) -> dict[str, ReconcileStatus]:
    if args.timeout != "hotel":
        return {}
    return {offer_id: "BOOKED" for offer_id in _offer_ids(selected, "HOTEL")}


def _price_overrides(selected: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, int] | None:
    """Raise the outbound price so the revalidator sees a change after approval."""
    outbound = next((offer for offer in selected if offer["kind"] == "TRANSPORT"), None)
    if not args.price_change or outbound is None:
        return None
    return {outbound["id"]: outbound["price"] + _PRICE_BUMP_VND}


def _book_agent(
    store: PlanStore,
    repository: HuePlacesRepository,
    selected: list[dict[str, Any]],
    args: argparse.Namespace,
) -> tuple[BookingAgent, MockBookingProvider]:
    provider = MockBookingProvider(
        modes=_failure_modes(selected, args),
        reconcile=_reconcile_answers(selected, args),
    )
    revalidator = QuoteRevalidator(
        MockTransportProvider(price_overrides=_price_overrides(selected, args)),
        MockHotelProvider(),
    )
    return BookingAgent(store, provider, revalidator, places=repository), provider


def _blocked_message(agent: BookingAgent) -> str:
    try:
        agent.book(_BOOK_THREAD, _BOOK_KEY)
    except ApprovalRequiredError as error:
        return str(error)
    return "Booking was not blocked."


def _forbidden_message(agent: BookingAgent) -> str:
    try:
        agent.book(_BOOK_THREAD, _BOOK_KEY, user_id=_OTHER_USER)
    except PermissionError as error:
        return str(error)
    return "The other user was not refused."


def _book_steps(
    agent: BookingAgent,
    store: PlanStore,
    provider: MockBookingProvider,
    payload: dict[str, Any],
    selected: list[dict[str, Any]],
    args: argparse.Namespace,
) -> tuple[list[str], BookingResult]:
    """Run the numbered demo steps and return the rendered lines and the final result."""
    names = poi_names(ItineraryResult.model_validate(payload["itinerary"]))
    entries = {offer["id"]: offer for offer in selected}
    lines = blocked_lines(_blocked_message(agent))
    approval = approve_option(store, store.latest(_BOOK_THREAD), args.option)
    lines += approval_lines(approval)
    if args.other_user:
        lines += forbidden_lines(_forbidden_message(agent))
    first = agent.book(_BOOK_THREAD, _BOOK_KEY)
    second = agent.book(_BOOK_THREAD, _BOOK_KEY)
    lines += booking_lines(first, _BOOK_KEY, entries, names)
    lines += retry_lines(first, second, entries, len(provider.book_calls))
    lines += explanation_lines(second)
    return lines, second


def _run_book(request: TripRequest, args: argparse.Namespace) -> int:
    repository = _repository()
    payload = _book_payload(request, repository)
    store = PlanStore("sqlite://")
    store.save_plan(_BOOK_THREAD, payload)
    try:
        selected = build_selected_offers(payload["budget"], args.option)
    except UnknownOptionError as error:
        print(str(error), file=sys.stderr)
        return 2
    agent, provider = _book_agent(store, repository, selected, args)
    lines, final = _book_steps(agent, store, provider, payload, selected, args)
    if args.json:
        print(final.model_dump_json(indent=2))
    else:
        print("\n".join(lines))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run a demo command and return a process exit code."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        request = build_request(args)
    except ValidationError as error:
        print(f"Invalid request: {error}", file=sys.stderr)
        return 2
    if args.command == "budget":
        return _run_budget(request, args)
    if args.command == "itinerary":
        return _run_itinerary(request, args)
    if args.command == "book":
        return _run_book(request, args)
    return _run_search(request, args)


if __name__ == "__main__":
    raise SystemExit(main())
