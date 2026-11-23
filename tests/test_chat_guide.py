"""Place descriptions in chat (S10): the stored guide or summary answers "có gì hay" questions, facts questions
keep the RAG or template path, and a place without any description says so."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.chat import texts  # noqa: E402
from app.chat.schemas import PlaceCard  # noqa: E402
from app.repositories.hue_places import HuePlacesRepository  # noqa: E402
from app.services import guide  # noqa: E402
from app.understanding.models import Intent, PlaceMention  # noqa: E402

# Reuse the chat harness and the scripted understanding from the chat service suite.
from test_chat_service import DAI_NOI, DAI_NOI_HOURS, FakeRag, Harness, _rag_answer, _scripted, _to_summary  # noqa: E402

DAI_NOI_LEAD = (
    "Đại Nội là quần thể cung điện ở Huế. Khu này được xây dựng từ đầu thế kỷ 19. "
    "Đây là di sản văn hóa thế giới."
)
WIKI_URL = "https://vi.wikipedia.org/wiki/%C4%90%E1%BA%A1i_N%E1%BB%99i"


def _place_mention(poi_id: str) -> PlaceMention:
    return PlaceMention(text="x", poi_id=poi_id, name="x", score=1.0)


@pytest.fixture
def fixture_corpus(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "guide_corpus.json"
    path.write_text(
        json.dumps(
            {
                DAI_NOI: {
                    "title": "Đại Nội",
                    "url": WIKI_URL,
                    "license": "CC BY-SA 4.0",
                    "authors_url": WIKI_URL + "?action=history",
                    "retrieved_at": "2026-11-24",
                    "lead": DAI_NOI_LEAD,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(guide, "GUIDE_PATH", path)
    return path


def _poi_without(predicate) -> Any:
    repo = HuePlacesRepository(BACKEND / "data" / "hue.sqlite")
    for place in repo.list_all():
        if predicate(place) and guide.guide_for(place.id) is None:
            return place
    raise AssertionError("no matching POI in the Hue source")


def _ask(h: Harness, conversation: str, text: str, poi_id: str | None, intent: Intent = Intent.PLACE_INFO) -> Any:
    mention = _place_mention(poi_id) if poi_id is not None else None
    h.fake.script(text, _scripted(intent, place_query=mention))
    return asyncio.run(h.say(conversation, text))


def test_description_question_is_answered_from_the_guide_without_rag(fixture_corpus) -> None:
    h = Harness()
    h.service.rag = FakeRag(_rag_answer([DAI_NOI]))
    h.service.handler_log = []
    reply = _ask(h, "g-guide", "Đại Nội có gì hay?", DAI_NOI)

    name = h.repo.get_by_id(DAI_NOI).name
    assert reply.text == (
        f"{name}: Đại Nội là quần thể cung điện ở Huế. Khu này được xây dựng từ đầu thế kỷ 19. "
        "Đây là di sản văn hóa thế giới.\n"
        f"Nguồn: Wikipedia tiếng Việt (CC BY-SA 4.0) · {WIKI_URL}"
    )
    assert [card.poi_id for card in reply.cards if isinstance(card, PlaceCard)] == [DAI_NOI]
    assert h.service.rag.questions == []
    assert h.service.handler_log == ["place_info", "guide"]


@pytest.mark.parametrize("question", ["Đại Nội giới thiệu về nơi này", "Đại Nội có lịch sử thế nào?"])
def test_other_description_cues_also_use_the_guide(fixture_corpus, question: str) -> None:
    h = Harness()
    h.service.rag = FakeRag(_rag_answer([DAI_NOI]))
    reply = _ask(h, "g-cues", question, DAI_NOI)
    assert "Nguồn: Wikipedia tiếng Việt" in reply.text
    assert h.service.rag.questions == []


def test_facts_question_keeps_the_rag_path_even_with_a_guide(fixture_corpus) -> None:
    h = Harness()
    h.service.rag = FakeRag(_rag_answer([DAI_NOI]))
    reply = _ask(h, "g-facts", "Đại Nội mở cửa mấy giờ?", DAI_NOI)
    assert reply.text == "Đại Nội mở 07:30-17:30."
    assert h.service.rag.questions == ["Đại Nội mở cửa mấy giờ?"]
    assert "Wikipedia" not in reply.text


def test_facts_question_uses_the_template_when_there_is_no_rag(fixture_corpus) -> None:
    h = Harness()
    reply = _ask(h, "g-template", "Đại Nội mở cửa mấy giờ?", DAI_NOI)
    assert DAI_NOI_HOURS in reply.text
    assert "Wikipedia" not in reply.text


def test_place_without_guide_gets_the_huetripo_summary(fixture_corpus) -> None:
    h = Harness()
    h.service.rag = FakeRag(_rag_answer([]))
    place = _poi_without(lambda p: bool(p.summary))
    reply = _ask(h, "g-summary", f"{place.name} có gì hay?", place.id)
    assert reply.text.startswith(f"{place.name}: ")
    assert "Nguồn: huetripo.hue.gov.vn" in reply.text
    assert h.service.rag.questions == []


def test_place_without_guide_or_summary_says_the_source_has_no_description(fixture_corpus) -> None:
    h = Harness()
    place = _poi_without(lambda p: not p.summary)
    reply = _ask(h, "g-none", f"{place.name} có gì hay?", place.id)
    assert reply.text.endswith(texts.NO_DESCRIPTION)
    assert "Nguồn: Wikipedia" not in reply.text


def test_description_question_without_a_linked_place_uses_the_old_path(fixture_corpus) -> None:
    h = Harness()
    reply = _ask(h, "g-unlinked", "Huế có gì hay?", None)
    assert texts.PLACE_MISSING in reply.text
    assert texts.NO_DESCRIPTION not in reply.text


def test_real_corpus_answers_song_huong_with_its_article() -> None:
    # Hồ Thủy Tiên has no lake article in the committed corpus (see the build script), so the real-data check uses Sông Hương.
    poi_id = "huetripo:512284"
    assert guide.guide_for(poi_id) is not None, "Sông Hương must stay in the committed corpus"
    h = Harness()
    h.service.rag = FakeRag(_rag_answer([]))
    reply = _ask(h, "g-real", "Sông Hương có gì hay?", poi_id)
    assert reply.text.startswith("Sông Hương: ")
    assert "Nguồn: Wikipedia tiếng Việt (CC BY-SA 4.0) · https://vi.wikipedia.org/wiki/" in reply.text
    assert h.service.rag.questions == []


def test_a_description_question_at_the_summary_leaves_the_summary_waiting(fixture_corpus) -> None:
    h = Harness()
    h.fake.script("Đại Nội có gì hay?", _scripted(Intent.PLACE_INFO, place_query=_place_mention(DAI_NOI)))

    async def scenario():
        await _to_summary(h, "g-summary-wait")
        answer = await h.say("g-summary-wait", "Đại Nội có gì hay?")
        kept = h.chats.context("g-summary-wait").pending
        planned = await h.say("g-summary-wait", "ok")
        return answer, kept, planned

    answer, kept, planned = asyncio.run(scenario())
    assert "Nguồn: Wikipedia tiếng Việt" in answer.text
    assert kept == {"kind": "confirm_trip"}
    assert len(h.starts) == 1
    assert planned.cards
