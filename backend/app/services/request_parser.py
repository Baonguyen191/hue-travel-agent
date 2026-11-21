"""Trip-request parsing: query understanding first, OpenAI only to fill missing required fields.

`understand()` uses the local Ollama model when `QU_ENABLED` is on and falls back to the
Vietnamese rule parser otherwise. The OpenAI step runs only when no request could be built and a
key exists; without a key the understanding result is final.
"""

from __future__ import annotations

import functools
import json
from datetime import date
from typing import Any

from openai import OpenAI

from app.core.config import ollama_url, openai_api_key, qu_enabled, qu_model
from app.schemas.parsed_trip import ParsedTrip
from app.services.poi_search import normalize_vietnamese
from app.services.vi_request_parser import (
    CITY_NAMES,
    REQUIRED_FIELDS,
    derive_end_date,
    finalize_parsed,
)
from app.understanding.extract import OllamaExtractor
from app.understanding.models import ParsedQuery, QuSource
from app.understanding.understand import Extractor, understand

__all__ = ["ParsedTrip", "TripRequestParser"]

_OPENAI_MODEL = "gpt-4.1-mini"
_DATE_FIELDS = frozenset({"start_date", "end_date"})
_CITY_FIELDS = frozenset({"origin", "destination"})
_SYSTEM_PROMPT = (
    "Extract a Vietnam travel request. Return JSON only. Never invent a value: "
    "use null when the text does not state it."
)


@functools.cache
def _shared_extractor() -> Extractor | None:
    """One Ollama client per process; None when the LLM step is switched off."""
    if not qu_enabled():
        return None
    return OllamaExtractor(ollama_url(), qu_model())


class TripRequestParser:
    """Understanding first; the OpenAI call runs only when no request exists and a key does."""

    def parse(self, text: str, today: date | None = None) -> ParsedTrip:
        query = understand(text, today or date.today(), extractor=_shared_extractor())
        parsed = _to_parsed_trip(query)
        key = openai_api_key()
        if parsed.request is not None or not parsed.missing_fields or not key:
            return parsed
        try:
            extra = _ask_openai(text, key, parsed.missing_fields)
        except Exception:
            return parsed
        return _fill_missing(parsed, extra)


def _to_parsed_trip(query: ParsedQuery) -> ParsedTrip:
    """The response shape of /plans/parse, built from a ParsedQuery."""
    notes = list(query.notes)
    if query.request is None and query.clarification:
        notes.append(query.clarification)
    if query.request is not None:
        source = "OLLAMA" if query.source is QuSource.OLLAMA else "RULES"
    else:
        source = "FORM_FALLBACK"
    return ParsedTrip(
        request=query.request,
        missing_fields=list(query.missing_fields),
        source=source,
        fields=dict(query.fields),
        notes=notes,
    )


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
