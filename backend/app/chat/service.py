"""Chat service: understand each message, then answer it through the trip orchestrator.

Gates:
- A plan starts only when every required slot is filled (`draft.pending_units` is empty); no default is guessed.
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
from app.chat import slots, texts
from app.chat.cards import nearby_places, phone_of, place_card, plan_card
from app.chat.context import ChatContext
from app.chat.draft import (
    build_request,
    asked_units,
    mark_asked,
    merge_draft,
    next_questions,
    pending_soft_note,
    precheck_due,
    precheck_key,
    summary_lines,
    summary_text,
)
from app.chat.schemas import BookingCard, ChatReply, UnderstandingInfo
from app.chat.store import ChatStore
from app.db.store import PlanStore
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.request import TripRequest
from app.services.guide import guide_for, guide_sentences
from app.services.origin import is_hue_name
from app.services.poi_search import normalize_vietnamese
from app.services.quote import UnknownOptionError
from app.understanding.models import ApproveOption, Intent, ParsedQuery, PlanChange, PlanChangeKind
from app.understanding.smalltalk import smalltalk_kind
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
    PlanChangeKind.ADD_PLACE: "thêm {value}",
    PlanChangeKind.REMOVE_PLACE: "bỏ {value}",
}
MAX_PLACE_CARDS = 3
# Intents that answer an open slot while a draft is filling.
_SLOT_INTENTS = (Intent.PLAN_NEW, Intent.MODIFY_PLAN, Intent.OUT_OF_SCOPE)
# Folded cues that ask for a description of a place ("Hồ Thủy Tiên có gì hay?"), matched as whole words.
_DESCRIPTION_CUES = ("co gi hay", "co gi dep", "co gi", "gioi thieu", "ke ve", "lich su", "noi tieng", "o day co gi", "the nao")


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
        if pending.get("kind") == "confirm_trip":
            return await self._answer_summary(user_id, text, parsed, context, pending, folded)
        if folded in texts.CONFIRM_WORDS:
            return await self._execute(user_id, pending, parsed, context)
        if folded in texts.CANCEL_WORDS:
            self._note("cancel")
            return self._reply(parsed, texts.CANCELLED)
        if parsed.intent is Intent.PLACE_INFO:
            context.pending = pending  # a place question leaves the approval or booking step waiting
        return None

    async def _answer_summary(
        self,
        user_id: str,
        text: str,
        parsed: ParsedQuery,
        context: ChatContext,
        pending: dict[str, Any],
        folded: str,
    ) -> ChatReply | None:
        """At the summary (S4, S5): a confirming message starts the plan, a cancel word keeps the draft,
        an edit goes to the slot filling, and a question or smalltalk is answered while the summary waits."""
        if folded in texts.CONFIRM_WORDS or folded in texts.TRIP_CONFIRM_WORDS:
            self._note("start_trip")
            context.draft = {**context.draft, "confirmed": True}
            reply = await self._start_plan(user_id, parsed, context)
            if "confirmed" in context.draft:  # the plan did not start: the draft stays, unconfirmed
                context.draft = {key: value for key, value in context.draft.items() if key != "confirmed"}
            return reply
        if folded in texts.CANCEL_WORDS:
            self._note("cancel")
            return self._reply(parsed, texts.CANCELLED)
        if parsed.intent in _SLOT_INTENTS and not (_is_weather(text) or _is_other_city(parsed)):
            return None  # an edit: _dispatch merges it into the draft and sends the summary again
        context.pending = pending  # a question or smalltalk: answered by _dispatch, the summary still waits
        return None

    async def _execute(self, user_id: str, pending: dict[str, Any], parsed: ParsedQuery, context: ChatContext) -> ChatReply:
        if pending.get("kind") == "approve":
            self._note("run_approve")
            return await self._run_approve(user_id, pending, parsed, context)
        self._note("run_book")
        return await self._run_book(user_id, pending, parsed, context)

    async def _dispatch(self, user_id: str, text: str, parsed: ParsedQuery, context: ChatContext) -> ChatReply:
        intent = parsed.intent
        if _is_filling(context) and intent in _SLOT_INTENTS:
            # While slots are open, a plan, change or out-of-scope message answers them. Weather and
            # other cities keep their refusals, without quick replies, and the draft stays as it is.
            if _is_weather(text) or _is_other_city(parsed):
                return self._out_of_scope(text, parsed, quick=False)
            self._note("plan_new")
            return await self._plan_new(user_id, text, parsed.model_copy(update={"intent": Intent.PLAN_NEW}), context)
        if intent is Intent.PLAN_NEW and _is_weather(text) and not _is_trip_detail(parsed, context):
            # The rule parser (Ollama down) reads "Thời tiết Huế…" as a Huế trip: answer the
            # weather refusal instead of starting to ask for dates.
            return self._out_of_scope(text, parsed, quick=True)
        if intent is Intent.PLAN_NEW or (intent is Intent.MODIFY_PLAN and _is_trip_detail(parsed, context)):
            self._note("plan_new")
            return await self._plan_new(user_id, text, parsed.model_copy(update={"intent": Intent.PLAN_NEW}), context)
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
        if intent is Intent.SMALLTALK:
            self._note("smalltalk")
            return self._smalltalk(text, parsed, context)
        return self._out_of_scope(text, parsed, quick=True)

    def _out_of_scope(self, text: str, parsed: ParsedQuery, *, quick: bool) -> ChatReply:
        """The weather refusal, or the polite refusal of other trips; quick replies only outside slot filling."""
        self._note("out_of_scope")
        if _is_weather(text):
            return self._reply(parsed, texts.WEATHER)
        return self._reply(parsed, texts.OUT_OF_SCOPE, replies=["Lên kế hoạch đi Huế"] if quick else [])

    def _smalltalk(self, text: str, parsed: ParsedQuery, context: ChatContext) -> ChatReply:
        """A fixed template answer; a plan in the chat gets a one-line status nudge instead of an example."""
        kind = smalltalk_kind(text) or "greeting"
        body = {
            "greeting": texts.GREETING,
            "identity": texts.IDENTITY,
            "thanks": texts.THANKS,
            "goodbye": texts.GOODBYE,
        }[kind]
        plan = self._latest_plan(context)
        if plan is not None:
            approved = self.plans.active_approval(plan["plan_id"]) is not None
            nudge = texts.PLAN_APPROVED_NUDGE if approved else texts.PLAN_WAITING_NUDGE
        elif kind in ("greeting", "identity"):
            nudge = texts.SMALLTALK_EXAMPLE
        else:
            nudge = ""
        return self._reply(parsed, f"{body} {nudge}".strip())

    async def _plan_new(self, user_id: str, text: str, parsed: ParsedQuery, context: ChatContext) -> ChatReply:
        """Fill the draft from this message; ask the next two open slots, or start the plan when none is open."""
        draft = slots.take_answers(merge_draft(context.draft, parsed), text, parsed.fields)
        if precheck_due(draft):
            draft["precheck"] = await self._precheck(draft)
        question = next_questions(draft)
        if question is None:
            return self._summary(parsed, draft, context)
        if pending_soft_note(draft) is not None:
            draft["precheck_noted"] = True
        context.draft = mark_asked(draft, asked_units(draft))
        return self._reply(parsed, question)

    def _summary(self, parsed: ParsedQuery, draft: dict[str, Any], context: ChatContext) -> ChatReply:
        """The summary of a complete draft; the plan waits for a confirming message (S4)."""
        text = summary_text(draft, self._name_of, previous=draft.get("summary_lines"))
        draft["summary_lines"] = summary_lines(draft, self._name_of)
        context.draft = draft
        context.pending = {"kind": "confirm_trip"}
        return self._reply(parsed, text, pending=context.pending)

    def _name_of(self, poi_id: str) -> str | None:
        place = self.places.get_by_id(poi_id)
        return place.name if place is not None else None

    async def _precheck(self, draft: dict[str, Any]) -> dict[str, Any]:
        """The cheapest estimate for the draft's request (S2). A missing estimate is stored too, so it is not retried."""
        key = precheck_key(draft) or ""
        try:
            estimate = await self.orchestrator.estimate(build_request(draft))
        except ValueError:  # the same refusal _start_plan reports as an invalid request
            estimate = None
        if estimate is None:
            return {"key": key, "min": None, "max": None, "mode": None, "tier": None}
        return {
            "key": key,
            "min": estimate.min_vnd,
            "max": estimate.max_vnd,
            "mode": estimate.transport_mode,
            "tier": estimate.hotel_tier,
        }

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
        prefix = texts.changes_applied(
            _change_lines(
                parsed.changes,
                lambda poi_id: (p.name if (p := self.places.get_by_id(poi_id)) else None),
            ),
            notes,
        )
        return self._plan_reply(parsed, state, prefix)

    async def _place_info(self, text: str, parsed: ParsedQuery) -> ChatReply:
        """A description question about a linked place is answered from the stored guide text (S10); other
        place questions get the facts answer."""
        mention = parsed.place_query
        poi_id = mention.poi_id if mention is not None else None
        if poi_id is not None and _asks_description(text):
            self._note("guide")
            return await self._description(poi_id, text, parsed)
        return await self._place_facts(text, parsed)

    async def _description(self, poi_id: str, text: str, parsed: ParsedQuery) -> ChatReply:
        """The guide lead when the corpus has one, else the huetripo summary, else the facts answer with a note.
        The guide and summary are copied from stored text; no LLM writes them."""
        place = self.places.get_by_id(poi_id)
        if place is None:
            return self._reply(parsed, texts.PLACE_MISSING)
        cards = [place_card(place)]
        guide = guide_for(poi_id)
        if guide is not None:
            return self._reply(parsed, texts.guide_text(place.name, guide_sentences(poi_id, 4), guide.url), cards=cards)
        if place.summary:
            return self._reply(parsed, texts.summary_text(place.name, place.summary), cards=cards)
        reply = await self._place_facts(text, parsed)
        return reply.model_copy(update={"text": f"{reply.text}\n{texts.NO_DESCRIPTION}"})

    async def _place_facts(self, text: str, parsed: ParsedQuery) -> ChatReply:
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


