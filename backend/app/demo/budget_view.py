"""Text rendering for the Budget Agent demo (`budget` and the itinerary budget block)."""

from __future__ import annotations

from app.demo.formatting import format_table, money, money_range, request_lines, unit_label, warning_lines
from app.schemas.budget import BudgetOption, BudgetResult, CostItem
from app.schemas.request import TripRequest

LABEL_NAMES = {"BUDGET": "Tiết kiệm", "BALANCED": "Cân bằng", "COMFORT": "Thoải mái"}


def _tag(item: CostItem) -> str:
    if item.price_kind == "UNKNOWN":
        return "[UNKNOWN]"
    if item.source == "MOCK":
        return "[MOCK]"
    if item.source == "HUE_POI_SOURCE":
        return "[DATA]"
    return "[ESTIMATED]"


def _amount_text(item: CostItem) -> str:
    if item.amount_vnd is None:
        return "unknown"
    if item.amount_max_vnd is None:
        return money(item.amount_vnd)
    return money_range(item.amount_vnd, item.amount_max_vnd)


def label_text(option: BudgetOption) -> str:
    if option.label is None:
        return "-"
    return f"{LABEL_NAMES[option.label]} ({option.label})"


def _option_row(rank: int, option: BudgetOption) -> list[str]:
    outbound, returning, hotel = option.transport_outbound, option.transport_return, option.hotel
    return [
        str(rank),
        label_text(option),
        f"{outbound.mode} {money(outbound.price_vnd)}" if outbound else "-",
        f"{returning.mode} {money(returning.price_vnd)}" if returning else "-",
        f"{hotel.hotel_name} ({hotel.tier}) {money(hotel.price_per_room_night_vnd)}/night" if hotel else "-",
        money_range(option.known_total_vnd, option.known_total_max_vnd),
        option.budget_status,
        str(option.unknown_item_count),
    ]


def _options_table(result: BudgetResult) -> list[str]:
    headers = ["#", "Label", "Outbound", "Return", "Hotel", "Total", "Status", "Unknown"]
    rows = [headers] + [_option_row(rank, option) for rank, option in enumerate(result.options, start=1)]
    return format_table(rows)


def _detail_option(result: BudgetResult) -> BudgetOption:
    """Prefer BALANCED, then COMFORT, then BUDGET, then the first option."""
    for label in ("BALANCED", "COMFORT", "BUDGET"):
        match = next((option for option in result.options if option.label == label), None)
        if match is not None:
            return match
    return result.options[0]


def _item_line(item: CostItem) -> str:
    unit = unit_label(item.price_unit)
    return (
        f"  {_tag(item):<11} {item.label} | {item.quantity} x {unit} | "
        f"{_amount_text(item)} | {item.note or '-'}"
    )


def _detail_lines(result: BudgetResult) -> list[str]:
    option = _detail_option(result)
    lines = ["", f"Detail: {label_text(option)}"]
    lines.extend(_item_line(item) for item in option.items)
    lines.append("")
    lines.append(f"Known total: {money_range(option.known_total_vnd, option.known_total_max_vnd)}")
    lines.append(f"Unknown items: {option.unknown_item_count}")
    lines.append(f"Remaining: {money(option.budget_remaining_vnd)}" if option.budget_remaining_vnd is not None else "Remaining: n/a")
    if result.shortfall_vnd is not None:
        lines.append(f"Shortfall: {money(result.shortfall_vnd)}")
    warnings = result.warnings + option.warnings
    lines.extend(warning_lines(warnings))
    return lines


def render_budget(
    request: TripRequest, visit_labels: list[str], visits_are_sample: bool, result: BudgetResult
) -> str:
    """Render the request, the visits used, the option table and the detail section."""
    lines = request_lines(request)
    prefix = "Sample visits (Itinerary will choose the real list)" if visits_are_sample else "Visits"
    lines.append(f"{prefix}: {', '.join(visit_labels) or 'none'}")
    lines.append("")
    lines.append("Budget options")
    lines.extend(_options_table(result))
    lines.extend(_detail_lines(result))
    return "\n".join(lines)
