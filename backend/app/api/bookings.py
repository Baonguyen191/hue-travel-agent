from fastapi import APIRouter,HTTPException
from app.api.plans import store
from app.providers.booking_mock import MockBookingProvider
from app.schemas.booking import BookingRequest,BookingResult
from app.services.booking_service import BookingService
router=APIRouter(prefix="/api/v1/plans",tags=["bookings"])
@router.post("/{thread_id}/book",response_model=BookingResult)
def book(thread_id:str,body:BookingRequest):
 try:return BookingService(store,MockBookingProvider()).book(thread_id,body.idempotency_key)
 except LookupError as e:raise HTTPException(404,str(e))
 except PermissionError as e:raise HTTPException(409,str(e))
