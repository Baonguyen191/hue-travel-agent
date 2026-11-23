"""Tour-guide text: sentence split, the 1200 and 160 character limits, the corpus loader and the real corpus."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
HUE_DB = BACKEND / "data" / "hue.sqlite"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.repositories.hue_places import HuePlacesRepository  # noqa: E402
from app.services import guide  # noqa: E402
from app.services.guide import (  # noqa: E402
    ELLIPSIS,
    INTRO_LIMIT,
    TEXT_LIMIT,
    guide_for,
    guide_sentences,
    intro_for,
    split_sentences,
    trim_text,
)

LEAD = (
    "Hồ Thủy Tiên là một hồ nhân tạo ở Huế. Hồ nằm gần đồi Vọng Cảnh và được xây năm 1820. "
    "Nước hồ trong xanh quanh năm? Khách đến thường ngắm hoàng hôn! Cảnh rất đẹp."
)


def write_corpus(path: Path, corpus: dict) -> Path:
    path.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
    return path


def entry(lead: str, title: str = "Hồ Thủy Tiên") -> dict[str, str]:
    return {
        "title": title,
        "url": "https://vi.wikipedia.org/wiki/H%E1%BB%93_Th%E1%BB%A7y_Ti%C3%AAn",
        "license": "CC BY-SA 4.0",
        "authors_url": "https://vi.wikipedia.org/wiki/H%E1%BB%93_Th%E1%BB%A7y_Ti%C3%AAn?action=history",
        "retrieved_at": "2026-11-24",
        "lead": lead,
    }


@pytest.fixture
def corpus_path(tmp_path, monkeypatch) -> Path:
    path = write_corpus(tmp_path / "guide_corpus.json", {"huetripo:1": entry(LEAD)})
    monkeypatch.setattr(guide, "GUIDE_PATH", path)
    return path


def test_split_sentences_on_terminators() -> None:
    assert split_sentences(LEAD) == [
        "Hồ Thủy Tiên là một hồ nhân tạo ở Huế.",
        "Hồ nằm gần đồi Vọng Cảnh và được xây năm 1820.",
        "Nước hồ trong xanh quanh năm?",
        "Khách đến thường ngắm hoàng hôn!",
        "Cảnh rất đẹp.",
    ]


def test_split_sentences_keeps_numbers_and_abbreviations_together() -> None:
    text = "Giá vé 1.000 đồng cho người lớn. Đại Nội ở TP. Huế, mở cửa từ 7h. Đền St. Anne đóng cửa."
    assert split_sentences(text) == [
        "Giá vé 1.000 đồng cho người lớn.",
        "Đại Nội ở TP. Huế, mở cửa từ 7h.",
        "Đền St. Anne đóng cửa.",
    ]


def test_split_sentences_does_not_split_before_lower_case() -> None:
    assert split_sentences("Sông Hương chảy qua Huế. tên cũ là sông Hương giang.") == [
        "Sông Hương chảy qua Huế. tên cũ là sông Hương giang."
    ]


def test_split_sentences_handles_closing_quotes_and_empty_text() -> None:
    assert split_sentences('Ông nói "Đẹp quá." Rồi đi.') == ['Ông nói "Đẹp quá."', 'Rồi đi.']
    assert split_sentences("   ") == []


def test_trim_text_keeps_short_lead_as_is() -> None:
    assert trim_text(LEAD) == LEAD


def test_trim_text_cuts_at_a_sentence_end_within_the_limit() -> None:
    sentence = "Một câu giới thiệu khá dài về di tích này."
    lead = " ".join([sentence] * 60)
    trimmed = trim_text(lead)
    assert len(trimmed) <= TEXT_LIMIT
    assert trimmed.endswith(".")
    assert ELLIPSIS not in trimmed
    assert lead.startswith(trimmed)
    assert len(trimmed) + len(sentence) + 1 > TEXT_LIMIT  # the next sentence would not have fitted


def test_trim_text_word_cut_with_ellipsis_when_first_sentence_is_too_long() -> None:
    lead = "Từ " * 500 + "kết thúc."
    trimmed = trim_text(lead)
    assert len(trimmed) <= TEXT_LIMIT
    assert trimmed.endswith(ELLIPSIS)
    assert not trimmed[:-1].endswith(" ")
    assert lead.startswith(trimmed[:-1])


def test_intro_is_the_first_sentence(corpus_path) -> None:
    assert intro_for("huetripo:1") == "Hồ Thủy Tiên là một hồ nhân tạo ở Huế."


def test_intro_is_cut_at_a_word_with_ellipsis_when_too_long(monkeypatch, tmp_path) -> None:
    lead = "Đây là một câu rất dài " + "và có nhiều từ " * 30 + "kết thúc."
    monkeypatch.setattr(guide, "GUIDE_PATH", write_corpus(tmp_path / "c.json", {"huetripo:2": entry(lead)}))
    intro = intro_for("huetripo:2")
    assert intro is not None
    assert len(intro) <= INTRO_LIMIT
    assert intro.endswith(ELLIPSIS)
    assert lead.startswith(intro[:-1])
    assert not intro[:-1].endswith(" ")


def test_guide_sentences_returns_the_first_n(corpus_path) -> None:
    assert guide_sentences("huetripo:1", 2) == [
        "Hồ Thủy Tiên là một hồ nhân tạo ở Huế.",
        "Hồ nằm gần đồi Vọng Cảnh và được xây năm 1820.",
    ]
    assert len(guide_sentences("huetripo:1")) == 4


def test_guide_for_returns_fields_and_none_for_unknown_ids(corpus_path) -> None:
    found = guide_for("huetripo:1")
    assert found is not None
    assert found.title == "Hồ Thủy Tiên"
    assert found.license == "CC BY-SA 4.0"
    assert found.retrieved_at == "2026-11-24"
    assert found.url.startswith("https://vi.wikipedia.org/wiki/")
    assert found.text == LEAD
    assert guide_for("huetripo:999") is None
    assert intro_for("huetripo:999") is None
    assert guide_sentences("huetripo:999") == []


def test_guide_for_limits_the_text_to_1200_characters(monkeypatch, tmp_path) -> None:
    lead = " ".join(["Đây là một câu khá dài để kiểm tra giới hạn của văn bản hướng dẫn."] * 40)
    monkeypatch.setattr(guide, "GUIDE_PATH", write_corpus(tmp_path / "c.json", {"huetripo:3": entry(lead)}))
    found = guide_for("huetripo:3")
    assert found is not None
    assert len(found.text) <= TEXT_LIMIT
    assert found.text.endswith(".")


def test_missing_corpus_file_means_no_guides(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(guide, "GUIDE_PATH", tmp_path / "absent.json")
    assert guide_for("huetripo:1") is None


def test_real_corpus_entries_are_well_formed() -> None:
    corpus = guide.load_corpus(guide.GUIDE_PATH)
    assert corpus, "the committed corpus must not be empty"
    for poi_id, record in corpus.items():
        assert poi_id.startswith("huetripo:")
        assert record["license"] == "CC BY-SA 4.0"
        assert record["url"].startswith("https://vi.wikipedia.org/wiki/")
        assert record["authors_url"] == f"{record['url']}?action=history"
        assert len(record["retrieved_at"]) == 10
        found = guide_for(poi_id)
        assert found is not None and found.text
        assert len(found.text) <= TEXT_LIMIT
        intro = intro_for(poi_id)
        assert intro is not None and len(intro) <= INTRO_LIMIT


def _committed_guided_poi_ids() -> list[str]:
    return sorted(guide.load_corpus(guide.GUIDE_PATH))


def test_place_endpoint_includes_the_guide_for_a_corpus_poi() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    guided = _committed_guided_poi_ids()
    if not guided:
        pytest.skip("the committed corpus has no entries yet")
    poi_id = guided[0]
    with TestClient(app) as client:
        body = client.get(f"/api/v1/places/{poi_id}").json()
        expected = guide_for(poi_id)
    assert expected is not None
    assert body["guide"] == expected.model_dump()
    assert body["guide"]["license"] == "CC BY-SA 4.0"
    assert len(body["guide"]["retrieved_at"]) == 10


def test_place_endpoint_has_a_null_guide_for_a_poi_outside_the_corpus() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    guided = set(_committed_guided_poi_ids())
    with TestClient(app) as client:
        unguided = next(
            place.id for place in HuePlacesRepository(HUE_DB).list_all() if place.id not in guided
        )
        response = client.get(f"/api/v1/places/{unguided}")
    assert response.status_code == 200
    assert response.json()["guide"] is None


def test_itinerary_sets_intro_on_guided_visits_only(monkeypatch, tmp_path) -> None:
    from datetime import date

    from app.agents.search import SearchAgent
    from app.providers.hotel_mock import MockHotelProvider
    from app.providers.transport_mock import MockTransportProvider
    from app.schemas.request import TripRequest
    from app.services.itinerary_optimizer import ItineraryAgent

    request = TripRequest(
        origin="Đà Nẵng", destination="Huế", start_date=date(2026, 12, 10), end_date=date(2026, 12, 12), people=2
    )
    search = asyncio.run(
        SearchAgent(HuePlacesRepository(HUE_DB), MockTransportProvider(), MockHotelProvider()).search(request)
    )
    visits = [
        event
        for day in ItineraryAgent().plan(request, search).days
        for event in day.events
        if event.kind == "VISIT"
    ]
    assert visits, "the plan needs at least one visit"
    guided = visits[0].poi_id
    corpus = {guided: {"title": "T", "url": "https://vi.wikipedia.org/wiki/T", "license": "CC BY-SA 4.0",
                       "authors_url": "https://vi.wikipedia.org/wiki/T?action=history",
                       "retrieved_at": "2026-11-24", "lead": "Đây là một điểm đến nổi tiếng ở Huế. Có nhiều di tích."}}
    monkeypatch.setattr(guide, "GUIDE_PATH", write_corpus(tmp_path / "c.json", corpus))
    intros = {
        event.poi_id: event.intro
        for day in ItineraryAgent().plan(request, search).days
        for event in day.events
        if event.kind == "VISIT"
    }
    assert intros[guided] == "Đây là một điểm đến nổi tiếng ở Huế."
    assert all(intro is None for poi_id, intro in intros.items() if poi_id != guided)


def test_han_characters_in_parentheses_are_dropped() -> None:
    from app.services.guide import strip_han

    text = "Sông Hương (hay Hương Giang, Hán Nôm: 香江, Chữ Nôm: 瀧香) là con sông."
    assert strip_han(text) == "Sông Hương (hay Hương Giang) là con sông."
    assert strip_han("Ngọ Môn (午門) là cổng chính.") == "Ngọ Môn là cổng chính."
    assert strip_han("Huế (Thừa Thiên) đẹp.") == "Huế (Thừa Thiên) đẹp."


def test_dai_cung_mon_is_not_given_the_ngo_mon_article() -> None:
    from app.services.guide import guide_for

    assert guide_for("huetripo:039509") is None  # Đại Cung Môn is a different gate


def _build_script():
    import importlib.util

    path = BACKEND / "scripts" / "build_guide_corpus.py"
    spec = importlib.util.spec_from_file_location("build_guide_corpus", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FAKE_EXTRACT = """Lead text of the place. It has two sentences.
