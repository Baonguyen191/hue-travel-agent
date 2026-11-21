"""TripRequestParser: rules first, OpenAI only to fill missing required fields. Never networked."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import request_parser  # noqa: E402
from app.services.request_parser import ParsedTrip, TripRequestParser  # noqa: E402

TODAY = date(2026, 11, 21)
DOD_TEXT = (
    "Tôi đi Huế 3 ngày 2 đêm, xuất phát Hà Nội, 2 người, "
    "ngân sách 6 triệu, thích di tích và đặc sản"
)
COMPLETE_TEXT = DOD_TEXT.replace("Tôi đi Huế", "Tôi đi Huế 05/12")


def _forbidden_openai(text: str, key: str, missing: list[str]) -> dict[str, Any]:
    raise AssertionError("OpenAI must not be called in this test")


def test_without_a_key_only_rules_run_and_the_form_fallback_lists_missing(monkeypatch) -> None:
    monkeypatch.setattr(request_parser, "openai_api_key", lambda: None)
    monkeypatch.setattr(request_parser, "_ask_openai", _forbidden_openai)

    parsed = TripRequestParser().parse(DOD_TEXT, today=TODAY)

    assert isinstance(parsed, ParsedTrip)
    assert parsed.request is None
    assert parsed.source == "FORM_FALLBACK"
    assert parsed.fields["destination"] == "Huế"
    assert {"start_date", "end_date"} <= set(parsed.missing_fields)


def test_complete_rules_never_call_openai_even_with_a_key(monkeypatch) -> None:
    monkeypatch.setattr(request_parser, "openai_api_key", lambda: "test-key")
    monkeypatch.setattr(request_parser, "_ask_openai", _forbidden_openai)

    parsed = TripRequestParser().parse(COMPLETE_TEXT, today=TODAY)

    assert parsed.source == "RULES"
    assert parsed.request is not None
    assert parsed.request.end_date == date(2026, 12, 7)


def test_openai_fills_only_missing_fields_and_never_overrides_rules(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_openai(text: str, key: str, missing: list[str]) -> dict[str, Any]:
        calls.append(missing)
        return {
            "origin": "Sài Gòn",
            "destination": "Đà Nẵng",
            "start_date": "2026-12-05",
            "end_date": "2026-12-07",
            "people": 9,
        }

    monkeypatch.setattr(request_parser, "openai_api_key", lambda: "test-key")
    monkeypatch.setattr(request_parser, "_ask_openai", fake_openai)
    text = "Tôi đi Huế 3 ngày 2 đêm, 2 người"

    parsed = TripRequestParser().parse(text, today=TODAY)

    assert calls and "origin" in calls[0]
    assert parsed.fields["destination"] == "Huế"
    assert parsed.fields["people"] == 2
    assert parsed.fields["origin"] == "TP. Hồ Chí Minh"
    assert parsed.source == "RULES+OPENAI"
    assert parsed.request is not None
    assert parsed.request.start_date == date(2026, 12, 5)


def test_openai_failure_keeps_the_rules_result(monkeypatch) -> None:
    def broken(text: str, key: str, missing: list[str]) -> dict[str, Any]:
        raise RuntimeError("network down")

    monkeypatch.setattr(request_parser, "openai_api_key", lambda: "test-key")
    monkeypatch.setattr(request_parser, "_ask_openai", broken)

    parsed = TripRequestParser().parse(DOD_TEXT, today=TODAY)

    assert parsed.source == "FORM_FALLBACK"
    assert parsed.fields["people"] == 2
    assert parsed.request is None


@pytest.mark.parametrize("bad_value", [None, "không phải ngày", ""])
def test_openai_bad_values_are_ignored(monkeypatch, bad_value) -> None:
    def odd(text: str, key: str, missing: list[str]) -> dict[str, Any]:
        return {"start_date": bad_value, "end_date": bad_value, "origin": bad_value}

    monkeypatch.setattr(request_parser, "openai_api_key", lambda: "test-key")
    monkeypatch.setattr(request_parser, "_ask_openai", odd)

    parsed = TripRequestParser().parse(DOD_TEXT, today=TODAY)

    assert "start_date" not in parsed.fields
    assert parsed.request is None