def _asks_description(text: str) -> bool:
    folded = normalize_vietnamese(text)
    return any(re.search(r"\b" + re.escape(cue) + r"\b", folded) for cue in _DESCRIPTION_CUES)


def _quick_intent(text: str, parsed: ParsedQuery) -> ParsedQuery:
    """Recognise the chat's own quick replies, which the rule parser would read as a new plan."""
    folded = normalize_vietnamese(text)
    option = _option_in(text)
    if folded.startswith("duyet") and option is not None:
        return parsed.model_copy(update={"intent": Intent.APPROVE, "approve_option": ApproveOption(option)})
    if any(phrase in folded for phrase in _BOOK_PHRASES):
        return parsed.model_copy(update={"intent": Intent.BOOK})
    return parsed


_TRIP_FIELDS = ("origin", "people", "rooms", "budget_vnd", "num_days", "start_date")
# Weather cues, folded. The bot has no weather data, so it refuses with a pointer to the forecast.
_WEATHER_PHRASES = ("thoi tiet", "nhiet do", "du bao", "troi mua", "co mua", "mua khong", "nang khong")


def _is_weather(text: str) -> bool:
    folded = normalize_vietnamese(text)
    return any(phrase in folded for phrase in _WEATHER_PHRASES)


def _is_other_city(parsed: ParsedQuery) -> bool:
    destination = parsed.fields.get("destination")
    return destination is not None and not is_hue_name(destination)


