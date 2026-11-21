"""Deterministic mock booking provider; it never makes a real reservation."""
from __future__ import annotations
from typing import Literal
from app.schemas.booking import BookingItem
MockBookingMode=Literal["success","fail","unknown"]
class MockBookingProvider:
 def __init__(self,modes:dict[str,MockBookingMode]|None=None): self.modes=modes or {}
 def book(self,offer_id:str,kind:Literal["TRANSPORT","HOTEL"])->BookingItem:
  mode=self.modes.get(offer_id,"success")
  if mode=="success": return BookingItem(offer_id=offer_id,kind=kind,status="BOOKED",source="MOCK",reference=f"mock-{offer_id}")
  return BookingItem(offer_id=offer_id,kind=kind,status="FAILED" if mode=="fail" else "UNKNOWN",source="MOCK",message="Mock provider did not confirm booking.")
