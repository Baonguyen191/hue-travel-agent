"""Test các hàm thuần của gợi ý dọn dữ liệu: chuẩn hóa tên, quy tắc trùng, quy tắc từ khóa."""

from __future__ import annotations

import datetime as dt

import pytest

from travel_agent.data.cleanup_suggestions import (
    CATEGORY_RULES,
    KIND_CATEGORY,
    KIND_DUPLICATE,
    KIND_MISSING,
    build_suggestions,
    categories_compatible,
    category_suspect,
    choose_kept,
    count_by_kind,
    duplicate_pair,
    find_duplicate_pairs,
    missing_key_data,
    name_relation,
    normalize_name,
    review_count,
    strip_diacritics,
    top_popular,
)
from travel_agent.domain.models import Category, Coordinates, Place

COLLECTED = dt.datetime(2026, 11, 3, 8, 0, tzinfo=dt.UTC)
CENTER_LAT = 16.47
CENTER_LON = 107.58
# Mỗi 0,001 độ vĩ độ xấp xỉ 111 m.
HOURS = "07:30-17:30"
DURATION = {"Thời gian trải nghiệm TB (phút)": "60"}


def make_place(
    pid: str,
    name: str,
    category: Category,
    *,
    lat: float = CENTER_LAT,
    lon: float = CENTER_LON,
    hours: str | None = HOURS,
    attributes: dict[str, str] | None = None,
) -> Place:
    return Place(
        id=pid,
        name=name,
        category=category,
        coords=Coordinates(lat=lat, lon=lon),
        opening_hours_raw=hours,
        source="huetripo.hue.gov.vn",
        source_place_id=pid.removeprefix("huetripo:"),
        license="test",
        collected_at=COLLECTED,
        attributes=dict(DURATION) if attributes is None else attributes,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Đông Ba", "Dong Ba"),
        ("Phá Tam Giang", "Pha Tam Giang"),
        ("Huế", "Hue"),
    ],
)
def test_strip_diacritics(raw: str, expected: str) -> None:
    assert strip_diacritics(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Chợ Đông Ba Huế", "cho dong ba"),
        ("Chợ Đông Ba", "cho dong ba"),
        ("Quán Hương - Bèo Nậm Lọc", "quan huong beo nam loc"),
        ("Cafe   Memoire  Hue!", "cafe memoire"),
        ("Huế", ""),
        ("", ""),
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_name_relation_equal_and_contained() -> None:
    assert name_relation("cho dong ba", "cho dong ba") == "tên giống nhau sau chuẩn hóa"
    assert name_relation("dau hu", "dau hu ben canh chua thien mu") == "tên này nằm trong tên kia"


def test_name_relation_requires_whole_words_and_minimum_length() -> None:
    # "cau" (3 ký tự) quá ngắn để coi là nằm trong tên khác.
    assert name_relation("cau", "cau ngoi thanh toan") is None
    # Không khớp một phần từ: "ba" không nằm trong "bana".
    assert name_relation("cho ba", "cho bana hills") is None
    assert name_relation("", "cho dong ba") is None


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (Category.ATTRACTION, Category.ATTRACTION, True),
        (Category.ATTRACTION, Category.PARK, True),
        (Category.RESTAURANT, Category.CAFE, True),
        (Category.MARKET, Category.ATTRACTION, False),
        (Category.RESTAURANT, Category.MARKET, False),
    ],
)
def test_categories_compatible(a: Category, b: Category, expected: bool) -> None:
    assert categories_compatible(a, b) is expected


def test_duplicate_within_300m_same_name() -> None:
    a = make_place("huetripo:1", "Chợ Đông Ba", Category.MARKET)
    b = make_place("huetripo:2", "Chợ Đông Ba Huế", Category.MARKET, lat=CENTER_LAT + 0.002)
    pair = duplicate_pair(a, b, normalize_name(a.name), normalize_name(b.name))
    assert pair is not None
    assert 200 < pair.distance_m < 240
    assert pair.reason == "tên giống nhau sau chuẩn hóa"


def test_duplicate_rejected_at_or_beyond_300m() -> None:
    a = make_place("huetripo:1", "Chợ Đông Ba", Category.MARKET)
    far = make_place("huetripo:2", "Chợ Đông Ba", Category.MARKET, lat=CENTER_LAT + 0.004)
    assert duplicate_pair(a, far, "cho dong ba", "cho dong ba") is None


def test_duplicate_rejected_when_categories_incompatible() -> None:
    a = make_place("huetripo:1", "Chợ Đông Ba", Category.MARKET)
    b = make_place("huetripo:2", "Chợ Đông Ba", Category.ATTRACTION, lat=CENTER_LAT + 0.001)
    assert duplicate_pair(a, b, "cho dong ba", "cho dong ba") is None