def _is_filling(context: ChatContext) -> bool:
    """A draft is being filled for a plan that has not started yet."""
    return bool(context.draft) and context.thread_id is None


def _is_trip_detail(parsed: ParsedQuery, context: ChatContext) -> bool:
    """A MODIFY_PLAN with no plan to modify, carrying trip details, is the start of a new plan."""
    if context.thread_id is not None:
        return False
    if context.draft:
        return True
    return any(parsed.fields.get(name) is not None for name in _TRIP_FIELDS)


_CATEGORY_KINDS = (PlanChangeKind.INCLUDE_CATEGORY, PlanChangeKind.EXCLUDE_CATEGORY)
_PLACE_KINDS = (PlanChangeKind.ADD_PLACE, PlanChangeKind.REMOVE_PLACE)


def _change_lines(
    changes: Sequence[PlanChange], name_of: Callable[[str], str | None]
) -> list[str]:
    """One Vietnamese line per change: categories by name, places by name (skipped when unknown)."""
    lines: list[str] = []
    for change in changes:
        if change.kind not in _CHANGE_FORMS or change.value is None:
            continue
        if change.kind in _PLACE_KINDS:
            name = name_of(str(change.value))
            if name is None:
                continue
            lines.append(_CHANGE_FORMS[change.kind].format(value=name))
        elif change.kind in _CATEGORY_KINDS:
            lines.append(_CHANGE_FORMS[change.kind].format(value=texts.category_name(str(change.value))))
        else:
            lines.append(_CHANGE_FORMS[change.kind].format(value=change.value))
    return lines
