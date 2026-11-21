"""Conversation and message persistence for the chat. Each method opens its own short session."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.chat.context import ChatContext
from app.chat.models import ChatMessage, Conversation


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _message_dict(row: ChatMessage) -> dict[str, Any]:
    return {
        "id": row.id,
        "role": row.role,
        "text": row.text,
        "created_at": row.created_at.isoformat(),
        "payload": None if row.payload_json is None else json.loads(row.payload_json),
    }


class ChatStore:
    """Conversations, their context JSON and their messages."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def ensure_owned(self, conversation_id: str, owner_id: str) -> None:
        """Create the conversation for its first message; PermissionError for another owner."""
        now = _utcnow()
        with Session(self.engine) as session:
            row = session.get(Conversation, conversation_id)
            if row is None:
                session.add(
                    Conversation(
                        id=conversation_id,
                        owner_id=owner_id,
                        thread_id=None,
                        context_json=ChatContext().to_json(),
                        created_at=now,
                        updated_at=now,
                    )
                )
                session.commit()
                return
            if row.owner_id != owner_id:
                raise PermissionError("owner: conversation belongs to another user")

    def require_owned(self, conversation_id: str, owner_id: str) -> None:
        """LookupError when the conversation does not exist; PermissionError for another owner."""
        with Session(self.engine) as session:
            row = session.get(Conversation, conversation_id)
            if row is None:
                raise LookupError("Conversation was not found.")
            if row.owner_id != owner_id:
                raise PermissionError("owner: conversation belongs to another user")

    def context(self, conversation_id: str) -> ChatContext:
        with Session(self.engine) as session:
            row = session.get(Conversation, conversation_id)
            return ChatContext.from_json(None if row is None else row.context_json)

    def save_context(self, conversation_id: str, context: ChatContext) -> None:
        with Session(self.engine) as session:
            row = session.get(Conversation, conversation_id)
            if row is None:
                raise LookupError("Conversation was not found.")
            row.context_json = context.to_json()
            row.thread_id = context.thread_id
            row.updated_at = _utcnow()
            session.commit()

    def add_message(
        self, conversation_id: str, role: str, text: str, payload: dict[str, Any] | None = None
    ) -> str:
        message_id = str(uuid4())
        with Session(self.engine) as session:
            session.add(
                ChatMessage(
                    id=message_id,
                    conversation_id=conversation_id,
                    role=role,
                    text=text,
                    payload_json=None if payload is None else json.dumps(payload, ensure_ascii=False, default=str),
                    created_at=_utcnow(),
                )
            )
            session.commit()
        return message_id

    def history(self, conversation_id: str) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id)
                .order_by(ChatMessage.created_at)
            ).all()
            return [_message_dict(row) for row in rows]
