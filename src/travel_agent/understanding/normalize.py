"""Chuẩn hóa văn bản tiếng Việt bằng code: bỏ dấu để so khớp, đọc số ngày, ánh xạ sở thích.

Mọi hàm ở đây là hàm thuần, không gọi mạng và không raise với đầu vào lạ.
"""

from __future__ import annotations

import functools
import re
import unicodedata
from collections.abc import Hashable, Iterable
from typing import TypeVar

from travel_agent.understanding.models import DurationSpec

_K = TypeVar("_K", bound=Hashable)

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
    "spiritual": (
        "chùa",
        "đi chùa",
        "đền",
        "đền thờ",
        "miếu",
        "tâm linh",
        "nhà thờ",
        "giáo đường",
    ),
    "food": (
        "ăn",
        "ăn uống",
        "ăn sáng",
        "ăn trưa",
        "ăn tối",
        "ăn vặt",
        "đi ăn",
        "ẩm thực",
        "ẩm thực đường phố",
        "đặc sản",
        "hải sản",
        "đồ ăn",
        "món",
        "món ăn",
        "món Huế",
        "nhà hàng",
        "bún",
        "bún bò",
        "cơm hến",
        "bánh bèo",
        "bánh khoái",
    ),
    "coffee": ("cà phê", "cafe", "coffee"),
    "nature": ("thiên nhiên", "sông", "sông hương", "núi", "biển", "đồi", "vườn", "rừng"),
    "photography": ("chụp ảnh", "chụp hình", "sống ảo", "check-in", "check in", "checkin"),
    "shopping": ("mua sắm", "chợ", "đi chợ", "chợ đêm", "quà", "mua quà", "quà lưu niệm"),
    "sightseeing": ("tham quan", "ngắm cảnh"),
}

# Từ khóa ngắn hoặc trùng từ thường (ăn = an toàn, chùa/chua = món chua, sông/sống, cổ/có):
# chỉ khớp khi cả cụm chỉ là đúng từ đó, không khớp khi nằm trong cụm dài. Tính theo dạng đã bỏ dấu.
_EXACT_ONLY: frozenset[str] = frozenset({"an", "den", "co", "chua", "song", "doi", "cho", "qua"})

# Ký tự không phải chữ/số/gạch ngang/khoảng trắng; gạch dưới cũng đổi thành khoảng trắng.
_NON_WORD = re.compile(r"[^\w\- ]|_")


def has_diacritics(text: str) -> bool:
    """True nếu cụm có dấu thanh, dấu mũ, dấu móc hoặc chữ đ/Đ. Quyết định cách so khớp."""
    if "đ" in text.lower():
        return True
    decomposed = unicodedata.normalize("NFD", text)
    return any(unicodedata.category(ch) == _COMBINING_MARK for ch in decomposed)


def _squash(text: str) -> str:
    """NFC, chữ thường, ký tự lạ thành khoảng trắng, gộp khoảng trắng; giữ nguyên dấu."""
    nfc = unicodedata.normalize("NFC", text).lower()
    return " ".join(_NON_WORD.sub(" ", nfc).split())


def clean_phrase(text: str) -> tuple[bool, str]:
    """(cụm có dấu hay không, cụm đã làm sạch để so khớp).

    Cụm có dấu giữ dấu: chỉ khớp với từ khóa có dấu. Cụm không dấu bỏ dấu: khớp với dạng
    không dấu của từ khóa. Vì vậy "tránh chỗ đông" không khớp "chợ", còn "cho dong" (không dấu)
    vẫn khớp "cho" và đó là chỗ còn mơ hồ.
    """
    if has_diacritics(text):
        return True, _squash(text)
    return False, _squash(strip_diacritics(text))


def keyword_form(keyword: str, diacritic: bool) -> str:
    """Dạng của từ khóa cùng loại với cụm: có dấu nếu diacritic, không dấu nếu không."""
    return _squash(keyword) if diacritic else _squash(strip_diacritics(keyword))


@functools.cache
def keyword_pattern(form: str, exact: bool = False) -> re.Pattern[str]:
    """Regex khớp form đứng riêng (ranh giới là không phải chữ/số). exact: cả cụm phải bằng form."""
    escaped = re.escape(form)
    if exact:
        return re.compile(rf"^{escaped}$")
    return re.compile(rf"(?<!\w){escaped}(?!\w)")


def keyword_hits(
    phrase: str,
    pairs: Iterable[tuple[_K, str]],
    exact_words: frozenset[str] = frozenset(),
) -> set[_K]:
    """Nhãn của các cặp (nhãn, từ khóa) khớp với cụm, theo quy tắc của clean_phrase.

    exact_words: các từ khóa (dạng không dấu) chỉ khớp khi cả cụm đúng là từ đó.
    """
    diacritic, cleaned = clean_phrase(phrase)
    if not cleaned:
        return set()
    hits: set[_K] = set()
    for label, keyword in pairs:
        exact = strip_diacritics(keyword) in exact_words
        if keyword_pattern(keyword_form(keyword, diacritic), exact).search(cleaned):
            hits.add(label)
    return hits


_INTEREST_PAIRS: tuple[tuple[str, str], ...] = tuple(
    (interest, keyword) for interest, keywords in INTEREST_KEYWORDS.items() for keyword in keywords
)


def map_interests(phrases: Iterable[str]) -> tuple[list[str], list[str]]:
    """Ánh xạ cụm sở thích về 9 từ trong INTEREST_CATEGORIES.

    Trả về (sở thích đã sắp xếp, không trùng; các cụm không ánh xạ được giữ nguyên văn).
    Cụm rỗng bị bỏ qua. Cụm không ánh xạ được nên đưa vào ParsedQuery.soft_preferences.
    """
    found: set[str] = set()
    unmatched: list[str] = []
    for phrase in phrases:
        if not clean_phrase(phrase)[1]:
            continue
        hits = keyword_hits(phrase, _INTEREST_PAIRS, _EXACT_ONLY)
        if hits:
            found |= hits
        else:
            unmatched.append(phrase)
    return sorted(found), unmatched
