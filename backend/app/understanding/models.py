"""Schema of a understood chat query (ParsedQuery) and of changes to an existing plan.

The LLM only copies phrases (dates, durations, place names, preferences). Code resolves
them, so these models hold resolved values and the rules that tie intent to request.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.place import PlaceCategory
from app.schemas.request import TripRequest


class Intent(StrEnum):
    """What the user wants from the chat turn."""

    PLAN_NEW = "plan_new"
    MODIFY_PLAN = "modify_plan"
    PLACE_INFO = "place_info"
    APPROVE = "approve"
    BOOK = "book"
    OUT_OF_SCOPE = "out_of_scope"


class ApproveOption(StrEnum):
    """Budget option the user approves."""

    BUDGET = "BUDGET"
    BALANCED = "BALANCED"
    COMFORT = "COMFORT"


class QuSource(StrEnum):
    """Which understanding path produced the result."""

    OLLAMA = "OLLAMA"
    RULES = "RULES"


class PlanChangeKind(StrEnum):
    """Kinds of edit a user can ask for on an existing plan."""

    ADD_DAYS = "add_days"
    REMOVE_DAYS = "remove_days"
    SET_DATES = "set_dates"
    SET_PEOPLE = "set_people"
    SET_BUDGET = "set_budget"
    CHEAPER = "cheaper"
    ADD_PLACE = "add_place"
    REMOVE_PLACE = "remove_place"
    EXCLUDE_CATEGORY = "exclude_category"
    INCLUDE_CATEGORY = "include_category"
    SET_HOTEL_TIER = "set_hotel_tier"
    OTHER = "other"


class DurationSpec(BaseModel):
    """Number of days read from a phrase. half_day means half a day or one session (num_days 1)."""

    model_config = ConfigDict(frozen=True)

    num_days: int = Field(ge=1)
    half_day: bool = False


class PlaceMention(BaseModel):
    """A place name the user wrote, linked to a POI id when the link is confident enough."""

    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1)
    poi_id: str | None = None
    name: str | None = None
    score: float = Field(ge=0.0, le=1.0)


class PlanChange(BaseModel):
    """One requested edit to an existing plan; value is a number, a poi id or a short text."""

    model_config = ConfigDict(frozen=True)

    kind: PlanChangeKind
    value: str | int | None = None
    text: str = ""


class ParsedQuery(BaseModel):
    """Result of understanding one user message. Fields are JSON-friendly when dumped."""

    intent: Intent
    request: TripRequest | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    date_text: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    clarification: str | None = None
    quick_replies: list[str] = Field(default_factory=list)
    must_include: list[PlaceMention] = Field(default_factory=list)
    exclude: list[PlaceMention] = Field(default_factory=list)
    exclude_categories: list[PlaceCategory] = Field(default_factory=list)
    soft_preferences: list[str] = Field(default_factory=list)
    changes: list[PlanChange] = Field(default_factory=list)
    place_query: PlaceMention | None = None
    approve_option: ApproveOption | None = None
    source: QuSource = QuSource.RULES
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _intent_matches_fields(self) -> ParsedQuery:
        if self.intent is Intent.PLAN_NEW and self.request is None and not self.clarification:
            raise ValueError("plan_new needs a request or a clarification")
        if self.intent is Intent.OUT_OF_SCOPE and self.request is not None:
            raise ValueError("out_of_scope must not carry a request")
        return self
