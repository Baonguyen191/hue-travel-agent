"""Structured trip-request extraction with a safe no-guess fallback."""
from __future__ import annotations
from datetime import date
from pydantic import BaseModel, Field
from openai import OpenAI
from app.core.config import openai_api_key
from app.schemas.request import TripRequest

class ParsedTrip(BaseModel):
    request: TripRequest | None = None
    missing_fields: list[str] = Field(default_factory=list)
    source: str

class TripRequestParser:
    def parse(self, text: str) -> ParsedTrip:
        key=openai_api_key()
        if not key:
            return ParsedTrip(source="FORM_FALLBACK",missing_fields=["origin","start_date","end_date","people"])
        schema={"type":"object","properties":{"origin":{"type":"string"},"destination":{"type":"string"},"start_date":{"type":"string"},"end_date":{"type":"string"},"people":{"type":"integer"}},"required":["origin","destination","start_date","end_date","people"],"additionalProperties":False}
        try:
            response=OpenAI(api_key=key).responses.create(model="gpt-4.1-mini",input=[{"role":"system","content":"Extract a Vietnam travel request. Return JSON only; never invent missing values."},{"role":"user","content":text}],text={"format":{"type":"json_schema","name":"trip_request","strict":True,"schema":schema}})
            import json
            data=json.loads(response.output_text)
            return ParsedTrip(request=TripRequest(**data),source="OPENAI_STRUCTURED_OUTPUT")
        except Exception:
            return ParsedTrip(source="FORM_FALLBACK",missing_fields=["origin","start_date","end_date","people"])