def test_find_duplicate_pairs_only_nearby_candidates() -> None:
    places = [
        make_place("huetripo:1", "Thành Cafe", Category.CAFE),
        make_place("huetripo:2", "Thành Cafe Huế", Category.CAFE, lat=CENTER_LAT + 0.001),
        make_place("huetripo:3", "Thành Cafe", Category.CAFE, lat=CENTER_LAT + 0.05),
    ]
    pairs = find_duplicate_pairs(places)
    assert len(pairs) == 1
    assert {pairs[0].kept.id, pairs[0].dropped.id} == {"huetripo:1", "huetripo:2"}


def test_choose_kept_prefers_more_attributes_then_reviews_then_id() -> None:
    rich = make_place(
        "huetripo:9",
        "A",
        Category.CAFE,
        attributes={"Địa chỉ": "x", "Đánh giá": "4.0/5 (5 lượt)"},
    )
    poor = make_place("huetripo:1", "A", Category.CAFE, attributes={"Địa chỉ": "y"})
    kept, dropped = choose_kept(rich, poor)
    assert kept.id == "huetripo:9" and dropped.id == "huetripo:1"

    same_a = make_place("huetripo:5", "A", Category.CAFE, attributes={"Đánh giá": "4/5 (10 lượt)"})
    same_b = make_place("huetripo:6", "A", Category.CAFE, attributes={"Đánh giá": "4/5 (99 lượt)"})
    kept, _ = choose_kept(same_a, same_b)
    assert kept.id == "huetripo:6"

    tie_a = make_place("huetripo:7", "A", Category.CAFE, attributes={})
    tie_b = make_place("huetripo:3", "A", Category.CAFE, attributes={})
    kept, _ = choose_kept(tie_a, tie_b)
    assert kept.id == "huetripo:3"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("4.6/5 (60 lượt, Google)", 60),
        ("4.2/5 (3.311 lượt, Google)", 3311),
        ("4.8/5", 0),
        ("", 0),
    ],
)
def test_review_count(text: str, expected: int) -> None:
    place = make_place("huetripo:1", "A", Category.CAFE, attributes={"Đánh giá": text})
    assert review_count(place) == expected


def _suspect_rule(name: str, category: Category) -> str | None:
    suspect = category_suspect(make_place("huetripo:1", name, category))
    return None if suspect is None else suspect.rule.label


def test_bridge_in_park_suggests_viewpoint() -> None:
    suspect = category_suspect(make_place("huetripo:1", "Cầu Trường Tiền", Category.PARK))
    assert suspect is not None
    assert suspect.rule.suggested is Category.VIEWPOINT
    assert suspect.keyword == "cau"


def test_bridge_already_viewpoint_is_not_flagged() -> None:
    assert category_suspect(make_place("huetripo:1", "Cầu Trường Tiền", Category.VIEWPOINT)) is None


def test_shop_in_market_is_flagged_without_suggestion() -> None:
    suspect = category_suspect(make_place("huetripo:1", "Vincom Plaza Huế", Category.MARKET))
    assert suspect is not None
    assert suspect.rule.suggested is None
    assert suspect.keyword == "vincom"


def test_nature_keywords_in_attraction_suggest_park_or_viewpoint() -> None:
    cases = {
        "Biển Thuận An": Category.PARK,
        "Phá Tam Giang": Category.PARK,
        "Đầm Chuồn": Category.PARK,
        "Thác Mơ": Category.PARK,
        "Hồ Truồi": Category.PARK,
        "Đồi Vọng Cảnh": Category.VIEWPOINT,
        "Núi Bạch Mã": Category.VIEWPOINT,
    }
    for name, expected in cases.items():
        suspect = category_suspect(make_place("huetripo:1", name, Category.ATTRACTION))
        assert suspect is not None, name
        assert suspect.rule.suggested is expected, name


def test_thac_nhi_ho_is_waterfall_not_lake() -> None:
    suspect = category_suspect(make_place("huetripo:1", "Thác Nhị Hồ", Category.ATTRACTION))
    assert suspect is not None
    assert suspect.keyword == "thac"


def test_exact_keywords_do_not_match_lookalikes() -> None:
    # "đôi" không phải "đồi"; "làng" không phải "lăng"; "Hổ" không phải "hồ".
    assert _suspect_rule("Đôi Bờ Sông", Category.ATTRACTION) is None
    assert _suspect_rule("Làng Chài Lăng Cô", Category.RESTAURANT) is None
    assert _suspect_rule("Hổ Bảo", Category.ATTRACTION) is None


def test_lang_co_is_a_place_not_a_tomb() -> None:
    assert _suspect_rule("Biển Lăng Cô", Category.RESTAURANT) is None
    assert _suspect_rule("Nhà hàng Lăng Cô Beach Resort", Category.MUSEUM) is None


