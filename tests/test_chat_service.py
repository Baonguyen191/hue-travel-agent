"""Chat service: every intent path, the clarification and confirmation gates, owners and history.

The understanding function is a fake: messages without a script go through the rule parser
with a fixed reference date; scripted messages return the ParsedQuery the test writes.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
HUE_DB = BACKEND / "data" / "hue.sqlite"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.booking import BookingAgent  # noqa: E402
from app.agents.orchestrator import Orchestrator  # noqa: E402
from app.agents.search import SearchAgent  # noqa: E402
from app.chat import texts  # noqa: E402
from app.chat.context import ChatContext  # noqa: E402
from app.chat.schemas import BookingCard, ChatReply, PlaceCard, PlanCard  # noqa: E402
from app.chat.service import ChatService  # noqa: E402
from app.chat.store import ChatStore  # noqa: E402
from app.db.store import PlanStore  # noqa: E402
from app.providers.booking_mock import MockBookingProvider  # noqa: E402
from app.providers.hotel_mock import MockHotelProvider  # noqa: E402
from app.providers.transport_mock import MockTransportProvider  # noqa: E402
from app.repositories.hue_places import HuePlacesRepository  # noqa: E402
from app.services.budget_optimizer import BudgetAgent  # noqa: E402
from app.services.itinerary_optimizer import ItineraryAgent  # noqa: E402
from app.services.quote_revalidator import QuoteRevalidator  # noqa: E402
from app.understanding.models import (  # noqa: E402
    ApproveOption,
    Intent,
    ParsedQuery,
    PlaceMention,
    PlanChange,
    PlanChangeKind,
    QuSource,
)
from app.understanding.understand import ConversationContext, understand  # noqa: E402

REF = date(2026, 11, 18)
USER = "alice"
GIA_LONG_TEXT = "Lăng vua Gia Long"
DAI_NOI = "huetripo:531787"
DAI_NOI_HOURS = "07:30-17:30"


class FakeUnderstand:
    """Scripted ParsedQuery per exact message; everything else goes through the rule parser."""

    def __init__(self) -> None:
        self.scripts: dict[str, ParsedQuery] = {}
        self.calls: list[str] = []

    def script(self, text: str, parsed: ParsedQuery) -> None:
        self.scripts[text] = parsed

    def __call__(self, text: str, context: ConversationContext | None) -> ParsedQuery:
        self.calls.append(text)
        if text in self.scripts:
            return self.scripts[text]
        return understand(text, REF, context)


class Harness:
    """A chat service over an in-memory plan store, with a spy on orchestrator starts."""

    def __init__(self) -> None:
        self.store = PlanStore("sqlite://")
        self.repo = HuePlacesRepository(HUE_DB)
        self.orchestrator = Orchestrator(
            SearchAgent(self.repo, MockTransportProvider(), MockHotelProvider()),
            BudgetAgent(places=self.repo),
            ItineraryAgent(places=self.repo),
            self.store,
            InMemorySaver(),
        )
        self.starts: list[Any] = []
        self._install_start_spy()
        self.booking = BookingAgent(
            self.store,
            MockBookingProvider(),
            QuoteRevalidator(MockTransportProvider(), MockHotelProvider()),
            places=self.repo,
        )
        self.fake = FakeUnderstand()
        self.chats = ChatStore(self.store.engine)
        self.service = ChatService(
            self.fake, self.orchestrator, self.store, self.booking, self.repo, self.chats
        )

    def _install_start_spy(self) -> None:
        original = self.orchestrator.start

        async def spy(thread_id: str, request: Any, owner_id: str = "anonymous") -> dict[str, Any]:
            self.starts.append(request)
            return await original(thread_id, request, owner_id=owner_id)

        self.orchestrator.start = spy  # type: ignore[method-assign]

    async def say(self, conversation: str, text: str, user: str = USER) -> ChatReply:
        return await self.service.handle(conversation, user, text)


def _scripted(intent: Intent, **kwargs: Any) -> ParsedQuery:
    return ParsedQuery(intent=intent, source=QuSource.OLLAMA, **kwargs)


def _run(scenario):
    return asyncio.run(scenario())


def _plan_card(reply: ChatReply) -> PlanCard:
    cards = [card for card in reply.cards if isinstance(card, PlanCard)]
    assert cards, reply.text
    return cards[0]


PLAN_TRIP = "Từ Hà Nội, 2 người, đi Huế 2 ngày từ 20/12"


# ---------------------------------------------------------------------------
# plan_new: clarification, defaults gate, start
# ---------------------------------------------------------------------------


def test_missing_start_and_duration_asks_with_quick_replies_and_stores_the_draft() -> None:
    async def scenario():
        h = Harness()
        reply = await h.say("c-clarify", "Đi Huế đi chơi vui")
        return h, reply

    h, reply = _run(scenario)

    assert reply.quick_replies
    assert "ngày nào" in reply.text
    assert reply.pending_confirmation is None
    assert h.starts == []
    assert "start_date" not in h.chats.context("c-clarify").draft
    assert "num_days" not in h.chats.context("c-clarify").draft


def test_next_message_is_merged_into_the_draft_and_the_plan_starts_only_after_defaults_are_confirmed() -> None:
    async def scenario():
        h = Harness()
        await h.say("c-merge", "Đi Huế 2 ngày")
        draft_after_first = dict(h.chats.context("c-merge").draft)
        second = await h.say("c-merge", "20/12")
        return h, draft_after_first, second

    h, draft_after_first, second = _run(scenario)

    assert draft_after_first["num_days"] == 2
    assert h.chats.context("c-merge").draft["start_date"] == "2026-12-20"
    assert h.chats.context("c-merge").draft["num_days"] == 2
    assert second.pending_confirmation == {"kind": "defaults"}
    assert h.starts == []


def test_complete_request_with_defaulted_origin_asks_once_and_never_starts_a_plan_unconfirmed() -> None:
    async def scenario():
        h = Harness()
        reply = await h.say("c-defaults", "Đi Huế 2 ngày từ 20/12")
        return h, reply

    h, reply = _run(scenario)

    assert "mặc định: Huế, 1 người" in reply.text
    assert reply.quick_replies == list(texts.DEFAULT_REPLIES)
    assert reply.pending_confirmation == {"kind": "defaults"}
    assert h.starts == []
    assert h.chats.context("c-defaults").thread_id is None


def test_defaults_are_not_started_by_an_unrelated_message() -> None:
    async def scenario():
        h = Harness()
        await h.say("c-noguess", "Đi Huế 2 ngày từ 20/12")
        reply = await h.say("c-noguess", "để mình suy nghĩ thêm")
        return h, reply

    h, reply = _run(scenario)

    assert h.starts == []
    assert reply.pending_confirmation == {"kind": "defaults"}


def test_dung_mac_dinh_starts_the_plan_with_confirmed_defaults() -> None:
    async def scenario():
        h = Harness()
        await h.say("c-yes-defaults", "Đi Huế 2 ngày từ 20/12")
        reply = await h.say("c-yes-defaults", "Dùng mặc định")
        return h, reply

    h, reply = _run(scenario)

    assert len(h.starts) == 1
    assert h.starts[0].origin == "Huế"
    assert h.starts[0].people == 1
    assert _plan_card(reply).status == "AWAITING_APPROVAL"
    assert h.chats.context("c-yes-defaults").thread_id is not None


def test_stated_origin_and_people_start_the_plan_at_once_with_plan_card_and_quick_replies() -> None:
    async def scenario():
        h = Harness()
        reply = await h.say("c-plan", PLAN_TRIP)
        return h, reply

    h, reply = _run(scenario)

    card = _plan_card(reply)
    assert len(h.starts) == 1
    assert h.starts[0].origin == "Hà Nội"
    assert h.starts[0].people == 2
    assert card.version == 1
    assert len(card.days) == 2
    assert all(item.kind in ("VISIT", "MEAL", "MEAL_BREAK") for day in card.days for item in day.items)
    assert card.budget_options
    assert reply.quick_replies == [f"Duyệt {option.label}" for option in card.budget_options]
    assert reply.understanding.source == "RULES"


def test_defaults_answer_with_a_stated_origin_is_merged_and_starts_the_plan() -> None:
    async def scenario():
        h = Harness()
        await h.say("c-answer", "Đi Huế 2 ngày từ 20/12")
        reply = await h.say("c-answer", "Từ Hà Nội, 2 người")
        return h, reply

    h, reply = _run(scenario)

    assert len(h.starts) == 1
    assert h.starts[0].origin == "Hà Nội"
    assert h.starts[0].people == 2
    assert _plan_card(reply)


def test_a_plan_that_is_too_long_asks_for_fewer_days() -> None:
    async def scenario():
        h = Harness()
        return h, await h.say("c-long", "Đi Huế 10 ngày từ 20/12")

    h, reply = _run(scenario)

    assert "tối đa 7 ngày" in reply.text
    assert h.starts == []


# ---------------------------------------------------------------------------
# approve and book: confirmation first
# ---------------------------------------------------------------------------


async def _planned(h: Harness, conversation: str) -> PlanCard:
    reply = await h.say(conversation, PLAN_TRIP)
    return _plan_card(reply)


def test_approve_asks_for_confirmation_and_only_a_confirming_message_approves() -> None:
    h = Harness()
    h.fake.script("Duyệt BUDGET", _scripted(Intent.APPROVE, approve_option=ApproveOption.BUDGET))

    async def scenario():
        await _planned(h, "c-approve")
        asked = await h.say("c-approve", "Duyệt BUDGET")
        still_open = h.store.active_approval(h.store.latest(h.chats.context("c-approve").thread_id)["plan_id"])
        confirmed = await h.say("c-approve", "đồng ý")
        return asked, still_open, confirmed

    asked, still_open, confirmed = _run(scenario)

    assert asked.pending_confirmation == {"kind": "approve", "option": "BUDGET", "version": 1}
    assert asked.quick_replies == list(texts.YES_REPLIES)
    assert "BUDGET" not in asked.text
    assert still_open is None
    assert "Đã duyệt phương án Tiết kiệm" in confirmed.text
    assert confirmed.pending_confirmation is None


def test_any_other_message_cancels_a_pending_approval() -> None:
    h = Harness()
    h.fake.script("Duyệt BUDGET", _scripted(Intent.APPROVE, approve_option=ApproveOption.BUDGET))

    async def scenario():
        await _planned(h, "c-cancel")
        await h.say("c-cancel", "Duyệt BUDGET")
        other = await h.say("c-cancel", "khoan đã, đổi ngày được không")
        return other

    other = _run(scenario)

    assert other.pending_confirmation is None
    assert other.text != texts.CANCELLED
    assert other.understanding.intent == "plan_new"
    assert h.chats.context("c-cancel").pending is None
    assert h.store.active_approval(h.store.latest(h.chats.context("c-cancel").thread_id)["plan_id"]) is None


def test_quick_replies_approve_and_book_work_without_any_scripted_understanding() -> None:
    h = Harness()

    async def scenario():
        await _planned(h, "c-quick")
        asked = await h.say("c-quick", "Duyệt BUDGET")
        await h.say("c-quick", "đồng ý")
        book_asked = await h.say("c-quick", "Đặt vé và khách sạn")
        return asked, book_asked

    asked, book_asked = _run(scenario)

    assert asked.pending_confirmation == {"kind": "approve", "option": "BUDGET", "version": 1}
    assert asked.understanding.intent == "approve"
    assert book_asked.understanding.intent == "book"
    assert book_asked.pending_confirmation["kind"] == "book"


def test_cancel_word_stops_the_pending_approval_with_a_cancel_reply() -> None:
    h = Harness()
    h.fake.script("Duyệt BUDGET", _scripted(Intent.APPROVE, approve_option=ApproveOption.BUDGET))

    async def scenario():
        await _planned(h, "c-huy")
        await h.say("c-huy", "Duyệt BUDGET")
        return await h.say("c-huy", "Huỷ")

    reply = _run(scenario)

    assert reply.text == texts.CANCELLED
    assert h.store.latest(h.chats.context("c-huy").thread_id)["version"] == 1


def test_approve_without_a_plan_says_so() -> None:
    h = Harness()
    h.fake.script("Duyệt BUDGET", _scripted(Intent.APPROVE, approve_option=ApproveOption.BUDGET))

    reply = _run(lambda: h.say("c-noplan", "Duyệt BUDGET"))

    assert reply.text == texts.NO_PLAN
    assert reply.pending_confirmation is None


def test_book_before_approval_is_refused_without_a_confirmation() -> None:
    h = Harness()
    h.fake.script("đặt vé", _scripted(Intent.BOOK))

    async def scenario():
        await _planned(h, "c-book-early")
        return await h.say("c-book-early", "đặt vé")

    reply = _run(scenario)

    assert reply.text == texts.NEED_APPROVAL
    assert reply.pending_confirmation is None
    assert reply.cards == []


def test_book_asks_for_confirmation_then_books_the_approved_quote_once_per_key() -> None:
    h = Harness()
    h.fake.script("Duyệt BUDGET", _scripted(Intent.APPROVE, approve_option=ApproveOption.BUDGET))
    h.fake.script("đặt vé", _scripted(Intent.BOOK))

    async def scenario():
        await _planned(h, "c-book")
        await h.say("c-book", "Duyệt BUDGET")
        await h.say("c-book", "đồng ý")
        asked = await h.say("c-book", "đặt vé")
        booked = await h.say("c-book", "đồng ý")
        key_first = h.chats.context("c-book").keys
        again = await h.say("c-book", "đặt vé")
        booked_again = await h.say("c-book", "đồng ý")
        return asked, booked, booked_again, key_first, h.chats.context("c-book").keys, again

    asked, booked, booked_again, key_first, key_after, again = _run(scenario)

    assert asked.pending_confirmation is not None
    assert asked.pending_confirmation["kind"] == "book"
    booking_cards = [card for card in booked.cards if isinstance(card, BookingCard)]
    assert booking_cards
    assert booking_cards[0].result.status == "BOOKED"
    assert booked_again.cards[0].result.intent_id == booking_cards[0].result.intent_id
    assert key_first == key_after
    assert len(key_after) == 1


# ---------------------------------------------------------------------------
# modify_plan, place_info, out_of_scope
# ---------------------------------------------------------------------------


def test_modify_plan_applies_the_change_to_the_latest_request_and_returns_a_new_version() -> None:
    h = Harness()
    h.fake.script(
        "thêm 1 ngày",
        _scripted(
            Intent.MODIFY_PLAN,
            changes=[PlanChange(kind=PlanChangeKind.ADD_DAYS, value=1, text="thêm 1 ngày")],
        ),
    )

    async def scenario():
        await _planned(h, "c-modify")
        return await h.say("c-modify", "thêm 1 ngày")

    reply = _run(scenario)

    card = _plan_card(reply)
    assert card.version == 2
    assert len(card.days) == 3
    assert "thêm 1 ngày" in reply.text
    assert h.store.latest(h.chats.context("c-modify").thread_id)["version"] == 2
    assert h.chats.context("c-modify").request["end_date"] == "2026-12-22"


def test_modify_without_a_plan_asks_to_plan_first() -> None:
    h = Harness()
    h.fake.script(
        "thêm 1 ngày",
        _scripted(Intent.MODIFY_PLAN, changes=[PlanChange(kind=PlanChangeKind.ADD_DAYS, value=1, text="")]),
    )

    reply = _run(lambda: h.say("c-modify-none", "thêm 1 ngày"))

    assert reply.text == texts.NO_PLAN


def test_place_info_answers_from_the_data_with_the_source_hours_and_no_llm_facts() -> None:
    h = Harness()
    h.fake.script(
        "Đại Nội có mở cửa lúc mấy giờ?",
        _scripted(
            Intent.PLACE_INFO,
            place_query=PlaceMention(text="Đại Nội", poi_id=DAI_NOI, name="Đại Nội Huế", score=1.0),
        ),
    )

    reply = _run(lambda: h.say("c-place", "Đại Nội có mở cửa lúc mấy giờ?"))

    assert DAI_NOI_HOURS in reply.text
    assert "chưa xác minh" in reply.text
    place_cards = [card for card in reply.cards if isinstance(card, PlaceCard)]
    assert place_cards[0].poi_id == DAI_NOI
    assert place_cards[0].opening_hours_raw == DAI_NOI_HOURS


def test_place_info_with_gan_lists_nearby_places_within_one_kilometre() -> None:
    h = Harness()
    text = "gần Đại Nội có quán nào không?"
    h.fake.script(
        text,
        _scripted(
            Intent.PLACE_INFO,
            place_query=PlaceMention(text="Đại Nội", poi_id=DAI_NOI, name="Đại Nội Huế", score=1.0),
        ),
    )

    reply = _run(lambda: h.say("c-nearby", text))

    assert "Gần đó (trong 1 km):" in reply.text
    assert "- Kinh Thành Huế (cách 0.04 km)" in reply.text
    assert reply.text.count("\n- ") == 5


def test_place_info_for_an_unknown_place_says_it_was_not_found() -> None:
    h = Harness()
    h.fake.script(
        "Chợ ma ở đâu?",
        _scripted(Intent.PLACE_INFO, place_query=PlaceMention(text="Chợ ma", poi_id=None, score=0.1)),
    )

    reply = _run(lambda: h.say("c-unknown-place", "Chợ ma ở đâu?"))

    assert reply.text == texts.PLACE_MISSING


def test_out_of_scope_gets_a_polite_refusal() -> None:
    h = Harness()

    reply = _run(lambda: h.say("c-scope", "Đi Đà Nẵng 3 ngày từ 10/12"))

    assert reply.understanding.intent == "out_of_scope"
    assert "chỉ lên kế hoạch cho chuyến đi Huế" in reply.text
    assert h.starts == []


def test_every_reply_carries_the_understanding_source() -> None:
    h = Harness()
    h.fake.script("Ngoài lề", _scripted(Intent.OUT_OF_SCOPE))

    async def scenario():
        first = await h.say("c-source", "Đi Huế 2 ngày")
        second = await h.say("c-source", "Ngoài lề")
        return first, second

    first, second = _run(scenario)

    assert first.understanding.source == "RULES"
    assert second.understanding.source == "OLLAMA"


# ---------------------------------------------------------------------------
# owners and history
# ---------------------------------------------------------------------------


def test_another_user_cannot_write_to_a_conversation() -> None:
    async def scenario():
        h = Harness()
        await h.say("c-owner", "Đi Huế 2 ngày")
        with pytest.raises(PermissionError):
            await h.say("c-owner", "Đi Huế 3 ngày", user="bob")

    _run(scenario)


def test_history_lists_the_turns_in_order_and_refuses_another_owner() -> None:
    async def scenario():
        h = Harness()
        await h.say("c-history", "Đi Huế 2 ngày")
        await h.say("c-history", "20/12")
        history = h.service.history("c-history", USER)
        with pytest.raises(PermissionError):
            h.service.history("c-history", "bob")
        with pytest.raises(LookupError):
            h.service.history("c-missing", USER)
        return history

    history = _run(scenario)

    assert [message["role"] for message in history] == ["user", "assistant", "user", "assistant"]
    assert history[0]["text"] == "Đi Huế 2 ngày"
    assert history[1]["payload"]["understanding"]["source"] == "RULES"


def test_context_round_trips_through_json() -> None:
    context = ChatContext(draft={"num_days": 2}, thread_id="t", pending={"kind": "defaults"}, keys={"q": "k"})

    assert ChatContext.from_json(context.to_json()) == context
    assert ChatContext.from_json(None) == ChatContext()
