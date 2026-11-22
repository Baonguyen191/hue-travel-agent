"""Chat endpoints: POST one message to a conversation, GET its history.

`X-User-Id` is the same MVP ownership check as the plan API (not authentication). A
conversation belongs to the user who wrote its first message; another user gets 403.
"""

from __future__ import annotations

import functools
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.api.bookings import build_booking_agent
from app.api.plans import hue_places
from app.chat import texts
from app.chat.cards import phone_of
from app.chat.schemas import ChatMessageIn, ChatReply
from app.chat.service import ChatService, Understand
from app.chat.store import ChatStore
from app.core.config import (
    ollama_url,
    qu_enabled,
    qu_model,
    rag_embed_model,
    rag_enabled,
    rag_gen_model,
    rag_index_path,
)
from app.db.store import DEFAULT_OWNER, PlanStore
from app.rag.answer import RagAnswerer
from app.rag.index import EmbedClient, EmbeddingStore
from app.rag.retrieve import Retriever
from app.understanding.extract import OllamaExtractor
from app.understanding.understand import understand as understand_query

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


@functools.cache
def _extractor() -> OllamaExtractor | None:
    """One Ollama client per process; None when QU_ENABLED is off (the rules answer instead)."""
    return OllamaExtractor(ollama_url(), qu_model()) if qu_enabled() else None


@functools.cache
def _rag() -> RagAnswerer | None:
    """One answerer per process; None when RAG or the LLM is switched off."""
    if not (rag_enabled() and qu_enabled()):
        return None
    client = EmbedClient(ollama_url(), rag_embed_model())
    retriever = Retriever(hue_places.list_all(), EmbeddingStore(rag_index_path()), client)
    return RagAnswerer(retriever, lambda place: texts.place_text(place, phone_of(place)), ollama_url(), rag_gen_model())


def get_rag() -> RagAnswerer | None:
    """The place answerer; tests replace it with `app.dependency_overrides`."""
    return _rag()


def default_understand(text: str, context: Any) -> Any:
    """The production understanding: Ollama when enabled, rules otherwise."""
    return understand_query(text, context=context, extractor=_extractor())


def get_understand() -> Understand:
    """The understanding function; tests replace it with `app.dependency_overrides`."""
    return default_understand


def get_chat_service(
    request: Request,
    understand_fn: Understand = Depends(get_understand),
    rag: RagAnswerer | None = Depends(get_rag),
) -> ChatService:
    """Wire the chat service over the lifespan's store and orchestrator."""
    store: PlanStore = request.app.state.store
    return ChatService(
        understand=understand_fn,
        orchestrator=request.app.state.orchestrator,
        plans=store,
        booking=build_booking_agent(store),
        places=hue_places,
        chats=ChatStore(store.engine),
        rag=rag,
    )


@router.post("/{conversation_id}", response_model=ChatReply)
async def post_message(
    conversation_id: str,
    body: ChatMessageIn,
    service: ChatService = Depends(get_chat_service),
    x_user_id: str = Header(default=DEFAULT_OWNER),
):
    """Answer one message; the reply carries its cards, quick replies and understanding source."""
    try:
        return await service.handle(conversation_id, x_user_id, body.text)
    except PermissionError as error:
        raise HTTPException(403, str(error))


@router.get("/{conversation_id}")
def get_history(
    conversation_id: str,
    service: ChatService = Depends(get_chat_service),
    x_user_id: str = Header(default=DEFAULT_OWNER),
):
    """All messages of a conversation in time order: 404 when missing, 403 for another owner."""
    try:
        messages = service.history(conversation_id, x_user_id)
    except LookupError as error:
        raise HTTPException(404, str(error))
    except PermissionError as error:
        raise HTTPException(403, str(error))
    return {"conversation_id": conversation_id, "messages": messages}
