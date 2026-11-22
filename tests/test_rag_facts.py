"""Fact checker: times, prices, phones and addresses in an answer must match the cited POIs."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))
_TESTS = _Path(__file__).resolve().parent
if str(_TESTS) not in _sys.path:
    _sys.path.insert(0, str(_TESTS))

from app.rag.facts import CITE_RE, check_facts  # noqa: E402
from test_rag_index import make_place  # noqa: E402

PLACE = make_place("huetripo:1")  # 06:00-21:00, 30.000-50.000đ, 0234 3826 123, 20 Bạch Đằng
OTHER = make_place("huetripo:2", opening_hours_raw="07:30-17:30", price_min_vnd=200000, price_max_vnd=200000)


def test_cite_re_finds_ids() -> None:
    assert CITE_RE.findall("A [huetripo:1]. B [huetripo:22].") == ["huetripo:1", "huetripo:22"]


def test_correct_facts_pass() -> None:
    answer = ("Quán mở cửa 06:00-21:00, giá 30.000đ đến 50k [huetripo:1]. "
              "Số điện thoại 0234 3826 123, địa chỉ: 20 Bạch Đằng [huetripo:1].")
    assert check_facts(answer, [PLACE]) == []


def test_wrong_time_price_phone_and_address_are_reported() -> None:
    answer = ("Quán mở cửa lúc 05:30 [huetripo:1]. Giá 90.000đ [huetripo:1]. "
              "Gọi 0905 111 222 [huetripo:1]. Địa chỉ: 99 Lê Lợi [huetripo:1].")
    kinds = sorted(m.kind for m in check_facts(answer, [PLACE]))
    assert kinds == ["address", "phone", "price", "time"]


def test_facts_are_checked_against_the_place_cited_in_the_same_sentence() -> None:
    answer = "Quán A mở 06:00 [huetripo:1]. Điểm B mở 07:30, vé 200.000đ [huetripo:2]."
    assert check_facts(answer, [PLACE, OTHER]) == []
    wrong = "Điểm B mở 06:00 [huetripo:2]."
    assert [m.kind for m in check_facts(wrong, [PLACE, OTHER])] == ["time"]


def test_bracketed_times_are_not_citations_and_are_checked() -> None:
    assert CITE_RE.findall("Mở [06:00-21:00] [huetripo:1].") == ["huetripo:1"]
    mismatches = check_facts("Mở cửa [05:00-06:00] [huetripo:1].", [PLACE])
    assert [(m.kind, m.value) for m in mismatches] == [("time", "05:00")]


def test_durations_and_distances_are_not_facts() -> None:
    assert check_facts("Tham quan khoảng 2 giờ, cách 1.5 km [huetripo:1].", [PLACE]) == []


def test_hours_stated_for_a_place_without_hours_is_a_mismatch() -> None:
    place = make_place("huetripo:9", opening_hours_raw=None)
    assert [m.kind for m in check_facts("Mở cửa 08:00 [huetripo:9].", [place])] == ["time"]


def test_phone_formats_from_the_source_match_local_forms() -> None:
    a = make_place("huetripo:5", raw_attributes={"Điện thoại": "(+84)  91 648 22 71"})
    b = make_place("huetripo:6", raw_attributes={"Điện thoại": "(+84) 0234 3824 399"})
    c = make_place("huetripo:7", raw_attributes={"Điện thoại": "0974770000; (+84) 036 677 0000"})
    assert check_facts("Gọi 091 648 2271 [huetripo:5].", [a]) == []
    assert check_facts("Gọi (+84) 91 648 22 71 [huetripo:5].", [a]) == []
    assert check_facts("Số 0234 3824 399 [huetripo:6].", [b]) == []
    assert check_facts("Gọi 036 677 0000 [huetripo:7].", [c]) == []
    assert [m.kind for m in check_facts("Gọi 0905 000 111 [huetripo:7].", [c])] == ["phone"]
