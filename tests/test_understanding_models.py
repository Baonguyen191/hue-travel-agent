"""Tests for the ParsedQuery schema and its intent/request rules."""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

import sys as _sys
from pathlib import Path as _Path
_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))

from app.schemas.request import TripRequest
from app.understanding.models import (
    Intent,
    ParsedQuery,
    PlaceMention,
    PlanChange,
    PlanChangeKind,
)

REQUEST = TripRequest(
    origin="Huế",
    destination="Huế",
    start_date=dt.date(2026, 11, 21),
    end_date=dt.date(2026, 11, 22),
    people=2,
)


def test_intent_values_match_spec() -> None:
    assert {item.value for item in Intent} == {
        "plan_new",
        "modify_plan",
        "place_info",
        "approve",
        "book",
        "out_of_scope",
        "smalltalk",
    }


def test_plan_new_with_request_is_valid() -> None:
    query = ParsedQuery(intent=Intent.PLAN_NEW, request=REQUEST)
    assert query.request == REQUEST


def test_plan_new_with_only_clarification_is_valid() -> None:
    query = ParsedQuery(intent=Intent.PLAN_NEW, clarification="Bạn đi từ ngày nào?")
    assert query.request is None


def test_plan_new_without_request_or_clarification_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ParsedQuery(intent=Intent.PLAN_NEW)


def test_plan_new_with_blank_clarification_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ParsedQuery(intent=Intent.PLAN_NEW, clarification="")


def test_out_of_scope_with_request_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ParsedQuery(intent=Intent.OUT_OF_SCOPE, request=REQUEST)


@pytest.mark.parametrize(
    "intent", [Intent.MODIFY_PLAN, Intent.PLACE_INFO, Intent.APPROVE, Intent.BOOK]
)
def test_other_intents_need_no_request(intent: Intent) -> None:
    assert ParsedQuery(intent=intent).request is None


def test_defaults_are_empty() -> None:
    query = ParsedQuery(intent=Intent.OUT_OF_SCOPE)
    assert query.must_include == []
    assert query.exclude == []
    assert query.exclude_categories == []
    assert query.changes == []
    assert query.quick_replies == []
    assert query.fields == {}


def test_place_mention_score_must_be_between_0_and_1() -> None:
    with pytest.raises(ValidationError):
        PlaceMention(text="Đại Nội", score=1.5)


def test_place_mention_text_must_not_be_empty() -> None:
    with pytest.raises(ValidationError):
        PlaceMention(text="", score=0.5)


def test_plan_change_keeps_kind_value_and_text() -> None:
    change = PlanChange(kind=PlanChangeKind.ADD_DAYS, value=1, text="thêm 1 ngày")
    assert change.kind is PlanChangeKind.ADD_DAYS
    assert change.value == 1
