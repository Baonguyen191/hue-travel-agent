"""Test validator của ParsedQuery và các schema phụ."""

import datetime as dt

import pytest
from pydantic import ValidationError

from travel_agent.domain.models import Category, PlanRequest
from travel_agent.understanding.models import DurationSpec, Intent, ParsedQuery, PlaceMention

REQUEST = PlanRequest(start_date=dt.date(2026, 11, 21), num_days=2)


def test_intent_values_match_plan_spec() -> None:
    assert {item.value for item in Intent} == {
        "plan_new",
        "modify_plan",
        "place_info",
        "out_of_scope",
    }


def test_plan_new_with_request_is_valid() -> None:
    query = ParsedQuery(intent=Intent.PLAN_NEW, request=REQUEST)
    assert query.request == REQUEST
    assert query.clarification is None


def test_plan_new_with_only_clarification_is_valid() -> None:
    query = ParsedQuery(intent=Intent.PLAN_NEW, clarification="Bạn đi ngày nào?")
    assert query.request is None


def test_plan_new_without_request_or_clarification_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ParsedQuery(intent=Intent.PLAN_NEW)


def test_plan_new_with_blank_clarification_and_no_request_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ParsedQuery(intent=Intent.PLAN_NEW, clarification="")


def test_out_of_scope_without_request_is_valid() -> None:
    query = ParsedQuery(intent=Intent.OUT_OF_SCOPE)
    assert query.request is None


def test_out_of_scope_with_request_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ParsedQuery(intent=Intent.OUT_OF_SCOPE, request=REQUEST)


@pytest.mark.parametrize("intent", [Intent.MODIFY_PLAN, Intent.PLACE_INFO])
def test_other_intents_need_no_request(intent: Intent) -> None:
    assert ParsedQuery(intent=intent).request is None


def test_defaults_are_empty_lists() -> None:
    query = ParsedQuery(intent=Intent.PLAN_NEW, request=REQUEST)
    assert query.must_include == []
    assert query.exclude == []
    assert query.exclude_categories == []
    assert query.soft_preferences == []
    assert query.defaulted == []
    assert query.date_text is None


def test_exclude_categories_accepts_category_and_rejects_unknown_value() -> None:
    query = ParsedQuery(
        intent=Intent.PLAN_NEW,
        request=REQUEST,
        exclude_categories=[Category.MARKET],
    )
    assert query.exclude_categories == [Category.MARKET]
    with pytest.raises(ValidationError):
        ParsedQuery(intent=Intent.PLAN_NEW, request=REQUEST, exclude_categories=["bar"])


def test_place_mention_score_must_be_between_0_and_1() -> None:
    assert PlaceMention(text="Đại Nội", place_id=None, score=0.0).score == 0.0
    assert PlaceMention(text="Đại Nội", place_id="p1", score=1.0).place_id == "p1"
    with pytest.raises(ValidationError):
        PlaceMention(text="Đại Nội", place_id=None, score=1.2)
    with pytest.raises(ValidationError):
        PlaceMention(text="Đại Nội", place_id=None, score=-0.1)


def test_place_mention_text_must_not_be_empty() -> None:
    with pytest.raises(ValidationError):
        PlaceMention(text="", place_id=None, score=0.5)


def test_duration_spec_requires_at_least_one_day() -> None:
    assert DurationSpec(num_days=2, half_day=False).num_days == 2
    with pytest.raises(ValidationError):
        DurationSpec(num_days=0, half_day=False)
