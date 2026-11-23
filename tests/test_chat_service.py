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


PLAN_TRIP = "Đi Huế 2 ngày từ 20/12 từ Hà Nội 2 người ngân sách 5 triệu thích ẩm thực"


# ---------------------------------------------------------------------------
# plan_new: open slots are asked until the trip is specified, then the plan starts
# ---------------------------------------------------------------------------


def _slot(fields: dict[str, Any], **kwargs: Any) -> ParsedQuery:
    """A scripted answer to an open slot: a plan message that carries these fields."""
    return _scripted(Intent.PLAN_NEW, clarification="Bạn cho mình thêm thông tin nhé?", fields=fields, **kwargs)


def _is_summary(reply: ChatReply) -> bool:
    return (reply.pending_confirmation or {}).get("kind") == "confirm_trip"


async def _plan_ready(h: Harness, conversation: str) -> ChatReply:
    """The trip in one message, then "tùy" to each optional question, then "ok" to the summary (S4)."""
    reply = await h.say(conversation, PLAN_TRIP)
    for _ in range(4):
        if any(isinstance(card, PlanCard) for card in reply.cards):
            break
        reply = await h.say(conversation, "ok" if _is_summary(reply) else "tùy")
    return reply


def test_missing_start_and_duration_asks_for_them_and_stores_the_draft() -> None:
    async def scenario():
        h = Harness()
        reply = await h.say("c-clarify", "Đi Huế đi chơi vui")
        return h, reply

    h, reply = _run(scenario)

    assert reply.quick_replies == []
    assert "ngày nào" in reply.text
    assert reply.pending_confirmation is None
    assert h.starts == []
    assert "start_date" not in h.chats.context("c-clarify").draft
    assert "num_days" not in h.chats.context("c-clarify").draft


def test_a_stated_length_is_merged_and_the_next_two_open_slots_are_asked() -> None:
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
    assert second.text.endswith("1. Bạn xuất phát từ đâu?\n2. Bạn đi mấy người?")
    assert second.pending_confirmation is None
    assert h.starts == []


def test_missing_origin_and_people_are_asked_and_no_plan_starts() -> None:
    async def scenario():
        h = Harness()
        reply = await h.say("c-ask-two", "Đi Huế 2 ngày từ 20/12")
        return h, reply

    h, reply = _run(scenario)

    assert reply.text.endswith("1. Bạn xuất phát từ đâu?\n2. Bạn đi mấy người?")
    assert reply.quick_replies == []
    assert reply.pending_confirmation is None
    assert h.starts == []
    assert h.chats.context("c-ask-two").thread_id is None


def test_a_plan_message_during_slot_filling_fills_the_draft_and_the_plan_waits_for_the_rest() -> None:
    h = Harness()
    h.fake.script(
        "Từ Hà Nội, 2 người",
        _scripted(
            Intent.MODIFY_PLAN,
            fields={"origin": "Hà Nội", "destination": "Huế", "people": 2},
            changes=[PlanChange(kind=PlanChangeKind.SET_PEOPLE, value=2, text="2 người")],
        ),
    )

    async def scenario():
        await h.say("c-modify-draft", "Đi Huế 3 ngày từ 28/11")
        return await h.say("c-modify-draft", "Từ Hà Nội, 2 người")

    reply = _run(scenario)
    draft = h.chats.context("c-modify-draft").draft

    assert reply.text.endswith("1. Ngân sách khoảng bao nhiêu cho cả chuyến?\n2. " + texts.QUESTIONS["interests"])
    assert draft["origin"] == "Hà Nội"
    assert draft["people"] == 2
    assert h.starts == []


