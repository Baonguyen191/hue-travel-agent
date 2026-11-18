"""Đổi cụm ngày tiếng Việt (nguyên văn từ LLM hoặc người dùng) thành ngày cụ thể.

LLM không tự tính ngày; hàm này tính theo ngày tham chiếu ref (hôm nay, hoặc ngày cố định khi
eval). Không hiểu thì trả None, không raise. Khớp không phân biệt dấu, và cụm phải khớp
toàn bộ (sau khi bỏ dấu, đổi về chữ thường, bỏ dấu câu ở hai đầu).

Quy tắc đã chọn (thứ Hai = 0 ... Chủ nhật = 6, như datetime.weekday()):
- "hôm nay" = ref; "mai" / "ngày mai" = ref + 1; "ngày kia" / "ngày mốt" / "mốt" = ref + 2.
- "thứ X này" = thứ X gần nhất từ ref trở đi, tính cả ref (thứ X trùng ref thì trả ref).
- "thứ X" và "thứ X tới" / "thứ X sau" = thứ X đầu tiên sau ref, KHÔNG tính ref.
  (Hôm thứ Tư nói "thứ 4" thì hiểu là tuần sau; đây là lựa chọn, không phải sự thật ngôn ngữ.)
  X: "2" / "hai" .. "7" / "bảy"; "chủ nhật" / "CN" = Chủ nhật.
- "cuối tuần này" (và "cuối tuần" trơ) = thứ Bảy gần nhất từ ref trở đi; nếu ref là Chủ nhật
  thì trả ref.
- "cuối tuần sau" / "cuối tuần tới" = mốc "cuối tuần này" + 7 ngày.
- "tuần sau" / "tuần tới" = thứ Hai đầu tiên sau ref, KHÔNG tính ref.
- "dd/mm", "dd-mm", "dd.mm" (không năm): ngày đầu tiên từ ref trở đi (nếu năm ref đã qua thì
  sang năm sau). Ngày không tồn tại trong năm (29/02 năm không nhuận) được bỏ qua sang năm
  nhuận kế tiếp; tối đa tìm 8 năm.
- "dd/mm/yyyy", "dd-mm-yyyy", "ngày dd tháng mm năm yyyy": đúng ngày đó, không dời năm.
  Năm phải đủ 4 chữ số; "20/12/26" không hiểu, trả None.
- "ngày dd tháng mm" (không năm): như dd/mm.
- "đầu tháng N" = ngày 1, "giữa tháng N" = ngày 15, "cuối tháng N" = ngày 25 (không dùng ngày
  cuối tháng vì khác nhau theo tháng; đây là quy ước). Năm: như dd/mm, hoặc "năm yyyy".
- "tết dương lịch" = 1/1; "giáng sinh" / "noel" = 24/12: lần đầu từ ref trở đi.
- Ngày không hợp lệ (31/02, 00/12, tháng 13...) trả None.
"""

from __future__ import annotations

import datetime as dt
import re

from travel_agent.understanding.normalize import strip_diacritics

_SATURDAY = 5
_SUNDAY = 6
_MONDAY = 0

# Số thứ trong tuần (đã bỏ dấu) -> weekday() của Python. Thứ 2..7 ứng với Thứ Hai..Thứ Bảy.
_WEEKDAY_INDEX: dict[str, int] = {
    "2": 0,
    "hai": 0,
    "3": 1,
    "ba": 1,
    "4": 2,
    "tu": 2,
    "5": 3,
    "nam": 3,
    "6": 4,
    "sau": 4,
    "7": 5,
    "bay": 5,
}

_RELATIVE_DAYS: dict[str, int] = {
    "hom nay": 0,
    "mai": 1,
    "ngay mai": 1,
    "ngay kia": 2,
    "ngay mot": 2,
    "mot": 2,
}

_WEEKDAY_RE = re.compile(r"(?:thu (\d|hai|ba|tu|nam|sau|bay)|(chu nhat|cn))(?: (nay|toi|sau))?")
_WEEKEND_RE = re.compile(r"cuoi tuan(?: (nay|toi|sau))?")
_NEXT_WEEK_RE = re.compile(r"tuan (?:sau|toi)")
_HOLIDAY_JAN_1 = "tet duong lich"
_HOLIDAY_DEC_24 = frozenset({"giang sinh", "noel"})
_NUMERIC_RE = re.compile(r"(?:ngay )?(\d{1,2})\s*[./-]\s*(\d{1,2})(?:\s*[./-]\s*(\d{4}))?")
_WORDS_DATE_RE = re.compile(r"(?:ngay )?(\d{1,2}) thang (\d{1,2})(?: nam (\d{4}))?")
_PART_OF_MONTH_RE = re.compile(r"(dau|giua|cuoi) thang (\d{1,2})(?: nam (\d{4}))?")
_PART_OF_MONTH_DAY: dict[str, int] = {"dau": 1, "giua": 15, "cuoi": 25}
_MAX_YEARS_TO_SEARCH = 8


