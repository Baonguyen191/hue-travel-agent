"""Trip-request parsing: Vietnamese rules first, OpenAI only to fill missing required fields.

Without `OPENAI_API_KEY` the OpenAI step is skipped entirely, so the rule result is final.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from openai import OpenAI

from app.core.config import openai_api_key
from app.schemas.parsed_trip import ParsedTrip
from app.services.poi_search import normalize_vietnamese
from app.services.vi_request_parser import (
    CITY_NAMES,
    REQUIRED_FIELDS,
    derive_end_date,
    finalize_parsed,
    parse_vietnamese_request,
)

__all__ = ["ParsedTrip", "TripRequestParser"]

_OPENAI_MODEL = "gpt-4.1-mini"
_DATE_FIELDS = frozenset({"start_date", "end_date"})
_CITY_FIELDS = frozenset({"origin", "destination"})
_SYSTEM_PROMPT = (
    "Extract a Vietnam travel request. Return JSON only. Never invent a value: "
    "use null when the text does not state it."
)


class TripRequestParser:
    """Rules first; the OpenAI call runs only when a key exists and fields are still missing."""

    def parse(self, text: str, today: date | None = None) -> ParsedTrip:
        parsed = parse_vietnamese_request(text, today or date.today())
        key = openai_api_key()
        if not parsed.missing_fields or not key:
            return parsed
        try:
            extra = _ask_openai(text, key, parsed.missing_fields)
        except Exception:
            return parsed
        return _fill_missing(parsed, extra)


def _fill_missing(parsed: ParsedTrip, extra: dict[str, Any]) -> ParsedTrip:
    """Copy OpenAI values into the fields the rules left missing; never override a rule value."""
    fields = dict(parsed.fields)
    gained = False
    for name in parsed.missing_fields:
        value = _coerce(name, extra.get(name))
        if value is not None:
            fields[name] = value
            gained = True
    if not gained:
        return parsed
    derive_end_date(fields)
    return finalize_parsed(fields, list(parsed.notes), "RULES+OPENAI")


def _coerce(name: str, value: Any) -> Any:
    """Turn one OpenAI value into the Python type the request needs, or None when unusable."""
    if value is None or value == "":
        return None
    if name in _DATE_FIELDS:
        return _iso_date(value)
    if name == "people":
        return _positive_int(value)
    if name in _CITY_FIELDS:
        return _city_name(str(value))
    return None


def _iso_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _positive_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _city_name(value: str) -> str:
    return CITY_NAMES.get(normalize_vietnamese(value), value.strip())


def _ask_openai(text: str, key: str, missing: list[str]) -> dict[str, Any]:
    """Ask OpenAI for the trip fields as strict JSON. Only the caller decides which values to keep."""
    schema = _schema()
    prompt = f"{_SYSTEM_PROMPT} Fill only these fields, others null: {', '.join(missing)}."
    response = OpenAI(api_key=key).responses.create(
        model=_OPENAI_MODEL,
        input=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ],
        text={"format": {"type": "json_schema", "name": "trip_request", "strict": True, "schema": schema}},
    )
    return json.loads(response.output_text)


def _schema() -> dict[str, Any]:
    nullable_string = {"type": ["string", "null"]}
    return {
        "type": "object",
        "properties": {
            "origin": nullable_string,
            "destination": nullable_string,
            "start_date": nullable_string,
            "end_date": nullable_string,
            "people": {"type": ["integer", "null"]},
        },
        "required": list(REQUIRED_FIELDS),
        "additionalProperties": False,
    }
