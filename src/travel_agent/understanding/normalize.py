"""Chuẩn hóa văn bản tiếng Việt bằng code: bỏ dấu để so khớp, đọc số ngày, ánh xạ sở thích.

Mọi hàm ở đây là hàm thuần, không gọi mạng và không raise với đầu vào lạ.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from travel_agent.understanding.models import DurationSpec

_COMBINING_MARK = "Mn"


def strip_diacritics(text: str) -> str:
    """Bỏ dấu tiếng Việt, đổi đ/Đ thành d/D, chuyển chữ thường và gộp khoảng trắng.

    "Đại Nội" -> "dai noi". Dùng để so khớp với người gõ không dấu.
    """
    decomposed = unicodedata.normalize("NFD", text)
    kept = "".join(ch for ch in decomposed if unicodedata.category(ch) != _COMBINING_MARK)
    kept = kept.replace("đ", "d").replace("Đ", "D")
    return " ".join(kept.lower().split())


# ---------------------------------------------------------------------------
# Thời lượng
# ---------------------------------------------------------------------------

# Số chữ tiếng Việt đã bỏ dấu, chỉ 1..7 vì chuyến đi tối đa 7 ngày.
_NUMBER_WORDS: dict[str, int] = {
    "mot": 1,
    "hai": 2,
    "ba": 3,
    "bon": 4,
    "nam": 5,
    "sau": 6,  # "sáu" sau khi bỏ dấu; "sau ngày" hiếm nên chấp nhận lẫn này
    "bay": 7,
}
_NUMBER = r"(\d+|mot|hai|ba|bon|nam|sau|bay)"
# "2 ngày", "3 hôm"; đêm không cần đếm vì số ngày đã đủ.
_DAY_RE = re.compile(rf"(?<![a-z0-9]){_NUMBER}\s*(?:ngay|hom)(?![a-z0-9])")
# "2n1đ" sau khi bỏ dấu là "2n1d".
_NIGHTS_RE = re.compile(r"(?<![a-z0-9])(\d+)\s*n\s*\d+\s*d(?![a-z0-9])")
_HALF_DAY_RE = re.compile(r"(?<![a-z0-9])(?:nua ngay|nua buoi|(?:mot|1)\s*buoi)(?![a-z0-9])")


def _to_number(token: str) -> int:
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS[token]


def parse_duration(text: str) -> DurationSpec | None:
    """Đọc số ngày đi từ câu. Trả None nếu không có cụm thời lượng nào.

    Ví dụ: "2 ngày 1 đêm" -> 2 ngày; "2n1đ" -> 2 ngày; "nửa ngày" -> 1 ngày, half_day.
    Số không hợp lệ (0) bị bỏ qua. Giới hạn 1..7 do PlanRequest kiểm tra, không kiểm ở đây.
    """
    normalized = strip_diacritics(text)
    for match in _DAY_RE.finditer(normalized):
        days = _to_number(match.group(1))
        if days >= 1:
            return DurationSpec(num_days=days, half_day=False)
    for match in _NIGHTS_RE.finditer(normalized):
        days = int(match.group(1))
        if days >= 1:
            return DurationSpec(num_days=days, half_day=False)
    if _HALF_DAY_RE.search(normalized):
        return DurationSpec(num_days=1, half_day=True)
    return None


# ---------------------------------------------------------------------------
# Sở thích
# ---------------------------------------------------------------------------

# HEURISTIC, không phải từ điển: chỉ là bảng từ khóa do người viết chọn để bắt các cách nói
# thường gặp. Chưa kiểm chứng bằng dữ liệu người dùng. Từ khóa viết có dấu, sẽ được bỏ dấu khi
# dùng. Kết quả giả định câu không phủ định: "không đi chợ" vẫn ra "shopping", phần loại trừ
# do LLM và ParsedQuery.exclude_categories xử lý.
INTEREST_KEYWORDS: dict[str, tuple[str, ...]] = {
    "history": (
        "lăng tẩm",
        "lăng",
        "di tích",
        "cổ",
        "cổ kính",
        "lịch sử",
        "hoàng thành",
        "đại nội",
    ),
    "culture": ("bảo tàng", "văn hóa", "nghệ thuật"),
    "spiritual": ("chùa", "đi chùa", "đền", "đền thờ", "miếu", "tâm linh"),
    "food": (
        "ăn",
        "ăn uống",
        "ăn sáng",
        "ăn trưa",
        "ăn tối",
        "ăn vặt",
        "đi ăn",
        "ẩm thực",
        "đặc sản",
        "món",
        "nhà hàng",
    ),
    "coffee": ("cà phê", "cafe", "coffee"),
    "nature": ("thiên nhiên", "sông", "sông hương", "núi", "biển", "đồi", "vườn", "rừng"),
    "photography": ("chụp ảnh", "chụp hình", "sống ảo", "check-in", "check in", "checkin"),
    "shopping": ("mua sắm", "chợ", "đi chợ", "chợ đêm", "quà", "mua quà", "quà lưu niệm"),
    "sightseeing": ("tham quan", "ngắm cảnh"),
}

# Từ khóa ngắn hoặc trùng từ thường (ăn = an toàn, chùa/chua = món chua, sông/sống, cổ/có):
# chỉ khớp khi cả cụm chỉ là đúng từ đó, không khớp khi nằm trong cụm dài.
_EXACT_ONLY: frozenset[str] = frozenset({"an", "den", "co", "chua", "song", "doi", "cho", "qua"})


def _clean_phrase(text: str) -> str:
    """Bỏ dấu, thay ký tự không phải chữ/số/gạch ngang bằng khoảng trắng."""
    stripped = strip_diacritics(text)
    return " ".join(re.sub(r"[^a-z0-9\- ]", " ", stripped).split())


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    stripped = strip_diacritics(keyword)
    escaped = re.escape(stripped)
    if stripped in _EXACT_ONLY:
        return re.compile(rf"^{escaped}$")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])")


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (interest, _keyword_pattern(keyword))
    for interest, keywords in INTEREST_KEYWORDS.items()
    for keyword in keywords
)


def map_interests(phrases: Iterable[str]) -> tuple[list[str], list[str]]:
    """Ánh xạ cụm sở thích về 9 từ trong INTEREST_CATEGORIES.

    Trả về (sở thích đã sắp xếp, không trùng; các cụm không ánh xạ được giữ nguyên văn).
    Cụm rỗng bị bỏ qua. Cụm không ánh xạ được nên đưa vào ParsedQuery.soft_preferences.
    """
    found: set[str] = set()
    unmatched: list[str] = []
    for phrase in phrases:
        cleaned = _clean_phrase(phrase)
        if not cleaned:
            continue
        hits = {interest for interest, pattern in _PATTERNS if pattern.search(cleaned)}
        if hits:
            found |= hits
        else:
            unmatched.append(phrase)
    return sorted(found), unmatched