def test_target_conversation_asks_each_open_slot_and_starts_the_plan_only_after_the_last_one() -> None:
    h = Harness()
    h.fake.script(
        "tôi muốn đi Huế 3 ngày 2 đêm với người yêu",
        _slot({"destination": "Huế", "num_days": 3, "people": 2}),
    )
    h.fake.script("ngày mai", _slot({"start_date": date(2026, 11, 24)}))
    h.fake.script(
        "6 triệu; ẩm thực, thiên nhiên, ngắm cảnh",
        _slot({"budget_vnd": 6_000_000, "categories": ["restaurant", "cafe", "attraction"]}),
    )
    messages = [
        "tôi muốn đi Huế 3 ngày 2 đêm với người yêu",
        "ngày mai",
        "Hà Nội",
        "6 triệu; ẩm thực, thiên nhiên, ngắm cảnh",
        "giữ 6 triệu, xe giường nằm, homestay",
        "thong thả, không",
        "ok",
    ]

    async def scenario():
        return [await h.say("c-target", text) for text in messages]

    replies = _run(scenario)
    first, second, third, fourth, fifth, summary, last = replies

    assert first.text.splitlines()[-2:] == ["1. Bạn muốn đi Huế từ ngày nào?", "2. Bạn xuất phát từ đâu?"]
    assert second.text.splitlines()[0] == "Mình ghi nhận: Huế, 2 người, thứ Ba 24/11 – thứ Năm 26/11 (3 ngày 2 đêm)."
    assert second.text.splitlines()[-2:] == ["1. Bạn xuất phát từ đâu?", "2. Ngân sách khoảng bao nhiêu cho cả chuyến?"]
    assert third.text.splitlines()[-2:] == ["1. Ngân sách khoảng bao nhiêu cho cả chuyến?", "2. " + texts.QUESTIONS["interests"]]
    assert fourth.text.splitlines()[-2:] == ["1. " + texts.QUESTIONS["transport"], "2. " + texts.QUESTIONS["stay"]]
    assert fifth.text.splitlines()[-2:] == ["1. " + texts.QUESTIONS["pace"], "2. " + texts.QUESTIONS["places"]]
    for reply in replies[:5]:
        assert reply.cards == [] and reply.quick_replies == [] and reply.pending_confirmation is None
    assert summary.text.startswith(texts.SUMMARY_HEAD) and _is_summary(summary)
    assert _plan_card(last).version == 1
    assert len(h.starts) == 1
    assert (h.starts[0].origin, h.starts[0].people) == ("Hà Nội", 2)
    assert h.starts[0].start_date == date(2026, 11, 24)
    assert h.starts[0].end_date == date(2026, 11, 26)
    assert h.starts[0].budget_vnd == 6_000_000


def test_an_early_answer_fills_transport_and_stay_so_they_are_never_asked() -> None:
    h = Harness()
    h.fake.script("5 triệu, ẩm thực", _slot({"budget_vnd": 8_000_000, "categories": ["restaurant"]}))

    async def scenario():
        first = await h.say("c-early", "Đi Huế 3 ngày từ 28/11 từ Hà Nội 2 người, xe giường nằm, homestay")
        second = await h.say("c-early", "5 triệu, ẩm thực")
        return first, second

    first, second = _run(scenario)
    draft = h.chats.context("c-early").draft

    assert first.text.splitlines()[-2:] == ["1. Ngân sách khoảng bao nhiêu cho cả chuyến?", "2. " + texts.QUESTIONS["interests"]]
    assert draft["transport_mode"] == "bus"
    assert draft["hotel_tier"] == "homestay"
    assert texts.QUESTIONS["transport"] not in second.text
    assert texts.QUESTIONS["stay"] not in second.text
    assert second.text.splitlines()[-2:] == ["1. " + texts.QUESTIONS["pace"], "2. " + texts.QUESTIONS["places"]]


def test_tuy_settles_the_optional_questions_that_were_asked() -> None:
    async def scenario():
        h = Harness()
        first = await h.say("c-tuy", PLAN_TRIP)
        second = await h.say("c-tuy", "tùy")
        draft = h.chats.context("c-tuy").draft
        third = await h.say("c-tuy", "thong thả, không")
        fourth = await h.say("c-tuy", "ok")
        return h, first, second, draft, third, fourth

    h, first, second, draft, third, fourth = _run(scenario)

    assert first.text.splitlines()[-2:] == ["1. " + texts.QUESTIONS["transport"], "2. " + texts.QUESTIONS["stay"]]
    assert draft["transport_mode"] == "any"
    assert draft["hotel_tier"] == "any"
    assert second.text.splitlines()[-2:] == ["1. " + texts.QUESTIONS["pace"], "2. " + texts.QUESTIONS["places"]]
    assert third.text.startswith(texts.SUMMARY_HEAD)
    assert _plan_card(fourth)
    assert len(h.starts) == 1


