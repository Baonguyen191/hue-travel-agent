"""Plan, approval and booking-intent persistence.

Each public method opens its own short session. Production schemas come from the
Alembic migrations (`app.db.migrate`); `create_all` runs only for the in-memory
SQLite used by tests and demos, or when a caller passes `create_schema=True`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
    select,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

DEFAULT_OWNER = "anonymous"
AWAITING_APPROVAL = "AWAITING_APPROVAL"


class Base(DeclarativeBase):
    """Declarative base shared by the plan store tables."""


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    thread_id: Mapped[str] = mapped_column(String, unique=True)
    owner_id: Mapped[str] = mapped_column(String, default=DEFAULT_OWNER)
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class PlanVersion(Base):
    __tablename__ = "plan_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id"))
    version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plan_versions.id"))
    option: Mapped[str] = mapped_column(String)
    quote_hash: Mapped[str] = mapped_column(String)
    selected_offers: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class BookingIntent(Base):
    __tablename__ = "booking_intents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id"))
    status: Mapped[str] = mapped_column(String)
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_engine(url: str) -> Engine:
    if url == "sqlite://":
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url)


def _check_owner(trip: Trip, owner_id: str) -> None:
    if trip.owner_id != owner_id:
        raise PermissionError("owner: plan thread belongs to another user")


def _next_version(session: Session, trip_id: str) -> int:
    current = session.scalar(select(func.max(PlanVersion.version)).where(PlanVersion.trip_id == trip_id))
    return (current or 0) + 1


def _deactivate_trip_approvals(session: Session, trip_id: str) -> None:
    plan_ids = select(PlanVersion.id).where(PlanVersion.trip_id == trip_id)
    session.execute(update(Approval).where(Approval.plan_id.in_(plan_ids)).values(active=False))


def _approval_dict(row: Approval) -> dict[str, Any]:
    return {
        "approval_id": row.id,
        "plan_id": row.plan_id,
        "option": row.option,
        "quote_hash": row.quote_hash,
        "selected_offers": json.loads(row.selected_offers),
    }


class PlanStore:
    """Versioned plans, active approvals and idempotent booking intents."""

    def __init__(self, url: str, create_schema: bool | None = None) -> None:
        """Open the engine; `create_schema=None` creates tables only for `sqlite://` (in memory)."""
        self.engine = _make_engine(url)
        if create_schema is None:
            create_schema = url == "sqlite://"
        if create_schema:
            Base.metadata.create_all(self.engine)

    def save_plan(
        self, thread_id: str, payload: dict[str, Any], owner_id: str = DEFAULT_OWNER
    ) -> tuple[str, int]:
        """Store a new plan version; a new version invalidates earlier approvals."""
        now = _utcnow()
        plan_id = str(uuid4())
        with Session(self.engine) as session:
            trip = session.scalar(select(Trip).where(Trip.thread_id == thread_id))
            if trip is None:
                trip = Trip(
                    id=str(uuid4()),
                    thread_id=thread_id,
                    owner_id=owner_id,
                    status=AWAITING_APPROVAL,
                    created_at=now,
                )
                session.add(trip)
                version = 1
            else:
                _check_owner(trip, owner_id)
                version = _next_version(session, trip.id)
                _deactivate_trip_approvals(session, trip.id)
                trip.status = AWAITING_APPROVAL
            session.add(
                PlanVersion(
                    id=plan_id,
                    trip_id=trip.id,
                    version=version,
                    payload=json.dumps(payload, default=str),
                    created_at=now,
                )
            )
            session.commit()
        return plan_id, version

    def latest(self, thread_id: str) -> dict[str, Any] | None:
        """Return the newest plan version of a thread, with its owner and trip ids."""
        with Session(self.engine) as session:
            trip = session.scalar(select(Trip).where(Trip.thread_id == thread_id))
            if trip is None:
                return None
            plan = session.scalar(
                select(PlanVersion)
                .where(PlanVersion.trip_id == trip.id)
                .order_by(PlanVersion.version.desc())
            )
            if plan is None:
                return None
            return {
                "thread_id": thread_id,
                "trip_id": trip.id,
                "owner_id": trip.owner_id,
                "plan_id": plan.id,
                "version": plan.version,
                "status": trip.status,
                "payload": json.loads(plan.payload),
            }

    def approve(
        self,
        plan_id: str,
        option: str,
        quote_hash: str,
        selected_offers: list[dict[str, Any]],
    ) -> str:
        """Record an approval for one plan version; older approvals of it go inactive."""
        approval_id = str(uuid4())
        with Session(self.engine) as session:
            session.execute(
                update(Approval)
                .where(Approval.plan_id == plan_id, Approval.active.is_(True))
                .values(active=False)
            )
            session.add(
                Approval(
                    id=approval_id,
                    plan_id=plan_id,
                    option=option,
                    quote_hash=quote_hash,
                    selected_offers=json.dumps(selected_offers),
                    active=True,
                    created_at=_utcnow(),
                )
            )
            session.commit()
        return approval_id

    def active_approval(self, plan_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = session.scalar(
                select(Approval).where(Approval.plan_id == plan_id, Approval.active.is_(True))
            )
            return None if row is None else _approval_dict(row)

    def claim_intent(
        self, idempotency_key: str, trip_id: str, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        """Insert the intent row first; the unique key makes exactly one caller the winner.

        Returns (stored payload, True) for the winner, or (existing payload, False).
        """
        now = _utcnow()
        row = BookingIntent(
            id=payload["intent_id"],
            idempotency_key=idempotency_key,
            trip_id=trip_id,
            status=payload["status"],
            payload=json.dumps(payload),
            created_at=now,
            updated_at=now,
        )
        with Session(self.engine) as session:
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return self._stored_intent(session, idempotency_key), False
        return payload, True

    def get_intent(self, idempotency_key: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            return self._stored_intent_or_none(session, idempotency_key)

    def update_intent(self, idempotency_key: str, payload: dict[str, Any]) -> None:
        with Session(self.engine) as session:
            row = session.scalar(
                select(BookingIntent).where(BookingIntent.idempotency_key == idempotency_key)
            )
            if row is None:
                raise LookupError("Booking intent was not found.")
            row.status = payload["status"]
            row.payload = json.dumps(payload)
            row.updated_at = _utcnow()
            session.commit()

    def set_trip_status(self, trip_id: str, status: str) -> None:
        with Session(self.engine) as session:
            session.execute(update(Trip).where(Trip.id == trip_id).values(status=status))
            session.commit()

    @staticmethod
    def _stored_intent(session: Session, idempotency_key: str) -> dict[str, Any]:
        stored = PlanStore._stored_intent_or_none(session, idempotency_key)
        if stored is None:
            raise LookupError("Booking intent vanished after a conflicting insert.")
        return stored

    @staticmethod
    def _stored_intent_or_none(session: Session, idempotency_key: str) -> dict[str, Any] | None:
        row = session.scalar(
            select(BookingIntent).where(BookingIntent.idempotency_key == idempotency_key)
        )
        return None if row is None else json.loads(row.payload)
