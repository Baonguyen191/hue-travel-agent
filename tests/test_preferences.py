"""PHASE 4 preference and keyword mapping tests."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.repositories.hue_places import HuePlacesRepository  # noqa: E402
from app.schemas.place import Place  # noqa: E402
from app.services.preferences import (  # noqa: E402
    extract_keyword_hints,
    is_food_market,
    is_hue_specialty,
    is_nature,
    is_view_cafe,
    map_preferences,
    map_themes,
    source_type,
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


def _typed(name: str, category: str, source: str | None) -> Place:
    """A place whose raw source type is `source` (None means the field is missing)."""
    raw = {} if source is None else {"Loại hình (theo nguồn)": source}
    return _place(name, category).model_copy(update={"raw_attributes": raw})


def test_source_type_is_the_part_after_the_last_slash() -> None:
    nature = _typed("Đồi Thiên An", "attraction", "Điểm du lịch, tài nguyên / Thiên nhiên")

    assert source_type(nature) == "Thiên nhiên"
    assert source_type(_typed("Không rõ", "market", None)) is None


def test_nature_and_scenery_preferences_map_to_the_nature_theme() -> None:
    assert map_themes(["thiên nhiên"]) == ["nature"]
    assert map_themes(["ngắm cảnh"]) == ["nature"]
    assert map_themes(["biển"]) == ["nature"]
    assert map_themes(["ẩm thực"]) == []


def test_food_preference_covers_restaurants_cafes_and_markets() -> None:
    categories, unmapped = map_preferences(["ẩm thực"])

    assert categories == ["restaurant", "cafe", "market"]
    assert unmapped == []


def test_thien_nhien_no_longer_maps_to_park() -> None:
    categories, _ = map_preferences(["thiên nhiên"])

    assert categories == ["attraction"]
    assert "park" not in categories


def test_food_market_rejects_supermarkets_and_malls_in_the_real_data() -> None:
    places = HuePlacesRepository(BACKEND / "data" / "hue.sqlite")

    assert not is_food_market(places.get_by_id("huetripo:778466"))  # Siêu thị GO! Huế
    assert not is_food_market(places.get_by_id("huetripo:489415"))  # Vincom Plaza Huế
    assert is_food_market(_typed("Chợ Xép", "market", "Chợ"))
    assert is_food_market(_typed("Bánh lọc Huế bà Vân", "market", "Cửa hàng đặc sản và quà tặng"))
    assert not is_food_market(_typed("Trung tâm thương mại X", "market", "Trung tâm thương mại"))


def test_nature_and_view_cafe_predicates() -> None:
    assert is_nature(_typed("Hồ Thủy Tiên", "attraction", "Điểm du lịch, tài nguyên / Thiên nhiên"))
    assert not is_nature(_typed("Cầu Trường Tiền", "park", "Không gian công cộng"))
    assert is_view_cafe(_typed("Riverside Coffee", "cafe", "trà"))
    assert is_view_cafe(_typed("Nhà Bên Hồ Cafe", "cafe", "trà"))
    assert not is_view_cafe(_typed("Túc Tắc Tea", "cafe", "trà"))