def test_no_quick_replies_while_the_slots_are_open() -> None:
    messages = ["Đi Huế 2 ngày", "20/12", "Hà Nội", "2 người", "5 triệu", "ẩm thực", "tùy", "tùy", "ok"]

    async def scenario():
        h = Harness()
        return [await h.say("c-no-replies", text) for text in messages]

    replies = _run(scenario)

    for reply in replies[:-2]:
        assert reply.quick_replies == [], reply.text
        assert reply.pending_confirmation is None
    assert replies[-2].quick_replies == [] and _is_summary(replies[-2])
    assert _plan_card(replies[-1])
    assert replies[-1].quick_replies == [f"Duyệt {option.label}" for option in _plan_card(replies[-1]).budget_options]


def test_a_place_question_during_slot_filling_is_answered_and_the_draft_is_kept() -> None:
    h = Harness()

    async def scenario():
        await h.say("c-place-draft", "Đi Huế 2 ngày từ 20/12")
        before = dict(h.chats.context("c-place-draft").draft)
        reply = await h.say("c-place-draft", "Đại Nội có mở cửa lúc mấy giờ?")
        after = dict(h.chats.context("c-place-draft").draft)
        h.fake.script("Từ Hà Nội, 2 người", _slot({"origin": "Hà Nội", "people": 2}))
        answered = await h.say("c-place-draft", "Từ Hà Nội, 2 người")
        return before, reply, after, answered

    before, reply, after, answered = _run(scenario)

    assert DAI_NOI_HOURS in reply.text
    assert any(isinstance(card, PlaceCard) for card in reply.cards)
    assert after == before
    assert answered.text.splitlines()[-2:] == ["1. " + texts.QUESTIONS["budget"], "2. " + texts.QUESTIONS["interests"]]
    assert h.starts == []


def test_weather_and_another_city_during_slot_filling_keep_their_own_replies() -> None:
    async def scenario():
        h = Harness()
        await h.say("c-scope-draft", "Đi Huế 2 ngày từ 20/12")
        weather = await h.say("c-scope-draft", "Huế mai có mưa không?")
        other = await h.say("c-scope-draft", "Đi Đà Nẵng 3 ngày từ 10/12")
        return h, weather, other

    h, weather, other = _run(scenario)

    assert weather.text == texts.WEATHER
    assert other.text == texts.OUT_OF_SCOPE
    assert h.chats.context("c-scope-draft").draft["start_date"] == "2026-12-20"
    assert h.starts == []


def test_an_unrelated_answer_asks_the_open_slots_again_and_never_starts_a_plan() -> None:
    async def scenario():
        h = Harness()
        await h.say("c-noguess", "Đi Huế 2 ngày từ 20/12")
        reply = await h.say("c-noguess", "để mình suy nghĩ thêm")
        return h, reply

    h, reply = _run(scenario)

    assert reply.text.endswith("1. Bạn xuất phát từ đâu?\n2. Bạn đi mấy người?")
    assert h.starts == []


def test_a_stated_origin_and_people_are_merged_and_the_plan_starts_after_the_optional_questions() -> None:
    async def scenario():
        h = Harness()
        reply = await _plan_ready(h, "c-plan")
        return h, reply

    h, reply = _run(scenario)

    card = _plan_card(reply)
    assert len(h.starts) == 1
    assert h.starts[0].origin == "Hà Nội"
    assert h.starts[0].people == 2
    assert card.version == 1
    assert len(card.days) == 2
    assert all(item.kind in ("VISIT", "MEAL", "MEAL_BREAK", "REST") for day in card.days for item in day.items)
    assert card.budget_options
    assert reply.quick_replies == [f"Duyệt {option.label}" for option in card.budget_options]
    assert reply.understanding.source == "RULES"


