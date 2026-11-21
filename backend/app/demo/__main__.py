"""CLI demo for the Search Agent: `python -m app.demo search --scenario dod`.

Run from `backend/`. Uses the local Hue SQLite source and deterministic mock
providers, so every transport and hotel offer is labelled `[MOCK]`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any, get_args

from pydantic import ValidationError

from app.agents.search import SearchAgent
from app.core.config import hue_database_path
from app.providers.hotel_mock import MockHotelProvider
from app.providers.transport_mock import MockTransportProvider
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.offer import HotelOffer, TransportOffer
from app.schemas.place import PlaceCategory, PlaceSearchResult
from app.schemas.request import TripRequest
from app.schemas.search import SearchResult

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

_UNIT_LABELS = {
    "VND_PER_PERSON_PER_LEG": "per person per leg",
    "VND_PER_ROOM_PER_NIGHT": "per room per night",
}
_TABLE_HEADERS = ["#", "Name", "poi_id", "Score", "Rating", "Distance", "Source URL"]


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with the `search` subcommand."""
    parser = argparse.ArgumentParser(prog="python -m app.demo", description="Agent demos.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    search = subparsers.add_parser("search", help="Run the Search Agent on a trip request.")
    search.add_argument("--scenario", choices=sorted(SCENARIOS))
    search.add_argument("--origin")
    search.add_argument("--destination")
    search.add_argument("--start", help="Start date, YYYY-MM-DD.")
    search.add_argument("--end", help="End date, YYYY-MM-DD.")
    search.add_argument("--people", type=int)
    search.add_argument("--rooms", type=int)
    search.add_argument("--budget", type=int, help="Budget in VND.")
    search.add_argument("--pref", action="append", help="Preference text; repeatable.")
    search.add_argument(
        "--category", action="append", choices=sorted(get_args(PlaceCategory)),
        help="Place category; repeatable.",
    )
    search.add_argument("--keyword")
    search.add_argument("--per-category", type=int, default=5, help="Rows shown per category.")
    search.add_argument("--json", action="store_true", help="Print the raw SearchResult JSON.")
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


def _money(amount: int) -> str:
    return f"{amount:,} VND"


def _unit_label(unit: str) -> str:
    return _UNIT_LABELS.get(unit, unit.lower())


def _source_tag(source: str) -> str:
    return "[MOCK] " if source == "MOCK" else ""


def _request_lines(request: TripRequest) -> list[str]:
    budget = _money(request.budget_vnd) if request.budget_vnd is not None else "not set"
    return [
        "Request",
        f"  Route: {request.origin} -> {request.destination}",
        f"  Dates: {request.start_date} -> {request.end_date}",
        f"  People: {request.people}  Rooms: {request.rooms}  Budget: {budget}",
        f"  Preferences: {', '.join(request.preferences) or '-'}",
        f"  Categories: {', '.join(request.categories) or '-'}",
        f"  Keyword: {request.keyword or '-'}",
    ]


def _warning_lines(warnings: list[str]) -> list[str]:
    if not warnings:
        return ["Warnings: none"]
    return ["Warnings:"] + [f"  - {warning}" for warning in warnings]


def _rating_text(item: PlaceSearchResult) -> str:
    place = item.place
    if place.rating_value is None:
        return "-"
    return f"{place.rating_value:.1f} ({place.rating_count or 0})"


def _distance_text(item: PlaceSearchResult) -> str:
    return "-" if item.distance_km is None else f"{item.distance_km:.2f} km"


def _format_table(rows: list[list[str]]) -> list[str]:
    """Pad every column to its widest cell and underline the header row."""
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    formatted: list[str] = []
    for row in rows:
        cells = "  ".join(cell.ljust(width) for cell, width in zip(row, widths))
        formatted.append(("  " + cells).rstrip())
    formatted.insert(1, "  " + "  ".join("-" * width for width in widths))
    return formatted


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
    return _format_table(rows)


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
            f"{_money(offer.price_vnd)} {_unit_label(offer.price_unit)}"
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
            f"{_money(offer.price_per_room_night_vnd)} {_unit_label(offer.price_unit)}"
        )
    return lines


def render_text(request: TripRequest, result: SearchResult, per_category: int) -> str:
    """Render a request summary, POI tables per category, and labelled offers."""
    lines = _request_lines(request)
    lines.append("")
    lines.append(f"Status: {result.status}")
    lines.extend(_warning_lines(result.warnings))
    lines.extend(_candidate_lines(result.poi_candidates, per_category))
    lines.extend(_transport_lines(result.transport_offers))
    lines.extend(_hotel_lines(result.hotel_offers))
    return "\n".join(lines)


def _build_agent() -> SearchAgent:
    return SearchAgent(
        HuePlacesRepository(hue_database_path()),
        MockTransportProvider(),
        MockHotelProvider(),
    )


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
    result = asyncio.run(_build_agent().search(request))
    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        print(render_text(request, result, args.per_category))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
