"""Versioned plan persistence with approval invalidation."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

class Base(DeclarativeBase): pass
class Trip(Base):
    __tablename__="trips"; id: Mapped[str]=mapped_column(String,primary_key=True); thread_id: Mapped[str]=mapped_column(String,unique=True); status: Mapped[str]=mapped_column(String); created_at: Mapped[datetime]=mapped_column(DateTime)
class PlanVersion(Base):
    __tablename__="plan_versions"; id: Mapped[str]=mapped_column(String,primary_key=True); trip_id: Mapped[str]=mapped_column(ForeignKey("trips.id")); version: Mapped[int]=mapped_column(Integer); payload: Mapped[str]=mapped_column(Text); created_at: Mapped[datetime]=mapped_column(DateTime)
class Approval(Base):
    __tablename__="approvals"; id: Mapped[str]=mapped_column(String,primary_key=True); plan_id: Mapped[str]=mapped_column(ForeignKey("plan_versions.id")); approved: Mapped[bool]=mapped_column(Boolean); active: Mapped[bool]=mapped_column(Boolean,default=True)
class BookingIntent(Base):
    __tablename__="booking_intents"; id: Mapped[str]=mapped_column(String,primary_key=True); idempotency_key: Mapped[str]=mapped_column(String,unique=True); payload: Mapped[str]=mapped_column(Text)

class PlanStore:
    def __init__(self,url:str):
        self.engine=create_engine(url,connect_args={"check_same_thread":False},poolclass=StaticPool) if url == "sqlite://" else create_engine(url)
        Base.metadata.create_all(self.engine)
    def save_plan(self,thread_id:str,payload:dict)->tuple[str,int]:
        now=datetime.now(timezone.utc)
        with Session(self.engine) as s:
            trip=s.scalar(select(Trip).where(Trip.thread_id==thread_id))
            if trip is None: trip=Trip(id=str(uuid4()),thread_id=thread_id,status="AWAITING_APPROVAL",created_at=now);s.add(trip);version=1
            else:
                version=(s.scalar(select(PlanVersion.version).where(PlanVersion.trip_id==trip.id).order_by(PlanVersion.version.desc())) or 0)+1
                s.execute(update(Approval).where(Approval.plan_id.in_(select(PlanVersion.id).where(PlanVersion.trip_id==trip.id))).values(active=False));trip.status="AWAITING_APPROVAL"
            plan=PlanVersion(id=str(uuid4()),trip_id=trip.id,version=version,payload=json.dumps(payload,default=str),created_at=now);s.add(plan);s.commit();return plan.id,version
    def approve(self,plan_id:str)->None:
        with Session(self.engine) as s: s.add(Approval(id=str(uuid4()),plan_id=plan_id,approved=True,active=True));s.commit()
    def is_approved(self,plan_id:str)->bool:
        with Session(self.engine) as s: return s.scalar(select(Approval).where(Approval.plan_id==plan_id,Approval.active==True,Approval.approved==True)) is not None
    def intent(self,key:str):
        with Session(self.engine) as s:
            row=s.scalar(select(BookingIntent).where(BookingIntent.idempotency_key==key));return None if row is None else json.loads(row.payload)
    def new_intent(self,key:str)->str: return str(uuid4())
    def save_intent(self,key:str,payload:dict)->None:
        with Session(self.engine) as s: s.add(BookingIntent(id=payload["intent_id"],idempotency_key=key,payload=json.dumps(payload)));s.commit()
    def latest(self,thread_id:str):
        with Session(self.engine) as s:
            trip=s.scalar(select(Trip).where(Trip.thread_id==thread_id))
            if trip is None: return None
            plan=s.scalar(select(PlanVersion).where(PlanVersion.trip_id==trip.id).order_by(PlanVersion.version.desc()))
            return None if plan is None else {"plan_id":plan.id,"version":plan.version,"status":trip.status,"payload":json.loads(plan.payload)}
