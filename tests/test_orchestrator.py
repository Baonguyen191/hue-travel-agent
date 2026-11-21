"""LangGraph orchestrator: trace order, visit ids, validation retries, durable approval, owners."""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
HUE_DB = BACKEND / "data" / "hue.sqlite"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

import app.agents.orchestrator as orchestrator_module  # noqa: E402
from app.agents.checkpoint import open_checkpointer  # noqa: E402
from app.agents.orchestrator import Orchestrator, StalePlanError  # noqa: E402
from app.agents.search import SearchAgent  # noqa: E402
from app.db.store import PlanStore  # noqa: E402
from app.providers.hotel_mock import MockHotelProvider  # noqa: E402
from app.providers.transport_mock import MockTransportProvider  # noqa: E402
from app.repositories.hue_places import HuePlacesRepository  # noqa: E402
from app.schemas.itinerary import ItineraryResult  # noqa: E402
from app.schemas.request import TripRequest  # noqa: E402
from app.services.budget_optimizer import BudgetAgent  # noqa: E402
from app.services.itinerary_optimizer import ItineraryAgent  # noqa: E402
from app.services.quote import UnknownOptionError  # noqa: E402

DOD_REQUEST = TripRequest(
    origin="Hà Nội",
    destination="Huế",
    start_date=date(2026, 12, 5),
    end_date=date(2026, 12, 7),
    people=2,
    rooms=1,
    budget_vnd=6_000_000,
    preferences=["di tích", "đặc sản"],
)
ALICE = "alice"


def _orchestrator(checkpointer: Any, store: PlanStore) -> Orchestrator:
    repository = HuePlacesRepository(HUE_DB)
    return Orchestrator(
        SearchAgent(repository, MockTransportProvider(), MockHotelProvider()),
        BudgetAgent(places=repository),
        ItineraryAgent(places=repository),
        store,
        checkpointer,
    )


def _approve(version: int, option: str = "BUDGET", user: str = ALICE) -> dict[str, Any]:
    return {"action": "approve", "option": option, "user_id": user, "version": version}


def test_dod_workflow_waits_for_approval_with_the_expected_trace() -> None:
    store = PlanStore("sqlite://")

    async def scenario() -> dict[str, Any]:
        orchestrator = _orchestrator(InMemorySaver(), store)
        return await orchestrator.start("thread-1", DOD_REQUEST, owner_id=ALICE)

    result = asyncio.run(scenario())

    assert result["status"] == "AWAITING_APPROVAL"
    assert result["waiting"] is True
    assert result["version"] == 1
    assert result["trace"] == ["search", "itinerary", "budget", "validate", "approval"]
    assert set(result["options"]) <= {"BUDGET", "BALANCED", "COMFORT"}


def test_budget_is_priced_with_the_itinerary_visit_ids() -> None:
    store = PlanStore("sqlite://")

    async def scenario() -> dict[str, Any]:
        return await _orchestrator(InMemorySaver(), store).start("visits", DOD_REQUEST)

    asyncio.run(scenario())
    payload = store.latest("visits")["payload"]
    visit_ids = set(ItineraryResult.model_validate(payload["itinerary"]).poi_ids())
    priced_ids = {
        item["poi_id"]
        for option in payload["budget"]["options"]
        for item in option["items"]
        if item["code"] == "admission" and item["poi_id"]
    }

    assert visit_ids
    assert priced_ids & visit_ids


def test_budget_build_receives_the_itinerary_poi_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, list[str]] = {}
    original = BudgetAgent.build

    def spy(self: BudgetAgent, request: Any, search: Any, visit_poi_ids: Any = None) -> Any:
        seen["visits"] = list(visit_poi_ids or [])
        return original(self, request, search, visit_poi_ids=visit_poi_ids)

    monkeypatch.setattr(BudgetAgent, "build", spy)
    store = PlanStore("sqlite://")

    asyncio.run(_orchestrator(InMemorySaver(), store).start("spy", DOD_REQUEST))
    payload = store.latest("spy")["payload"]

    assert seen["visits"] == ItineraryResult.model_validate(payload["itinerary"]).poi_ids()
    assert seen["visits"]


