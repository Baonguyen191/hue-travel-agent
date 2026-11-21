"""Tests for Vietnamese normalisation: diacritics, durations and budget phrases."""

from __future__ import annotations

import pytest

import sys as _sys
from pathlib import Path as _Path
_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))

from app.understanding.models import DurationSpec
from app.understanding.normalize import parse_budget_vnd, parse_duration, strip_diacritics


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
        ("ÔNG BÀ ƯƠNG", "ong ba uong"),
        ("", ""),
    ],
)
def test_strip_diacritics(text: str, expected: str) -> None:
    assert strip_diacritics(text) == expected


def test_strip_diacritics_accepts_decomposed_input() -> None:
    assert strip_diacritics("à") == "a"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2 ngày 1 đêm", DurationSpec(num_days=2)),
        ("2N1Đ", DurationSpec(num_days=2)),
        ("2n1đ", DurationSpec(num_days=2)),
        ("2n1d", DurationSpec(num_days=2)),
        ("3 hôm", DurationSpec(num_days=3)),
        ("3 ngày 2 đêm", DurationSpec(num_days=3)),
        ("ba ngày ba đêm", DurationSpec(num_days=3)),
        ("một ngày", DurationSpec(num_days=1)),
        ("hai ngày một đêm", DurationSpec(num_days=2)),
        ("bảy ngày", DurationSpec(num_days=7)),
        ("bốn hôm", DurationSpec(num_days=4)),
        ("12 ngày", DurationSpec(num_days=12)),
        ("đi Huế 2 ngày cuối tuần này", DurationSpec(num_days=2)),
        ("nửa ngày", DurationSpec(num_days=1, half_day=True)),
        ("1 buổi", DurationSpec(num_days=1, half_day=True)),
        ("một buổi", DurationSpec(num_days=1, half_day=True)),
    ],
)
def test_parse_duration_reads_common_forms(text: str, expected: DurationSpec) -> None:
    assert parse_duration(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", "đi Huế", "cuối tuần này", "0 ngày", "2 người", "2 năm", "ngày mai", "2 tuần"],
)
def test_parse_duration_returns_none_when_absent(text: str) -> None:
    assert parse_duration(text) is None


def test_parse_duration_skips_zero_and_uses_next_valid_match() -> None:
    assert parse_duration("0 ngày rồi 2 ngày") == DurationSpec(num_days=2)


def test_parse_duration_does_not_read_number_word_inside_other_word() -> None:
    assert parse_duration("bánh ngày") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("5 triệu", 5_000_000),
        ("5tr", 5_000_000),
        ("5 củ", 5_000_000),
        ("năm củ", 5_000_000),
        ("hai triệu rưỡi", 2_500_000),
        ("500k", 500_000),
        ("500 nghìn", 500_000),
        ("3.000.000 đồng", 3_000_000),
        ("3,5 triệu", 3_500_000),
        ("khoảng 2 triệu", 2_000_000),
    ],
)
def test_parse_budget_reads_vietnamese_units(text: str, expected: int) -> None:
    assert parse_budget_vnd(text) == expected


@pytest.mark.parametrize("text", ["", "ngân sách thấp", "5", "2 người", "miễn phí"])
def test_parse_budget_returns_none_when_unit_or_amount_is_missing(text: str) -> None:
    assert parse_budget_vnd(text) is None
