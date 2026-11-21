"""Result of parsing a natural-language trip request.

Lives in `schemas` so the rule parser and `TripRequestParser` can both use it without
importing each other. `request_parser` re-exports it.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.request import TripRequest


class ParsedTrip(BaseModel):
    """A request when every required field is known; otherwise what is missing."""

    request: TripRequest | None = None
    missing_fields: list[str] = Field(default_factory=list)
    source: str
    fields: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
