"""Plain-text helpers shared by the demo renderers: money, tables and request summaries."""

from __future__ import annotations

from app.schemas.request import TripRequest

_UNIT_LABELS = {
    "VND_PER_PERSON_PER_LEG": "per person per leg",
    "VND_PER_ROOM_PER_NIGHT": "per room per night",
    "VND_PER_GROUP_PER_DAY": "per group per day",
    "VND_PER_PERSON_PER_DAY": "per person per day",
    "VND_PER_PERSON_PER_MEAL_ASSUMED": "per person per meal (assumed)",
    "VND_PER_PERSON": "per person",
}


def money(amount: int) -> str:
    return f"{amount:,} VND"


def money_range(low: int, high: int) -> str:
    return money(low) if low == high else f"{low:,} – {high:,} VND"


def unit_label(unit: str) -> str:
    return _UNIT_LABELS.get(unit, unit.lower())


def format_table(rows: list[list[str]]) -> list[str]:
    """Pad every column to its widest cell and underline the header row."""
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    formatted: list[str] = []
    for row in rows:
        cells = "  ".join(cell.ljust(width) for cell, width in zip(row, widths))
        formatted.append(("  " + cells).rstrip())
    formatted.insert(1, "  " + "  ".join("-" * width for width in widths))
    return formatted


def request_lines(request: TripRequest) -> list[str]:
    budget = money(request.budget_vnd) if request.budget_vnd is not None else "not set"
    return [
        "Request",
        f"  Route: {request.origin} -> {request.destination}",
        f"  Dates: {request.start_date} -> {request.end_date}",
        f"  People: {request.people}  Rooms: {request.rooms}  Budget: {budget}",
        f"  Preferences: {', '.join(request.preferences) or '-'}",
        f"  Categories: {', '.join(request.categories) or '-'}",
        f"  Keyword: {request.keyword or '-'}",
    ]


def warning_lines(warnings: list[str]) -> list[str]:
    if not warnings:
        return ["Warnings: none"]
    return ["Warnings:"] + [f"  - {warning}" for warning in warnings]