def test_plan_items_carry_poi_ids_for_places_and_none_for_meal_breaks() -> None:
    h = Harness()

    async def scenario():
        return await _planned(h, "c-poi-ids")

    card = _run(scenario)

    items = [item for day in card.days for item in day.items]
    assert any(item.poi_id is not None and item.poi_id.startswith("huetripo:") for item in items)
    assert all(item.poi_id is None for item in items if item.kind == "MEAL_BREAK")


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
    return _plan_card(await _plan_ready(h, conversation))


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
    context = ChatContext(draft={"num_days": 2}, thread_id="t", pending={"kind": "approve", "option": "BUDGET", "version": 1}, keys={"q": "k"})

    assert ChatContext.from_json(context.to_json()) == context
    assert ChatContext.from_json(None) == ChatContext()


# ---------------------------------------------------------------------------
# place_info through RAG, handler log
# ---------------------------------------------------------------------------


class FakeRag:
    """Returns a fixed RagAnswer, or raises, and records the questions it got."""

    def __init__(self, answer: Any = None, error: Exception | None = None) -> None:
        self.answer_value, self.error, self.questions = answer, error, []

    def answer(self, question: str, parsed: Any = None) -> Any:
        self.questions.append(question)
        if self.error is not None:
            raise self.error
        return self.answer_value


def _rag_answer(cited: list[str], text: str = "Đại Nội mở 07:30-17:30.") -> Any:
    from app.rag.answer import RagAnswer
    from app.rag.retrieve import Hit, RetrievalResult

    retrieval = RetrievalResult(hits=[Hit(poi_id=i, score=1.0) for i in cited], mode="bm25")
    return RagAnswer(text, text, cited, bool(cited), "llm" if cited else "refusal", retrieval)


def test_place_info_uses_rag_and_shows_cards_for_cited_places() -> None:
    async def scenario():
        h = Harness()
        h.service.rag = FakeRag(_rag_answer([DAI_NOI]))
        h.fake.script("Đại Nội mấy giờ mở cửa?", _scripted(Intent.PLACE_INFO))
        reply = await h.say("c-rag", "Đại Nội mấy giờ mở cửa?")
        assert reply.text == "Đại Nội mở 07:30-17:30."
        assert [card.poi_id for card in reply.cards if isinstance(card, PlaceCard)] == [DAI_NOI]
        assert h.service.last_rag is not None and h.service.last_rag.source == "llm"
        assert h.service.rag.questions == ["Đại Nội mấy giờ mở cửa?"]

    _run(scenario)


def test_place_info_falls_back_to_the_template_when_rag_raises() -> None:
    async def scenario():
        h = Harness()
        h.service.rag = FakeRag(error=RuntimeError("boom"))
        mention = PlaceMention(text="Đại Nội", poi_id=DAI_NOI, name="Đại Nội", score=1.0)
        h.fake.script("Đại Nội ở đâu?", _scripted(Intent.PLACE_INFO, place_query=mention))
        reply = await h.say("c-rag-fail", "Đại Nội ở đâu?")
        assert DAI_NOI_HOURS in reply.text
        assert h.service.last_rag is None

    _run(scenario)


def test_handler_log_records_one_name_per_turn() -> None:
    async def scenario():
        h = Harness()
        h.service.handler_log = []
        h.fake.script("Thời tiết thế nào?", _scripted(Intent.OUT_OF_SCOPE))
        await h.say("c-log", "Thời tiết thế nào?")
        await h.say("c-log", PLAN_TRIP)
        assert h.service.handler_log == ["out_of_scope", "plan_new"]

    _run(scenario)


# ---------------------------------------------------------------------------
# Smalltalk and weather: fixed templates, no quick replies
# ---------------------------------------------------------------------------


def test_greeting_gets_the_assistant_intro_and_an_example_without_quick_replies() -> None:
    async def scenario():
        h = Harness()
        return await h.say("c-hello", "xin chào")

    reply = _run(scenario)

    assert "trợ lý lập lịch du lịch Huế" in reply.text
    assert texts.SMALLTALK_EXAMPLE in reply.text
    assert reply.quick_replies == []
    assert reply.understanding.intent == "smalltalk"