def test_tomb_outside_historic_suggests_historic() -> None:
    suspect = category_suspect(make_place("huetripo:1", "Lăng vua Minh Mạng", Category.MUSEUM))
    assert suspect is not None
    assert suspect.rule.suggested is Category.HISTORIC
    assert (
        category_suspect(make_place("huetripo:2", "Lăng vua Minh Mạng", Category.HISTORIC)) is None
    )


def test_church_must_be_religious_but_tomb_complex_is_not() -> None:
    church = category_suspect(make_place("huetripo:1", "Nhà thờ Phú Cam", Category.ATTRACTION))
    assert church is not None
    assert church.rule.suggested is Category.RELIGIOUS
    assert _suspect_rule("Lăng mộ và Nhà thờ Nguyễn Tri Phương", Category.HISTORIC) is None
    assert _suspect_rule("Mộ và nhà thờ ông Tổ nghề đúc Đồng", Category.HISTORIC) is None


def test_name_says_cafe_in_restaurant_suggests_cafe() -> None:
    suspect = category_suspect(make_place("huetripo:1", "Cafe Mai Uyển", Category.RESTAURANT))
    assert suspect is not None
    assert suspect.rule.suggested is Category.CAFE
    # Vừa nhà hàng vừa cafe thì không đổi.
    assert _suspect_rule("Vị Huế Restaurant & Café", Category.RESTAURANT) is None


def test_no_keyword_no_suspect() -> None:
    assert _suspect_rule("Bánh Xèo Làng Chuồn", Category.RESTAURANT) is None
    assert category_suspect(make_place("huetripo:1", "Chợ Đông Ba", Category.MARKET)) is None


def test_every_rule_has_label_and_known_keywords() -> None:
    for rule in CATEGORY_RULES:
        assert rule.label
        assert rule.keywords or rule.exact
        for keyword in rule.keywords:
            assert keyword == normalize_name(keyword), keyword


def test_missing_key_data_flags_missing_hours_and_duration() -> None:
    complete = make_place("huetripo:1", "A", Category.MUSEUM)
    assert missing_key_data(complete) == []

    no_hours = make_place("huetripo:2", "A", Category.MUSEUM, hours=None)
    assert missing_key_data(no_hours) == ["thiếu giờ mở cửa"]

    unparsable = make_place("huetripo:3", "A", Category.MUSEUM, hours="mở 16:00")
    assert missing_key_data(unparsable) == ["giờ mở cửa không đọc được"]

    blank_duration = make_place(
        "huetripo:4", "A", Category.MUSEUM, attributes={"Thời gian trải nghiệm TB (phút)": " "}
    )
    assert missing_key_data(blank_duration) == ["thiếu thời lượng tham quan"]


def test_top_popular_orders_by_reviews_then_id() -> None:
    many = make_place(
        "huetripo:2", "A", Category.MUSEUM, attributes={"Đánh giá": "4.2/5 (3311 lượt)"}
    )
    few = make_place("huetripo:1", "B", Category.MUSEUM, attributes={"Đánh giá": "4.9/5 (17 lượt)"})
    none = make_place("huetripo:3", "C", Category.MUSEUM, attributes={})
    assert [p.id for p in top_popular([few, none, many], 2)] == ["huetripo:2", "huetripo:1"]


def test_build_suggestions_rows_and_counts() -> None:
    kept = make_place(
        "huetripo:10",
        "Chợ Đông Ba",
        Category.MARKET,
        attributes={"Đánh giá": "4.2/5 (3311 lượt)", "Địa chỉ": "x", **DURATION},
    )
    dropped = make_place("huetripo:11", "Chợ Đông Ba Huế", Category.MARKET, lat=CENTER_LAT + 0.001)
    bridge = make_place("huetripo:12", "Cầu Trường Tiền", Category.PARK, hours=None)
    statuses = {"huetripo:10": "approved", "huetripo:11": "pending"}

    rows = build_suggestions([kept, dropped, bridge], statuses, top_n=10)
    counts = count_by_kind(rows)
    assert counts == {KIND_DUPLICATE: 1, KIND_CATEGORY: 1, KIND_MISSING: 1}

    duplicate = next(row for row in rows if row.kind == KIND_DUPLICATE)
    assert duplicate.place_id == "huetripo:11"
    assert duplicate.other_place_id == "huetripo:10"
    assert duplicate.suggested_action == "gộp: giữ huetripo:10"
    assert duplicate.status == "pending"

    category = next(row for row in rows if row.kind == KIND_CATEGORY)
    assert category.place_id == "huetripo:12"
    assert category.suggested_category == "viewpoint"
    assert category.matched_keyword == "cau"

    missing = next(row for row in rows if row.kind == KIND_MISSING)
    assert missing.place_id == "huetripo:12"
    assert "thiếu giờ mở cửa" in missing.reason


def test_count_by_kind_reports_zero_for_empty_kinds() -> None:
    assert count_by_kind([]) == {KIND_DUPLICATE: 0, KIND_CATEGORY: 0, KIND_MISSING: 0}
