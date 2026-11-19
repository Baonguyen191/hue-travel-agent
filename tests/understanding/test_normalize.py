"""Test chuẩn hóa bằng code: bỏ dấu, đọc thời lượng, map sở thích."""

import pytest

from travel_agent.planning.candidates import INTEREST_CATEGORIES
from travel_agent.understanding.models import DurationSpec
from travel_agent.understanding.normalize import (
    INTEREST_KEYWORDS,
    has_diacritics,
    map_interests,
    parse_duration,
    strip_diacritics,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Đại Nội", "dai noi"),
        ("Huế", "hue"),
        ("ĐI HUẾ", "di hue"),
        ("  Cuối   tuần  ", "cuoi tuan"),
        ("Ngày mai", "ngay mai"),
        ("đ Đ", "d d"),
        ("café", "cafe"),
        ("Hương Giang", "huong giang"),
        ("ÔNG BÀ ƯƠNG", "ong ba uong"),
        ("", ""),
        ("abc", "abc"),
    ],
)
def test_strip_diacritics(text: str, expected: str) -> None:
    assert strip_diacritics(text) == expected


def test_strip_diacritics_accepts_decomposed_input() -> None:
    # "a" + dấu huyền tổ hợp (NFD) phải ra "a", giống dạng dựng sẵn.
    assert strip_diacritics("à") == "a"
    assert strip_diacritics("à") == strip_diacritics("à")


def test_strip_diacritics_never_raises_on_odd_characters() -> None:
    assert strip_diacritics("💥 \x00 tab\there") == "💥 \x00 tab here"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2 ngày 1 đêm", DurationSpec(num_days=2, half_day=False)),
        ("2N1Đ", DurationSpec(num_days=2, half_day=False)),
        ("2n1đ", DurationSpec(num_days=2, half_day=False)),
        ("2n1d", DurationSpec(num_days=2, half_day=False)),
        ("2 ngay 1 dem", DurationSpec(num_days=2, half_day=False)),
        ("3 hôm", DurationSpec(num_days=3, half_day=False)),
        ("3 hom", DurationSpec(num_days=3, half_day=False)),
        ("3 ngày 2 đêm", DurationSpec(num_days=3, half_day=False)),
        ("ba ngày ba đêm", DurationSpec(num_days=3, half_day=False)),
        ("một ngày", DurationSpec(num_days=1, half_day=False)),
        ("mot ngay", DurationSpec(num_days=1, half_day=False)),
        ("hai ngày một đêm", DurationSpec(num_days=2, half_day=False)),
        ("bảy ngày", DurationSpec(num_days=7, half_day=False)),
        ("năm ngày", DurationSpec(num_days=5, half_day=False)),
        ("bốn hôm", DurationSpec(num_days=4, half_day=False)),
        ("12 ngày", DurationSpec(num_days=12, half_day=False)),
        (
            "đi Huế 2 ngày cuối tuần này với bố mẹ",
            DurationSpec(num_days=2, half_day=False),
        ),
        ("nửa ngày", DurationSpec(num_days=1, half_day=True)),
        ("nua ngay", DurationSpec(num_days=1, half_day=True)),
        ("1 buổi", DurationSpec(num_days=1, half_day=True)),
        ("một buổi", DurationSpec(num_days=1, half_day=True)),
        ("mot buoi", DurationSpec(num_days=1, half_day=True)),
    ],
)
def test_parse_duration_reads_common_forms(text: str, expected: DurationSpec) -> None:
    assert parse_duration(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "đi Huế",
        "cuối tuần này",
        "0 ngày",
        "2 người",
        "2 năm",
        "ngày mai",
        "sáng mai",
        "2 tuần",
        "💥",
    ],
)
def test_parse_duration_returns_none_when_absent(text: str) -> None:
    assert parse_duration(text) is None


def test_parse_duration_skips_zero_and_uses_next_valid_match() -> None:
    assert parse_duration("0 ngày rồi 2 ngày") == DurationSpec(num_days=2, half_day=False)