def test_thanks_after_a_plan_gets_the_waiting_nudge_and_no_quick_replies() -> None:
    async def scenario():
        h = Harness()
        await _planned(h, "c-thanks")
        reply = await h.say("c-thanks", "cảm ơn bạn")
        return h, reply

    h, reply = _run(scenario)

    assert texts.THANKS in reply.text
    assert texts.PLAN_WAITING_NUDGE in reply.text
    assert reply.quick_replies == []
    assert len(h.starts) == 1


def test_weather_question_gets_the_weather_refusal() -> None:
    async def scenario():
        h = Harness()
        h.fake.script("Huế mai có mưa không?", _scripted(Intent.OUT_OF_SCOPE))
        return await h.say("c-weather", "Huế mai có mưa không?")

    reply = _run(scenario)

    assert reply.text == texts.WEATHER
    assert reply.quick_replies == []


# ---------------------------------------------------------------------------
# Early budget check (S2) turn by turn: 3 triệu, bus, homestay, food, 2 people, 3 days
# ---------------------------------------------------------------------------

WARN_TRIP = "Đi Huế 3 ngày từ 05/12 từ Hà Nội 2 người"
WARN_BUDGET = "3 triệu, ẩm thực"
WARN_STAY = "xe giường nằm, homestay"
WARN_LINE = (
    "Lưu ý: phương án rẻ nhất (xe khách + homestay) ước tính 5,15–6,16 triệu, "
    "vượt ngân sách 2,15–3,16 triệu. Bạn muốn tăng ngân sách, hay giữ 3 triệu để mình chọn phương án tiết kiệm nhất?"
)


def _warning_harness(conversation: str) -> tuple[Harness, list[str]]:
    """A harness scripted for the over-budget trip; returns it with the messages up to the stay answer."""
    h = Harness()
    h.fake.script(WARN_TRIP, _slot({"origin": "Hà Nội", "people": 2, "start_date": date(2026, 12, 5), "num_days": 3}))
    h.fake.script(WARN_BUDGET, _slot({"budget_vnd": 3_000_000, "categories": ["restaurant", "cafe", "market"]}))
    h.fake.script(WARN_STAY, _slot({}))
    return h, [WARN_TRIP, WARN_BUDGET, WARN_STAY]


def test_over_budget_pre_check_warns_on_the_turn_after_stay_and_the_plan_does_not_start() -> None:
    h, messages = _warning_harness("c-warn")

    async def scenario():
        return [await h.say("c-warn", text) for text in messages]

    first, second, third = _run(scenario)

    assert first.text.splitlines()[-2:] == ["1. " + texts.QUESTIONS["budget"], "2. " + texts.QUESTIONS["interests"]]
    assert second.text.splitlines()[-2:] == ["1. " + texts.QUESTIONS["transport"], "2. " + texts.QUESTIONS["stay"]]
    assert "vượt ngân sách" in third.text
    assert third.text.splitlines()[-1] == WARN_LINE  # asked alone
    assert all(not isinstance(card, PlanCard) for card in third.cards)
    assert third.pending_confirmation is None
    assert h.starts == []
    context = h.chats.context("c-warn")
    assert context.thread_id is None
    assert context.draft["precheck"]["min"] == 5_150_000
    assert context.draft["precheck"]["max"] == 6_160_000
    assert (context.draft["precheck"]["mode"], context.draft["precheck"]["tier"]) == ("BUS", "HOMESTAY")


