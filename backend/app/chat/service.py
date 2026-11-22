"""Chat service: understand each message, then answer it through the trip orchestrator.

Gates:
- A plan starts only when origin and party size are stated or confirmed (no guessed defaults).
- Approve and book always ask first and run only on a confirming message; any other message
  cancels the pending step, and that message is then handled as new.
- Facts about places, prices and plans come from the data. A RAG place answer is LLM text, shown only when every checked fact matches the cited POIs.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from app.agents.booking import ApprovalRequiredError, BookingAgent
from app.agents.orchestrator import NotWaitingError, Orchestrator, StalePlanError
from app.chat import texts
from app.chat.cards import nearby_places, phone_of, place_card, plan_card
from app.chat.context import ChatContext
from app.chat.draft import build_request, confirm_defaults, merge_draft, missing_defaults, missing_question
from app.chat.schemas import BookingCard, ChatReply, UnderstandingInfo
from app.chat.store import ChatStore
from app.db.store import PlanStore
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.request import TripRequest
from app.services.poi_search import normalize_vietnamese
from app.services.quote import UnknownOptionError
from app.understanding.models import ApproveOption, Intent, ParsedQuery, PlanChange, PlanChangeKind
from app.understanding.understand import ConversationContext, apply_changes

if TYPE_CHECKING:
    from app.rag.answer import RagAnswer, RagAnswerer

logger = logging.getLogger(__name__)
Understand = Callable[[str, ConversationContext | None], ParsedQuery]
_OPTION_RE = re.compile(r"\b(BUDGET|BALANCED|COMFORT)\b")
_BOOK_PHRASES = ("dat ve", "dat khach san", "dat cho")
_CHANGE_FORMS: dict[PlanChangeKind, str] = {
    PlanChangeKind.ADD_DAYS: "thêm {value} ngày",
    PlanChangeKind.REMOVE_DAYS: "bỏ {value} ngày",
    PlanChangeKind.SET_DATES: "đổi ngày đi sang {value}",
    PlanChangeKind.SET_PEOPLE: "đổi số người thành {value}",
    PlanChangeKind.SET_BUDGET: "đổi ngân sách thành {value} VND",
    PlanChangeKind.INCLUDE_CATEGORY: "thêm loại {value}",
    PlanChangeKind.EXCLUDE_CATEGORY: "bỏ loại {value}",
}
MAX_PLACE_CARDS = 3


class ChatService:
    """One user message in, one chat reply out. The understanding function is injected."""

    def __init__(
        self,
        understand: Understand,
        orchestrator: Orchestrator,
        plans: PlanStore,
        booking: BookingAgent,
        places: HuePlacesRepository,
        chats: ChatStore,
        rag: RagAnswerer | None = None,
    ) -> None:
        self.understand = understand
        self.orchestrator = orchestrator
        self.plans = plans
        self.booking = booking
        self.places = places
        self.chats = chats
        self.rag = rag
        self.handler_log: list[str] | None = None
        self.last_rag: RagAnswer | None = None

    def _note(self, handler: str) -> None:
        """Record which handler answered the turn (read by the evaluator)."""
        if self.handler_log is not None:
            self.handler_log.append(handler)

    async def handle(self, conversation_id: str, user_id: str, text: str) -> ChatReply:
        """Store the turn, answer it, store the reply; PermissionError for another owner."""
        self.last_rag = None
        self.chats.ensure_owned(conversation_id, user_id)
        context = self.chats.context(conversation_id)
        self.chats.add_message(conversation_id, "user", text)
        parsed = _quick_intent(text, await self._understand(text, context))
        reply = await self._respond(user_id, text, parsed, context)
        self.chats.save_context(conversation_id, context)
        message_id = self.chats.add_message(conversation_id, "assistant", reply.text, reply.model_dump(mode="json"))
        return reply.model_copy(update={"message_id": message_id})

    def history(self, conversation_id: str, user_id: str) -> list[dict[str, Any]]:
        """Messages in time order; LookupError when missing, PermissionError for another owner."""
        self.chats.require_owned(conversation_id, user_id)
        return self.chats.history(conversation_id)

    async def _understand(self, text: str, context: ChatContext) -> ParsedQuery:
        current = TripRequest.model_validate(context.request) if context.request else None
        return await asyncio.to_thread(self.understand, text, ConversationContext(request=current))

    async def _respond(self, user_id: str, text: str, parsed: ParsedQuery, context: ChatContext) -> ChatReply:
        if context.pending is not None:
            answered = await self._answer_pending(user_id, text, parsed, context)
            if answered is not None:
                return answered
        return await self._dispatch(user_id, text, parsed, context)

    async def _answer_pending(
        self, user_id: str, text: str, parsed: ParsedQuery, context: ChatContext
    ) -> ChatReply | None:
        """A confirming message runs the pending step; a cancel word stops it; anything else cancels it."""
        pending = context.pending or {}
        context.pending = None
        folded = normalize_vietnamese(text).strip(" .!?")
        confirms = folded in texts.CONFIRM_WORDS or (
            pending.get("kind") == "defaults" and folded in texts.DEFAULT_WORDS
        )
        if confirms:
            return await self._execute(user_id, pending, parsed, context)
        if folded in texts.CANCEL_WORDS:
            self._note("cancel")
            return self._reply(parsed, texts.CANCELLED)
        return None

    async def _execute(self, user_id: str, pending: dict[str, Any], parsed: ParsedQuery, context: ChatContext) -> ChatReply:
        if pending.get("kind") == "defaults":
            context.draft = confirm_defaults(context.draft)
            self._note("confirm_defaults")
            return await self._start_plan(user_id, parsed, context)
        if pending.get("kind") == "approve":
            self._note("run_approve")
            return await self._run_approve(user_id, pending, parsed, context)
        self._note("run_book")
        return await self._run_book(user_id, pending, parsed, context)

    async def _dispatch(self, user_id: str, text: str, parsed: ParsedQuery, context: ChatContext) -> ChatReply:
        intent = parsed.intent
        if intent is Intent.PLAN_NEW:
            self._note("plan_new")
            return await self._plan_new(user_id, parsed, context)
        if intent is Intent.MODIFY_PLAN:
            self._note("modify")
            return await self._modify(user_id, parsed, context)
        if intent is Intent.PLACE_INFO:
            self._note("place_info")
            return await self._place_info(text, parsed)
        if intent is Intent.APPROVE:
            self._note("ask_approve")
            return self._ask_approve(text, parsed, context)
        if intent is Intent.BOOK:
            self._note("ask_book")
            return self._ask_book(parsed, context)
        self._note("out_of_scope")
        return self._reply(parsed, texts.OUT_OF_SCOPE, replies=["Lên kế hoạch đi Huế"])

    async def _plan_new(self, user_id: str, parsed: ParsedQuery, context: ChatContext) -> ChatReply:
        context.draft = merge_draft(context.draft, parsed)
        question = missing_question(context.draft)
        if question is not None:
            return self._reply(parsed, question[0], replies=question[1])
        if missing_defaults(context.draft):
            context.pending = {"kind": "defaults"}
            return self._reply(parsed, texts.DEFAULTS_QUESTION, replies=texts.DEFAULT_REPLIES, pending=context.pending)
        return await self._start_plan(user_id, parsed, context)

    async def _start_plan(self, user_id: str, parsed: ParsedQuery, context: ChatContext) -> ChatReply:
        try:
            request = build_request(context.draft)
        except ValueError as error:
            return self._reply(parsed, texts.invalid(str(error)))
        thread = f"chat-{uuid4().hex}"
        try:
            state = await self.orchestrator.start(thread, request, owner_id=user_id)
        except ValueError as error:
            return self._reply(parsed, texts.invalid(str(error)))
        if not state["waiting"]:
            return self._reply(parsed, texts.plan_failed(state["warnings"]))
        context.thread_id = thread
        context.request = request.model_dump(mode="json")
        context.draft = {}
        return self._plan_reply(parsed, state)

    async def _modify(self, user_id: str, parsed: ParsedQuery, context: ChatContext) -> ChatReply:
        if context.thread_id is None or context.request is None:
            return self._reply(parsed, texts.NO_PLAN)
        current = TripRequest.model_validate(context.request)
        updated, notes = apply_changes(current, parsed.changes)
        if updated == current:
            return self._reply(parsed, texts.changes_not_applied(notes))
        try:
            state = await self.orchestrator.resume(
                context.thread_id,
                {"action": "edit", "request": updated.model_dump(mode="json"), "user_id": user_id},
            )
        except NotWaitingError:
            return self._reply(parsed, texts.NOT_WAITING)
        except PermissionError as error:
            return self._reply(parsed, str(error))
        if not state["waiting"]:
            return self._reply(parsed, texts.plan_failed(state["warnings"]))
        context.request = updated.model_dump(mode="json")
        prefix = texts.changes_applied(_change_lines(parsed.changes), notes)
        return self._plan_reply(parsed, state, prefix)

    async def _place_info(self, text: str, parsed: ParsedQuery) -> ChatReply:
        """RAG answer when configured; the template answer otherwise or when RAG fails."""
        if self.rag is not None:
            try:
                answer = await asyncio.to_thread(self.rag.answer, text, parsed)
            except Exception:  # RAG must never break the chat; the template path answers instead
                logger.exception("RAG answer failed; using the template answer")
            else:
                self.last_rag = answer
                found = (self.places.get_by_id(poi_id) for poi_id in answer.cited_poi_ids[:MAX_PLACE_CARDS])
                return self._reply(parsed, answer.text, cards=[place_card(p) for p in found if p is not None])
        return self._template_place_info(text, parsed)

    def _template_place_info(self, text: str, parsed: ParsedQuery) -> ChatReply:
        mention = parsed.place_query
        place = self.places.get_by_id(mention.poi_id) if mention is not None and mention.poi_id else None
        if place is None:
            return self._reply(parsed, texts.PLACE_MISSING)
        body = texts.place_text(place, phone_of(place))
        if " gan " in f" {normalize_vietnamese(text)} ":
            body = f"{body}\n{texts.nearby_text(nearby_places(place, self.places.list_all()))}"
        return self._reply(parsed, body, cards=[place_card(place)])

    def _ask_approve(self, text: str, parsed: ParsedQuery, context: ChatContext) -> ChatReply:
        plan = self._latest_plan(context)
        if plan is None:
            return self._reply(parsed, texts.NO_PLAN)
        options = _options(plan)
        label = _option_in(text) or (parsed.approve_option.value if parsed.approve_option else None)
        if label is None:
            return self._reply(parsed, texts.CHOOSE_OPTION, replies=[f"Duyệt {name}" for name in options])
        if label not in options:
            return self._reply(parsed, texts.no_option(label))
        option = options[label]
        context.pending = {"kind": "approve", "option": label, "version": plan["version"]}
        total = texts.total_range(option["known_total_vnd"], option["known_total_max_vnd"])
        question = texts.approve_question(label, plan["version"], total)
        return self._reply(parsed, question, replies=texts.YES_REPLIES, pending=context.pending)

    async def _run_approve(self, user_id: str, pending: dict[str, Any], parsed: ParsedQuery, context: ChatContext) -> ChatReply:
        if context.thread_id is None:
            return self._reply(parsed, texts.NO_PLAN)
        answer = {"action": "approve", "option": pending["option"], "user_id": user_id, "version": pending["version"]}
        try:
            await self.orchestrator.resume(context.thread_id, answer)
        except (StalePlanError, NotWaitingError, UnknownOptionError, PermissionError) as error:
            return self._reply(parsed, texts.stale(str(error)))
        return self._reply(parsed, texts.approved_text(pending["option"], pending["version"]), replies=["Đặt vé và khách sạn"])

    def _ask_book(self, parsed: ParsedQuery, context: ChatContext) -> ChatReply:
        plan = self._latest_plan(context)
        if plan is None:
            return self._reply(parsed, texts.NO_PLAN)
        approval = self.plans.active_approval(plan["plan_id"])
        if approval is None:
            return self._reply(parsed, texts.NEED_APPROVAL)
        context.pending = {"kind": "book", "option": approval["option"], "quote_hash": approval["quote_hash"]}
        return self._reply(parsed, texts.book_question(approval["option"]), replies=texts.YES_REPLIES, pending=context.pending)

    async def _run_book(self, user_id: str, pending: dict[str, Any], parsed: ParsedQuery, context: ChatContext) -> ChatReply:
        if context.thread_id is None:
            return self._reply(parsed, texts.NO_PLAN)
        key = context.keys.setdefault(pending["quote_hash"], f"chat-{uuid4().hex}")
        try:
            result = await asyncio.to_thread(self.booking.book, context.thread_id, key, user_id)
        except ApprovalRequiredError:
            return self._reply(parsed, texts.NEED_APPROVAL)
        except LookupError:
            return self._reply(parsed, texts.NO_PLAN)
        except PermissionError as error:
            return self._reply(parsed, str(error))
        return self._reply(parsed, texts.booking_text(result), cards=[BookingCard(result=result)])

    def _plan_reply(self, parsed: ParsedQuery, state: dict[str, Any], prefix: str = "") -> ChatReply:
        card = plan_card(self.plans.latest(state["thread_id"]), state)
        labels = [option.label for option in card.budget_options]
        text = texts.plan_text(len(card.days), state["version"], labels)
        return self._reply(
            parsed,
            f"{prefix} {text}".strip(),
            cards=[card],
            replies=[f"Duyệt {label}" for label in labels],
        )

    def _latest_plan(self, context: ChatContext) -> dict[str, Any] | None:
        return None if context.thread_id is None else self.plans.latest(context.thread_id)

    @staticmethod
    def _reply(
        parsed: ParsedQuery,
        text: str,
        cards: Sequence[Any] = (),
        replies: Sequence[str] = (),
        pending: dict[str, Any] | None = None,
    ) -> ChatReply:
        understanding = UnderstandingInfo(
            intent=parsed.intent.value, source=parsed.source.value, notes=list(parsed.notes)
        )
        return ChatReply(
            text=text,
            cards=list(cards),
            quick_replies=list(replies),
            pending_confirmation=pending,
            understanding=understanding,
        )


def _options(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {option["label"]: option for option in plan["payload"]["budget"]["options"] if option.get("label")}


def _option_in(text: str) -> str | None:
    match = _OPTION_RE.search(text.upper())
    return match.group(1) if match else None


def _quick_intent(text: str, parsed: ParsedQuery) -> ParsedQuery:
    """Recognise the chat's own quick replies, which the rule parser would read as a new plan."""
    folded = normalize_vietnamese(text)
    option = _option_in(text)
    if folded.startswith("duyet") and option is not None:
        return parsed.model_copy(update={"intent": Intent.APPROVE, "approve_option": ApproveOption(option)})
    if any(phrase in folded for phrase in _BOOK_PHRASES):
        return parsed.model_copy(update={"intent": Intent.BOOK})
    return parsed


def _change_lines(changes: Sequence[PlanChange]) -> list[str]:
    return [_CHANGE_FORMS[change.kind].format(value=change.value) for change in changes if change.kind in _CHANGE_FORMS]