def test_parse_duration_does_not_read_number_word_inside_other_word() -> None:
    # "ba" nằm trong "bánh" không được tính là số ngày khi không đứng riêng.
    assert parse_duration("bánh ngày") is None


@pytest.mark.parametrize(
    ("phrases", "interests", "unmatched"),
    [
        (
            ["chùa", "lăng tẩm", "ăn uống", "cà phê", "chụp ảnh"],
            ["coffee", "food", "history", "photography", "spiritual"],
            [],
        ),
        (
            ["chua", "lang tam", "an uong", "ca phe", "chup anh"],
            ["coffee", "food", "history", "photography", "spiritual"],
            [],
        ),
        (["yên tĩnh", "đi cùng bố mẹ già"], [], ["yên tĩnh", "đi cùng bố mẹ già"]),
        (["an toàn"], [], ["an toàn"]),
        (["đèn lồng"], [], ["đèn lồng"]),
        (["DAI NOI"], ["history"], []),
        (["cafe", "coffee"], ["coffee"], []),
        (["check-in", "sống ảo"], ["photography"], []),
        (["sông Hương"], ["nature"], []),
        (["sống ảo"], ["photography"], []),
        (["mua sắm", "đi chợ", "chợ đêm", "mua quà"], ["shopping"], []),
        (["tham quan", "ngắm cảnh"], ["sightseeing"], []),
        (["cổ kính", "di tích", "lịch sử", "hoàng thành"], ["history"], []),
        (["bảo tàng", "văn hóa"], ["culture"], []),
        (["ẩm thực", "đặc sản", "món"], ["food"], []),
        (["thiên nhiên", "núi", "biển", "đồi", "vườn"], ["nature"], []),
        (["đền", "miếu", "tâm linh"], ["spiritual"], []),
        (["ăn uống, cà phê"], ["coffee", "food"], []),
    ],
)
def test_map_interests_maps_phrases_to_nine_interests(
    phrases: list[str], interests: list[str], unmatched: list[str]
) -> None:
    assert map_interests(phrases) == (interests, unmatched)


def test_map_interests_empty_input() -> None:
    assert map_interests([]) == ([], [])


def test_map_interests_drops_blank_phrases_and_dedups_interests() -> None:
    assert map_interests(["  ", "chùa", "đền", "chùa"]) == (["spiritual"], [])


def test_map_interests_keeps_unmatched_phrase_text_as_given() -> None:
    _, unmatched = map_interests(["Yên Tĩnh", "chùa"])
    assert unmatched == ["Yên Tĩnh"]


def test_keyword_table_covers_exactly_the_nine_interests() -> None:
    assert set(INTEREST_KEYWORDS) == set(INTEREST_CATEGORIES)


def test_every_table_keyword_maps_to_its_own_interest() -> None:
    for interest, keywords in INTEREST_KEYWORDS.items():
        for keyword in keywords:
            found, _ = map_interests([keyword])
            assert interest in found, keyword


@pytest.mark.parametrize(
    ("phrase", "interest"),
    [
        ("đồ ăn địa phương", "food"),
        ("hải sản tươi", "food"),
        ("món ăn truyền thống", "food"),
        ("ẩm thực đường phố", "food"),
        ("ăn vặt", "food"),
        ("ăn", "food"),
        ("biển xanh", "nature"),
    ],
)
def test_food_and_sea_phrases_map_to_interests(phrase: str, interest: str) -> None:
    assert map_interests([phrase]) == ([interest], [])


@pytest.mark.parametrize(
    "phrase",
    [
        "tránh chỗ đông",  # "chợ" không có trong "chỗ"
        "chỉ đi chỗ có mái che",
        "làng nghề truyền thống",  # "làng" không phải "lăng"
    ],
)
def test_accented_phrase_does_not_hit_look_alike_keywords(phrase: str) -> None:
    assert map_interests([phrase]) == ([], [phrase])


def test_has_diacritics_detects_marks_and_d_stroke() -> None:
    assert has_diacritics("chùa")
    assert has_diacritics("đền")
    assert has_diacritics("Đại Nội")
    assert not has_diacritics("chua")
    assert not has_diacritics("dai noi")