def test_keeping_the_budget_moves_on_to_the_next_open_question() -> None:
    h, messages = _warning_harness("c-keep")
    h.fake.script("giữ", _slot({}))
    h.fake.script("thong thả, không", _slot({}))

    async def scenario():
        for text in messages:
            await h.say("c-keep", text)
        kept = await h.say("c-keep", "giữ")
        draft_after_keep = dict(h.chats.context("c-keep").draft)
        await h.say("c-keep", "thong thả, không")
        planned = await h.say("c-keep", "ok")
        return kept, draft_after_keep, planned

    kept, draft_after_keep, planned = _run(scenario)

    assert "vượt ngân sách" not in kept.text
    # The budget check is asked alone, so "giữ" settles only it: pace is still open and asked
    # now with the places question instead of being lost as "tùy".
    assert kept.text.splitlines()[-2:] == ["1. " + texts.QUESTIONS["pace"], "2. " + texts.QUESTIONS["places"]]
    assert draft_after_keep["budget_accepted"] is True
    assert "pace" not in draft_after_keep
    assert h.starts[0].budget_vnd == 3_000_000
    assert _plan_card(planned).version == 1
    assert len(h.starts) == 1


def test_keeping_the_budget_by_repeating_the_current_amount_counts_as_keep() -> None:
    h, messages = _warning_harness("c-same")
    h.fake.script("giữ 3 triệu", _slot({"budget_vnd": 3_000_000}))

    async def scenario():
        for text in messages:
            await h.say("c-same", text)
        return await h.say("c-same", "giữ 3 triệu")

    reply = _run(scenario)

    assert "vượt ngân sách" not in reply.text
    assert reply.text.splitlines()[-2:] == ["1. " + texts.QUESTIONS["pace"], "2. " + texts.QUESTIONS["places"]]


def test_a_higher_budget_reruns_the_check_and_asks_the_next_unit_without_a_warning() -> None:
    h, messages = _warning_harness("c-raise")
    h.fake.script("10 triệu", _slot({"budget_vnd": 10_000_000}))

    async def scenario():
        for text in messages:
            await h.say("c-raise", text)
        return await h.say("c-raise", "10 triệu")

    reply = _run(scenario)
    context = h.chats.context("c-raise")

    assert "vượt ngân sách" not in reply.text
    assert reply.text.splitlines()[-2:] == ["1. " + texts.QUESTIONS["pace"], "2. " + texts.QUESTIONS["places"]]
    assert context.draft["budget_vnd"] == 10_000_000
    assert context.draft["precheck"]["min"] == 5_150_000
    assert h.starts == []


def test_an_unrelated_answer_to_the_budget_warning_asks_it_again() -> None:
    h, messages = _warning_harness("c-again")
    h.fake.script("hmm để xem", _slot({}))

    async def scenario():
        for text in messages:
            await h.say("c-again", text)
        return await h.say("c-again", "hmm để xem")

    reply = _run(scenario)

    # The unanswered pace question is settled by this message (the optional-slot rule); the budget is asked again.
    assert reply.text.splitlines()[-1] == WARN_LINE  # asked alone
    assert h.starts == []


# ---------------------------------------------------------------------------
# Summary before planning (S4) and edits at the summary (S5)
# ---------------------------------------------------------------------------


async def _to_summary(h: Harness, conversation: str) -> ChatReply:
    """The trip in one message, then "tùy" to the two optional questions: the summary waits."""
    reply = await h.say(conversation, PLAN_TRIP)
    for _ in range(2):
        reply = await h.say(conversation, "tùy")
    return reply


def _summary_lines(reply: ChatReply) -> list[str]:
    return [line for line in reply.text.splitlines() if line.startswith("- ")]


def test_a_complete_draft_gets_the_summary_and_no_plan_starts() -> None:
    async def scenario():
        h = Harness()
        return h, await _to_summary(h, "c-summary")

    h, reply = _run(scenario)

    assert reply.text.startswith(texts.SUMMARY_HEAD)
    assert reply.text.endswith(texts.SUMMARY_TAIL)
    assert reply.pending_confirmation == {"kind": "confirm_trip"}
    assert reply.cards == [] and reply.quick_replies == []
    assert h.starts == []
    assert not any(line.endswith(texts.CHANGED_MARK) for line in reply.text.splitlines())


def test_ok_at_the_summary_starts_exactly_one_plan() -> None:
    async def scenario():
        h = Harness()
        await _to_summary(h, "c-ok")
        return h, await h.say("c-ok", "ok")

    h, reply = _run(scenario)

    assert _plan_card(reply).version == 1
    assert len(h.starts) == 1
    assert h.chats.context("c-ok").draft == {}