def test_o01_always_failing_validation_stops_after_exactly_three_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(orchestrator_module, "validate_plan", lambda itinerary, budget: ["forced failure"])
    plan_calls: list[int] = []
    original_plan = ItineraryAgent.plan

    def counting(self: ItineraryAgent, request: Any, search: Any) -> Any:
        plan_calls.append(1)
        return original_plan(self, request, search)

    monkeypatch.setattr(ItineraryAgent, "plan", counting)
    store = PlanStore("sqlite://")

    result = asyncio.run(_orchestrator(InMemorySaver(), store).start("o01", DOD_REQUEST))

    assert result["status"] == "FAILED_VALIDATION"
    assert result["retries"] == 3
    assert len(plan_calls) == 4
    assert result["warnings"] == ["forced failure"] * 4
    assert result["trace"][-1] == "failed"
    assert "approval" not in result["trace"]
    assert store.latest("o01") is None


def test_r01_approval_survives_a_new_orchestrator_on_the_same_checkpoint_file(tmp_path: Path) -> None:
    store = PlanStore(f"sqlite:///{tmp_path / 'plans.sqlite'}")
    checkpoint_file = str(tmp_path / "checkpoints.sqlite")

    async def first_process() -> dict[str, Any]:
        async with open_checkpointer(checkpoint_file) as saver:
            return await _orchestrator(saver, store).start("r01", DOD_REQUEST, owner_id=ALICE)

    async def second_process(version: int) -> dict[str, Any]:
        async with open_checkpointer(checkpoint_file) as saver:
            return await _orchestrator(saver, store).resume("r01", _approve(version))

    waiting = asyncio.run(first_process())
    approved = asyncio.run(second_process(waiting["version"]))

    assert waiting["status"] == "AWAITING_APPROVAL"
    assert approved["status"] == "APPROVED"
    assert approved["approval"]["quote_hash"]
    assert approved["trace"][-1] == "await_approval"
    assert store.latest("r01")["version"] == 1


def test_edit_while_waiting_creates_version_two_and_the_old_approval_is_refused() -> None:
    store = PlanStore("sqlite://")
    edited = {**DOD_REQUEST.model_dump(mode="json"), "people": 3}

    async def scenario() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        async with open_checkpointer("memory://") as saver:
            orchestrator = _orchestrator(saver, store)
            await orchestrator.start("edit", DOD_REQUEST, owner_id=ALICE)
            after_edit = await orchestrator.resume(
                "edit", {"action": "edit", "request": edited, "user_id": ALICE}
            )
            with pytest.raises(StalePlanError):
                await orchestrator.resume("edit", _approve(1))
            approved = await orchestrator.resume("edit", _approve(2))
            return after_edit, approved, await orchestrator.state("edit")

    after_edit, approved, final = asyncio.run(scenario())

    assert after_edit["status"] == "AWAITING_APPROVAL"
    assert after_edit["version"] == 2
    assert approved["status"] == "APPROVED"
    assert approved["approval"]["plan_id"] == after_edit["plan_id"]
    assert final["waiting"] is False


def test_wrong_owner_cannot_resume_and_the_owner_still_can() -> None:
    store = PlanStore("sqlite://")

    async def scenario() -> dict[str, Any]:
        async with open_checkpointer("memory://") as saver:
            orchestrator = _orchestrator(saver, store)
            await orchestrator.start("owner", DOD_REQUEST, owner_id=ALICE)
            with pytest.raises(PermissionError):
                await orchestrator.resume("owner", _approve(1, user="bob"))
            with pytest.raises(PermissionError):
                await orchestrator.start("owner", DOD_REQUEST, owner_id="bob")
            return await orchestrator.resume("owner", _approve(1))

    assert asyncio.run(scenario())["status"] == "APPROVED"


def test_unknown_option_is_refused_and_the_plan_keeps_waiting() -> None:
    store = PlanStore("sqlite://")

    async def scenario() -> dict[str, Any]:
        async with open_checkpointer("memory://") as saver:
            orchestrator = _orchestrator(saver, store)
            await orchestrator.start("opt", DOD_REQUEST, owner_id=ALICE)
            with pytest.raises(UnknownOptionError):
                await orchestrator.resume("opt", _approve(1, option="NOPE"))
            return await orchestrator.state("opt")

    state = asyncio.run(scenario())

    assert state["waiting"] is True
    assert state["status"] == "AWAITING_APPROVAL"


def test_resume_without_a_waiting_plan_is_refused() -> None:
    store = PlanStore("sqlite://")

    async def scenario() -> None:
        async with open_checkpointer("memory://") as saver:
            orchestrator = _orchestrator(saver, store)
            await orchestrator.resume("nothing", _approve(1))

    with pytest.raises(ValueError):
        asyncio.run(scenario())
