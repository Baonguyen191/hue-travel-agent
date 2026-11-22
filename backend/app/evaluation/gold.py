"""Gold-set schemas and JSONL loaders for the RAG and chat-scenario evaluations."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

from app.core.config import PROJECT_ROOT

EVAL_DIR = PROJECT_ROOT / "data" / "eval"
RAG_EVAL_FILE = EVAL_DIR / "rag_eval_v1.jsonl"
SCENARIO_FILE = EVAL_DIR / "scenarios_v1.jsonl"

Split = Literal["dev", "test"]
Tool = Literal["transport", "hotel", "booking", "poi_search", "rag"]
Handler = Literal[
    "plan_new",
    "modify",
    "place_info",
    "ask_approve",
    "ask_book",
    "out_of_scope",
    "confirm_defaults",
    "run_approve",
    "run_book",
    "cancel",
]
FinalState = Literal[
    "awaiting_approval",
    "approved",
    "booked",
    "answered",
    "clarifying",
    "confirming",
    "refused",
    "failed",
]
RagGroup = Literal["single_place", "near_place", "by_category", "unanswerable"]

_T = TypeVar("_T", bound=BaseModel)


class RagItem(BaseModel):
    """One RAG question with its gold POIs and a reference answer."""

    id: str
    split: Split
    group: RagGroup
    question: str
    relevant_poi_ids: list[str] = Field(default_factory=list)
    reference_answer: str


class BudgetExpect(BaseModel):
    """Expected budget for a scenario and whether it is feasible."""

    budget_vnd: int
    feasible: bool


class ConstraintExpect(BaseModel):
    """Expected parsed constraints for a scenario."""

    must_include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    exclude_categories: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    num_days: int | None = None
    start_date: date | None = None


class ScenarioExpect(BaseModel):
    """Expected routing, tool use and end state for a multi-turn scenario."""

    handlers: list[Handler]
    final_state: FinalState
    trace: list[str] | None = None
    tools_called: list[Tool] = Field(default_factory=list)
    tools_not_called: list[Tool] = Field(default_factory=list)
    budget: BudgetExpect | None = None
    constraints: ConstraintExpect | None = None


class Scenario(BaseModel):
    """A multi-turn chat scenario; each turn is routed to exactly one handler."""

    id: str
    split: Split
    group: str
    turns: list[str]
    expect: ScenarioExpect

    @model_validator(mode="after")
    def _handlers_match_turns(self) -> Scenario:
        """Require one expected handler per user turn."""
        if len(self.expect.handlers) != len(self.turns):
            raise ValueError(
                f"scenario {self.id}: {len(self.expect.handlers)} handlers for {len(self.turns)} turns"
            )
        return self


def load_jsonl(path: Path, model: type[_T], split: str) -> list[_T]:
    """Load one model per non-blank line, keeping only ``split`` ("all" keeps every row)."""
    if split not in ("all", "dev", "test"):
        raise ValueError(f"unknown split: {split!r}")
    rows: list[_T] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = model.model_validate(json.loads(line))
            if split == "all" or getattr(row, "split", None) == split:
                rows.append(row)
    return rows