def _clean(text: str) -> str:
    """Bỏ dấu, giữ chữ số, "/", "." và "-"; bỏ dấu câu ở hai đầu; gộp khoảng trắng."""
    stripped = re.sub(r"[^a-z0-9./\- ]", " ", strip_diacritics(text))
    return " ".join(stripped.strip(" ./-").split())


def _next_weekday(ref: dt.date, weekday: int, *, include_ref: bool) -> dt.date:
    delta = (weekday - ref.weekday()) % 7
    if delta == 0 and not include_ref:
        delta = 7
    return ref + dt.timedelta(days=delta)


def _weekend_saturday(ref: dt.date) -> dt.date:
    """Thứ Bảy của "cuối tuần này": Chủ nhật ref thì trả ref, còn lại là thứ Bảy gần nhất."""
    if ref.weekday() == _SUNDAY:
        return ref
    return _next_weekday(ref, _SATURDAY, include_ref=True)


def _next_occurrence(month: int, day: int, ref: dt.date) -> dt.date | None:
    """Lần đầu tiên từ ref trở đi có ngày/tháng này. None nếu ngày không tồn tại trong các năm."""
    for year in range(ref.year, ref.year + _MAX_YEARS_TO_SEARCH):
        try:
            candidate = dt.date(year, month, day)
        except ValueError:
            continue
        if candidate >= ref:
            return candidate
    return None


def _date_with_optional_year(
    day: int, month: int, year_text: str | None, ref: dt.date
) -> dt.date | None:
    if year_text is None:
        return _next_occurrence(month, day, ref)
    return dt.date(int(year_text), month, day)


def _resolve(text: str, ref: dt.date) -> dt.date | None:
    cleaned = _clean(text)
    if not cleaned:
        return None
    if cleaned in _RELATIVE_DAYS:
        return ref + dt.timedelta(days=_RELATIVE_DAYS[cleaned])

    weekday_match = _WEEKDAY_RE.fullmatch(cleaned)
    if weekday_match is not None:
        number, chu_nhat, modifier = weekday_match.groups()
        if chu_nhat is not None:
            target = _SUNDAY
        elif number is not None and number in _WEEKDAY_INDEX:
            target = _WEEKDAY_INDEX[number]
        else:
            return None
        return _next_weekday(ref, target, include_ref=modifier == "nay")

    weekend_match = _WEEKEND_RE.fullmatch(cleaned)
    if weekend_match is not None:
        anchor = _weekend_saturday(ref)
        if weekend_match.group(1) in ("sau", "toi"):
            return anchor + dt.timedelta(days=7)
        return anchor

    if _NEXT_WEEK_RE.fullmatch(cleaned) is not None:
        return _next_weekday(ref, _MONDAY, include_ref=False)

    if cleaned == _HOLIDAY_JAN_1:
        return _next_occurrence(1, 1, ref)
    if cleaned in _HOLIDAY_DEC_24:
        return _next_occurrence(12, 24, ref)

    numeric_match = _NUMERIC_RE.fullmatch(cleaned)
    if numeric_match is not None:
        day, month, year_text = numeric_match.groups()
        return _date_with_optional_year(int(day), int(month), year_text, ref)

    words_match = _WORDS_DATE_RE.fullmatch(cleaned)
    if words_match is not None:
        day, month, year_text = words_match.groups()
        return _date_with_optional_year(int(day), int(month), year_text, ref)

    part_match = _PART_OF_MONTH_RE.fullmatch(cleaned)
    if part_match is not None:
        part, month, year_text = part_match.groups()
        day = _PART_OF_MONTH_DAY[part]
        return _date_with_optional_year(day, int(month), year_text, ref)

    return None


def resolve_date_text(text: str, ref: dt.date) -> dt.date | None:
    """Đổi cụm ngày tiếng Việt thành ngày, tính theo ref. Không hiểu hoặc không hợp lệ: None."""
    try:
        return _resolve(text, ref)
    except (ValueError, OverflowError):
        return None