def test_a_pace_step_at_the_summary_resends_it_with_the_pace_marked_and_no_plan() -> None:
    async def scenario():
        h = Harness()
        await _to_summary(h, "c-pace")
        reply = await h.say("c-pace", "thêm số lượng điểm đến")
        return h, reply

    h, reply = _run(scenario)

    assert _summary_lines(reply)[4] == "- Nhịp độ: đi nhiều, 5 điểm tham quan mỗi ngày ← đã đổi"
    marked = [line for line in reply.text.splitlines() if line.endswith(texts.CHANGED_MARK)]
    assert marked == [_summary_lines(reply)[4]]
    assert reply.pending_confirmation == {"kind": "confirm_trip"}
    assert h.starts == []


def test_a_budget_edit_at_the_summary_reruns_the_check_and_marks_only_the_budget() -> None:
    h = Harness()
    h.fake.script("8 triệu", _slot({"budget_vnd": 8_000_000}))

    async def scenario():
        before = await _to_summary(h, "c-budget")
        after = await h.say("c-budget", "8 triệu")
        return before, after

    before, after = _run(scenario)

    marked = [line for line in after.text.splitlines() if line.endswith(texts.CHANGED_MARK)]
    assert len(marked) == 1 and marked[0].startswith("- Ngân sách: 8 triệu")
    assert after.pending_confirmation == {"kind": "confirm_trip"}
    assert h.starts == []
    assert h.chats.context("c-budget").draft["budget_vnd"] == 8_000_000
    assert "precheck" in h.chats.context("c-budget").draft


def test_a_cancel_word_keeps_the_draft_and_no_plan_starts() -> None:
    async def scenario():
        h = Harness()
        await _to_summary(h, "c-cancel")
        reply = await h.say("c-cancel", "huỷ")
        return h, reply

    h, reply = _run(scenario)

    assert reply.text == texts.CANCELLED
    assert reply.pending_confirmation is None
    assert h.starts == []
    draft = h.chats.context("c-cancel").draft
    assert draft["origin"] == "Hà Nội" and draft["budget_vnd"] == 5_000_000


def test_a_place_question_at_the_summary_is_answered_and_ok_still_starts_the_plan() -> None:
    h = Harness()
    h.fake.script(
        "Đại Nội có mở cửa lúc mấy giờ?",
        _scripted(
            Intent.PLACE_INFO,
            place_query=PlaceMention(text="Đại Nội", poi_id=DAI_NOI, name="Đại Nội Huế", score=1.0),
        ),
    )

    async def scenario():
        await _to_summary(h, "c-question")
        answer = await h.say("c-question", "Đại Nội có mở cửa lúc mấy giờ?")
        kept = h.chats.context("c-question").pending
        planned = await h.say("c-question", "ok")
        return answer, kept, planned

    answer, kept, planned = _run(scenario)

    assert DAI_NOI_HOURS in answer.text
    assert answer.text != texts.CANCELLED
    assert kept == {"kind": "confirm_trip"}
    assert _plan_card(planned).version == 1
    assert len(h.starts) == 1


def test_smalltalk_at_the_summary_keeps_the_summary_waiting() -> None:
    async def scenario():
        h = Harness()
        await _to_summary(h, "c-thanks-summary")
        reply = await h.say("c-thanks-summary", "cảm ơn bạn")
        return h, reply

    h, reply = _run(scenario)

    assert texts.THANKS in reply.text
    assert h.chats.context("c-thanks-summary").pending == {"kind": "confirm_trip"}
    assert h.starts == []


def test_a_confirming_word_after_the_summary_is_not_read_as_an_edit() -> None:
    async def scenario():
        h = Harness()
        await _to_summary(h, "c-lich")
        return h, await h.say("c-lich", "Lên lịch!")

    h, reply = _run(scenario)

    assert _plan_card(reply).version == 1
    assert len(h.starts) == 1
