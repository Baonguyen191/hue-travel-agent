"""Approval-gated mock booking saga with durable idempotency."""
from __future__ import annotations
from app.db.store import PlanStore
from app.providers.booking_mock import MockBookingProvider
from app.schemas.booking import BookingItem, BookingResult
class BookingService:
 def __init__(self,store:PlanStore,provider:MockBookingProvider): self.store,self.provider=store,provider
 def book(self,thread_id:str,key:str)->BookingResult:
  plan=self.store.latest(thread_id)
  if not plan: raise LookupError("Plan thread was not found.")
  if not self.store.is_approved(plan["plan_id"]): raise PermissionError("Current plan version has not been approved.")
  existing=self.store.intent(key)
  if existing: return BookingResult.model_validate(existing)
  items=[]
  for offer in plan["payload"]["search"]["transport_offers"]: items.append(self.provider.book(offer["id"],"TRANSPORT"))
  for offer in plan["payload"]["search"]["hotel_offers"]: items.append(self.provider.book(offer["id"],"HOTEL"))
  states={x.status for x in items}
  status="BOOKED" if states=={"BOOKED"} else "PARTIALLY_BOOKED" if "BOOKED" in states else ("UNKNOWN" if "UNKNOWN" in states else "FAILED")
  result=BookingResult(intent_id=self.store.new_intent(key),status=status,items=items,plan_version=plan["version"])
  self.store.save_intent(key,result.model_dump(mode="json"));return result
