"""Mock-only booking contracts with explicit saga outcomes."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
BookingStatus=Literal["PENDING","BOOKED","FAILED","UNKNOWN","PARTIALLY_BOOKED","RECONFIRM_REQUIRED"]
class BookingRequest(BaseModel): idempotency_key:str=Field(min_length=8,max_length=200)
class BookingItem(BaseModel): offer_id:str; kind:Literal["TRANSPORT","HOTEL"]; status:BookingStatus; source:Literal["MOCK"]; reference:str|None=None; message:str|None=None
class BookingResult(BaseModel): intent_id:str; status:BookingStatus; items:list[BookingItem]; plan_version:int; source:Literal["MOCK"]="MOCK"