== Lịch sử ==
Năm 1802 xây dựng. Đây là câu hai.
=== Giai đoạn đầu ===
Phần con được gộp vào mục cha. Thêm một câu.
== Kiến trúc ==
Kiến trúc đẹp.
== Tham khảo ==
Nguồn tham khảo.
== Địa lý ==
Nằm bên sông.
== Du lịch ==
Đi lại dễ dàng.
== Lễ hội ==
Hội lớn hằng năm.
== Hình ảnh ==
Ảnh minh họa.
"""


def test_fold_drops_diacritics_and_case() -> None:
    build = _build_script()
    assert build.fold("Lịch sử") == "lich su"
    assert build.fold("Địa lý") == "dia ly"
    assert build.fold("  Trùng  tu ") == "trung tu"


def test_split_sections_folds_level_three_and_keeps_wanted_headings_in_order() -> None:
    build = _build_script()
    sections = build.split_sections(FAKE_EXTRACT, lead_length=50)
    assert [section["heading"] for section in sections] == ["Lịch sử", "Kiến trúc", "Địa lý"]
    history = sections[0]["text"]
    assert "Năm 1802 xây dựng." in history
    assert "Phần con được gộp vào mục cha." in history  # level-3 text stays with its level-2 parent
    assert "Lead text" not in history


def test_split_sections_skips_unwanted_and_reference_headings() -> None:
    build = _build_script()
    headings = [section["heading"] for section in build.split_sections(FAKE_EXTRACT)]
    assert "Tham khảo" not in headings
    assert "Hình ảnh" not in headings
    assert "Nguồn tham khảo." not in " ".join(section["text"] for section in build.split_sections(FAKE_EXTRACT))


def test_split_sections_keeps_at_most_three_sections() -> None:
    build = _build_script()
    sections = build.split_sections(FAKE_EXTRACT)
    assert len(sections) == build.SECTIONS_MAX == 3
    assert [section["heading"] for section in sections] == ["Lịch sử", "Kiến trúc", "Địa lý"]


def test_split_sections_trims_at_a_sentence_end_within_the_limit() -> None:
    build = _build_script()
    sentence = "Một câu lịch sử khá dài về di tích này được ghi chép lại."
    extract = "Lead.\n== Lịch sử ==\n" + " ".join([sentence] * 40) + "\n"
    (section,) = build.split_sections(extract)
    assert len(section["text"]) <= build.SECTION_LIMIT
    assert section["text"].endswith(".")
    assert len(section["text"]) + len(sentence) + 1 > build.SECTION_LIMIT


def test_split_sections_drops_a_section_whose_first_sentence_is_too_long() -> None:
    build = _build_script()
    extract = "Lead.\n== Lịch sử ==\n" + "từ " * 400 + "kết thúc.\n"
    assert build.split_sections(extract) == []


def test_split_sections_respects_the_total_limit_with_the_lead() -> None:
    build = _build_script()
    body = " ".join(["Một câu về lịch sử của di tích này."] * 20)
    extract = f"Lead.\n== Lịch sử ==\n{body}\n== Kiến trúc ==\n{body}\n"
    assert build.split_sections(extract, lead_length=build.TOTAL_LIMIT - 100) == []
    assert len(build.split_sections(extract, lead_length=0)) == 2


def test_guide_for_returns_sections_cleaned_and_trimmed(monkeypatch, tmp_path) -> None:
    corpus_entry = entry(LEAD)
    corpus_entry["sections"] = [
        {"heading": "Lịch sử", "text": "Xây năm 1820 (Hán Nôm: 香江). Hồ rất đẹp."},
        {"heading": "Kiến trúc", "text": "(Chữ Hán: 皇城)"},
        {"heading": "Vị trí", "text": "Bên bờ sông. " * 100},
    ]
    monkeypatch.setattr(guide, "GUIDE_PATH", write_corpus(tmp_path / "c.json", {"huetripo:4": corpus_entry}))
    found = guide_for("huetripo:4")
    assert found is not None
    assert [section.heading for section in found.sections] == ["Lịch sử", "Vị trí"]
    assert found.sections[0].text == "Xây năm 1820. Hồ rất đẹp."
    assert len(found.sections[1].text) <= guide.SECTION_LIMIT
    assert found.sections[1].text.endswith(".")


def test_guide_for_has_no_sections_for_an_entry_without_them(corpus_path) -> None:
    found = guide_for("huetripo:1")
    assert found is not None and found.sections == []


def test_real_corpus_sections_are_well_formed() -> None:
    corpus = guide.load_corpus(guide.GUIDE_PATH)
    for poi_id in corpus:
        found = guide_for(poi_id)
        assert found is not None
        assert len(found.sections) <= 3
        for section in found.sections:
            assert section.heading and section.text
            assert len(section.text) <= guide.SECTION_LIMIT
            assert guide.strip_han(section.text) == section.text


def test_hoang_thanh_hue_has_its_history_section() -> None:
    found = guide_for("huetripo:531787")
    assert found is not None
    assert [section.heading for section in found.sections] == ["Lịch sử"]
    assert found.sections[0].text.strip()


def test_place_endpoint_includes_sections_for_hoang_thanh_hue() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        body = client.get("/api/v1/places/huetripo:531787").json()
    assert body["guide"]["sections"][0]["heading"] == "Lịch sử"
    assert body["guide"]["sections"][0]["text"]


def test_glued_wikipedia_footnote_numbers_are_dropped() -> None:
    from app.services.guide import strip_han

    assert strip_han("của người Chăm1. Truyền thuyết") == "của người Chăm. Truyền thuyết"
    assert strip_han("năm 1601, đời chúa Tiên") == "năm 1601, đời chúa Tiên"  # real numbers stay
    assert strip_han("Thiên Mụ Sơn 2.") == "Thiên Mụ Sơn 2."  # a separate number is kept
