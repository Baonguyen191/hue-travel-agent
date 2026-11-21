"""PHASE 4 preference and keyword mapping tests."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.schemas.place import Place  # noqa: E402
from app.services.preferences import (  # noqa: E402
    extract_keyword_hints,
    is_hue_specialty,
    map_preferences,
)


def _place(name: str, category: str = "restaurant", summary: str | None = None) -> Place:
    return Place(
        id="test-place",
        name=name,
        category=category,  # type: ignore[arg-type]
        lat=16.46,
        lon=107.59,
        summary=summary,
        opening_hours_confidence="UNKNOWN",
        price_status="UNKNOWN",
        source="test",
        source_place_id="test-place",
        collected_at=datetime(2026, 11, 21),
        raw_attributes={},
    )


def test_historic_and_specialty_preferences_map_to_categories() -> None:
    categories, unmapped = map_preferences(["di tích", "đặc sản"])

    assert "historic" in categories
    assert "restaurant" in categories
    assert unmapped == []


def test_cafe_preference_maps_with_and_without_diacritics() -> None:
    categories, _ = map_preferences(["cà phê"])
    assert categories == ["cafe"]

    categories, _ = map_preferences(["ca phe sữa đá"])
    assert categories == ["cafe"]


def test_unmapped_preference_passes_through_unchanged() -> None:
    categories, unmapped = map_preferences(["bún bò"])

    assert categories == []
    assert unmapped == ["bún bò"]


def test_preference_match_is_whole_word_not_substring() -> None:
    categories, unmapped = map_preferences(["đi chơi"])

    assert "market" not in categories
    assert unmapped == ["đi chơi"]


def test_keyword_hint_quan_ca_phe_is_cafe_with_no_residual() -> None:
    categories, residual = extract_keyword_hints("quan ca phe")

    assert categories == ["cafe"]
    assert residual is None


def test_keyword_without_hint_keeps_normalized_residual() -> None:
    categories, residual = extract_keyword_hints("bún bò")

    assert categories == []
    assert residual == "bun bo"


def test_specialty_restaurant_is_detected_by_name_or_summary() -> None:
    assert is_hue_specialty(_place("Bún Bò Huế Đông Ba"))
    assert is_hue_specialty(_place("Quán Ăn Sáng", summary="Nổi tiếng với bánh khoai"))


def test_non_specialty_or_non_restaurant_is_not_specialty() -> None:
    assert not is_hue_specialty(_place("Pizza Hut"))
    assert not is_hue_specialty(_place("Bún Bò Huế Cafe", category="cafe"))
