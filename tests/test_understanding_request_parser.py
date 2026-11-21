"""TripRequestParser on top of understand(): the extractor is patched, never networked."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))

import datetime as dt  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402

from app.services import request_parser  # noqa: E402
from app.services.request_parser import TripRequestParser  # noqa: E402
from app.understanding.extract import ExtractionError, Extraction  # noqa: E402

TODAY = dt.date(2026, 11, 18)


class _FixedExtractor:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def extract(self, text: str, ref: dt.date) -> Extraction:
        return Extraction.model_validate(self.payload)


class _DownExtractor:
    def extract(self, text: str, ref: dt.date) -> Extraction:
        raise ExtractionError("Ollama không trả lời")


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "intent": "plan_new",
        "date_text": "20/12",
        "duration_text": "2 ngày",
        "origin": None,
        "people": 2,
        "rooms": None,
        "budget_text": None,
        "city": None,
        "interest_phrases": ["đi chùa"],
        "must_include_mentions": [],
        "exclude_mentions": [],
        "exclude_category_phrases": [],
        "soft_preferences": [],
        "changes": [],
        "approve_option": None,
    }
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def _no_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(request_parser, "openai_api_key", lambda: None)


def test_llm_result_is_reported_as_ollama_with_a_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(request_parser, "_shared_extractor", lambda: _FixedExtractor(_payload()))

    parsed = TripRequestParser().parse("Đi Huế 2 ngày từ 20/12, 2 người, thích đi chùa", today=TODAY)

    assert parsed.source == "OLLAMA"
    assert parsed.request is not None
    assert parsed.request.start_date == dt.date(2026, 12, 20)
    assert parsed.request.categories == ["religious"]
    assert parsed.fields["destination"] == "Huế"


def test_llm_outage_falls_back_to_rules_with_the_same_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(request_parser, "_shared_extractor", lambda: _DownExtractor())

    parsed = TripRequestParser().parse("Đi Huế 2 ngày từ 20/12, 2 người", today=TODAY)

    assert parsed.source == "RULES"
    assert parsed.request is not None
    assert any("Ollama không dùng được" in note for note in parsed.notes)


def test_missing_start_date_is_form_fallback_and_lists_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(request_parser, "_shared_extractor", lambda: None)

    parsed = TripRequestParser().parse("Đi Huế 2 ngày, thích lăng tẩm", today=TODAY)

    assert parsed.source == "FORM_FALLBACK"
    assert parsed.request is None
    assert "start_date" in parsed.missing_fields
    assert parsed.notes
