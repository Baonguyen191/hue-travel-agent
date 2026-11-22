"""Gold sets: schema validation, split selection and integrity of the real v1 JSONL files."""

from __future__ import annotations

import sys as _sys
from collections import Counter
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.core.config import hue_database_path  # noqa: E402
from app.evaluation.gold import (  # noqa: E402
    RAG_EVAL_FILE,
    SCENARIO_FILE,
    RagItem,
    Scenario,
    load_jsonl,
)
from app.repositories.hue_places import HuePlacesRepository  # noqa: E402


def _rag_line(item_id: str, split: str = "dev", group: str = "single_place") -> str:
    return (
        '{"id": "%s", "split": "%s", "group": "%s", "question": "Q?", '
        '"relevant_poi_ids": ["huetripo:1"], "reference_answer": "A."}' % (item_id, split, group)
    )


def _scenario_payload(turns: list[str], handlers: list[str]) -> dict:
    return {
        "id": "s99",
        "split": "dev",
        "group": "plan_full",
        "turns": turns,
        "expect": {
            "handlers": handlers,
            "final_state": "awaiting_approval",
            "trace": None,
            "tools_called": ["poi_search"],
            "tools_not_called": [],
            "budget": None,
            "constraints": None,
        },
    }


def test_load_jsonl_round_trip(tmp_path: _Path) -> None:
    path = tmp_path / "rag.jsonl"
    path.write_text(_rag_line("a1") + "\n\n" + _rag_line("a2", "test") + "\n", encoding="utf-8")

    items = load_jsonl(path, RagItem, "all")

    assert [item.id for item in items] == ["a1", "a2"]
    assert items[0] == RagItem(
        id="a1",
        split="dev",
        group="single_place",
        question="Q?",
        relevant_poi_ids=["huetripo:1"],
        reference_answer="A.",
    )


def test_load_jsonl_split_selection(tmp_path: _Path) -> None:
    path = tmp_path / "rag.jsonl"
    path.write_text(_rag_line("a1", "dev") + "\n" + _rag_line("a2", "test") + "\n", encoding="utf-8")

    assert [item.id for item in load_jsonl(path, RagItem, "dev")] == ["a1"]
    assert [item.id for item in load_jsonl(path, RagItem, "test")] == ["a2"]
    assert len(load_jsonl(path, RagItem, "all")) == 2


def test_load_jsonl_rejects_unknown_split(tmp_path: _Path) -> None:
    path = tmp_path / "rag.jsonl"
    path.write_text(_rag_line("a1") + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        load_jsonl(path, RagItem, "validation")


def test_rag_item_rejects_unknown_group() -> None:
    with pytest.raises(ValidationError):
        RagItem(
            id="x",
            split="dev",
            group="nearby",  # type: ignore[arg-type]
            question="Q?",
            relevant_poi_ids=[],
            reference_answer="A.",
        )


def test_scenario_handler_count_must_match_turns() -> None:
    with pytest.raises(ValidationError):
        Scenario.model_validate(_scenario_payload(["one", "two"], ["plan_new"]))


def test_scenario_accepts_matching_handler_count() -> None:
    scenario = Scenario.model_validate(_scenario_payload(["one", "two"], ["plan_new", "modify"]))

    assert scenario.expect.handlers == ["plan_new", "modify"]
    assert scenario.expect.tools_not_called == []
    assert scenario.expect.budget is None


def test_real_rag_eval_file_is_valid() -> None:
    items = load_jsonl(RAG_EVAL_FILE, RagItem, "all")
    repo = HuePlacesRepository(hue_database_path())

    assert len(items) == 60
    ids = [item.id for item in items]
    assert len(set(ids)) == len(ids)

    dev = [item for item in items if item.split == "dev"]
    test = [item for item in items if item.split == "test"]
    assert (len(dev), len(test)) == (40, 20)

    for item in items:
        if item.group == "unanswerable":
            assert item.relevant_poi_ids == [], item.id
        else:
            assert item.relevant_poi_ids, item.id
        for poi_id in item.relevant_poi_ids:
            assert repo.get_by_id(poi_id) is not None, (item.id, poi_id)


def test_real_scenario_file_is_valid() -> None:
    scenarios = load_jsonl(SCENARIO_FILE, Scenario, "all")
    repo = HuePlacesRepository(hue_database_path())

    assert len(scenarios) == 40
    ids = [scenario.id for scenario in scenarios]
    assert len(set(ids)) == len(ids)

    splits = Counter(scenario.split for scenario in scenarios)
    assert (splits["dev"], splits["test"]) == (25, 15)

    for scenario in scenarios:
        constraints = scenario.expect.constraints
        if constraints is None:
            continue
        for poi_id in [*constraints.must_include, *constraints.exclude]:
            assert repo.get_by_id(poi_id) is not None, (scenario.id, poi_id)
