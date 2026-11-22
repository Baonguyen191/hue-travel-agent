"""Agent routing/tool metrics and the planning metrics on hand-built plan payloads."""

from __future__ import annotations

import sys as _sys
from datetime import date
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parents[1]
BACKEND = _ROOT / "backend"
if str(BACKEND) not in _sys.path:
    _sys.path.insert(0, str(BACKEND))
_TESTS = _Path(__file__).resolve().parent
if str(_TESTS) not in _sys.path:
    _sys.path.insert(0, str(_TESTS))

from typing import Any  # noqa: E402

from app.evaluation.agent_metrics import handler_hits, tool_counts, tools_exact  # noqa: E402
from app.evaluation.gold import BudgetExpect, ConstraintExpect, ScenarioExpect  # noqa: E402
from app.evaluation.planning_metrics import budget_compliant, constraint_checks, schedule_feasible  # noqa: E402
from app.repositories.hue_places import HuePlacesRepository  # noqa: E402
from test_rag_index import make_place  # noqa: E402

DAI_NOI = "huetripo:531787"


def _expect(**kwargs: Any) -> ScenarioExpect:
    base: dict[str, Any] = {"handlers": ["plan_new"], "final_state": "awaiting_approval"}
    base.update(kwargs)
    return ScenarioExpect(**base)


def test_handler_hits() -> None:
    assert handler_hits(["plan_new", "place_info"], ["plan_new", "out_of_scope"]) == (1, 2)
    assert handler_hits(["plan_new", "modify"], ["plan_new"]) == (1, 2)


def test_tools_exact_and_counts() -> None:
    expect = _expect(tools_called=["poi_search"], tools_not_called=["transport"])
    assert tools_exact({"poi_search", "hotel"}, expect) is True
    assert tools_exact({"poi_search", "hotel", "transport"}, expect) is False
    both = _expect(tools_called=["poi_search", "hotel"], tools_not_called=["transport"])
    assert tool_counts({"poi_search", "transport"}, both) == (1, 1, 1)


def test_budget_compliant() -> None:
    feasible = BudgetExpect(budget_vnd=2_000_000, feasible=True)
    ok = {"options": [{"known_total_max_vnd": 1_900_000, "budget_status": "WITHIN_BUDGET"}], "shortfall_vnd": None}
    lying = {"options": [{"known_total_max_vnd": 2_100_000, "budget_status": "WITHIN_BUDGET"}], "shortfall_vnd": None}
    assert budget_compliant(ok, feasible) is True
    assert budget_compliant(lying, feasible) is False
    over = {"options": [{"known_total_max_vnd": 3_000_000, "budget_status": "OVER_BUDGET"}], "shortfall_vnd": 1_000_000}
    assert budget_compliant(over, BudgetExpect(budget_vnd=2_000_000, feasible=False)) is True
    assert budget_compliant(ok, BudgetExpect(budget_vnd=2_000_000, feasible=False)) is False


def _visit(poi_id: str, start: str, end: str) -> dict[str, Any]:
    return {"kind": "VISIT", "poi_id": poi_id, "name": poi_id, "start_at": start, "end_at": end}


def _plan(*events: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    return {"days": [{"date": "2026-12-20", "events": list(events)}], "validation": {"warnings": warnings or []}}


def test_schedule_feasible() -> None:
    dai_noi = HuePlacesRepository(BACKEND / "data" / "hue.sqlite").get_by_id(DAI_NOI)
    assert dai_noi is not None
    places = {DAI_NOI: dai_noi}
    late = _plan(_visit(DAI_NOI, "2026-12-20T17:00:00", "2026-12-20T18:00:00"))
    ok, unchecked, problems = schedule_feasible(late, places)
    assert not ok and unchecked == 0 and problems
    early = _plan(_visit(DAI_NOI, "2026-12-20T08:00:00", "2026-12-20T09:00:00"))
    assert schedule_feasible(early, places) == (True, 0, [])
    unknown = make_place("huetripo:900", opening_hours_raw=None)
    free = _plan(_visit("huetripo:900", "2026-12-20T10:00:00", "2026-12-20T11:00:00"))
    assert schedule_feasible(free, {"huetripo:900": unknown}) == (True, 1, [])
    meal = _plan(
        {"kind": "MEAL_BREAK", "name": "Dinner", "start_at": "2026-12-20T20:00:00", "end_at": "2026-12-20T21:30:00"}
    )
    assert schedule_feasible(meal, places)[0] is False
    assert schedule_feasible(_plan(warnings=["overlap"]), places)[0] is False


def test_constraint_checks() -> None:
    plan = _plan(_visit("huetripo:900", "2026-12-20T10:00:00", "2026-12-20T11:00:00"))
    assert constraint_checks(plan, ConstraintExpect(must_include=[DAI_NOI])) == {"must_include": False}
    two_days = {"days": [{"date": "2026-12-20", "events": []}, {"date": "2026-12-21", "events": []}]}
    got = constraint_checks(two_days, ConstraintExpect(num_days=2, start_date=date(2026, 12, 20)))
    assert got == {"num_days": True, "start_date": True}
    cafe = _plan(
        {
            "kind": "MEAL_BREAK",
            "category": "cafe",
            "name": "Cafe",
            "start_at": "2026-12-20T15:00:00",
            "end_at": "2026-12-20T16:00:00",
        }
    )
    assert constraint_checks(cafe, ConstraintExpect(exclude_categories=["cafe"])) == {"exclude_categories": False}
