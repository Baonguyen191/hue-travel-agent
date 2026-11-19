"""Liên kết tên địa điểm người dùng nhắc tới với một place trong DB.

So khớp trên tên đã bỏ dấu, chữ thường, bỏ dấu câu. Điểm của mỗi địa điểm lấy theo bậc
đầu tiên đúng:
1. Trùng hoàn toàn, kể cả khi bỏ phần trong ngoặc ("Chùa Thiên Mụ (Chùa Linh Mụ)"): 1.0
2. Các từ của cụm nhắc tới (từ 2 từ trở lên) xuất hiện đúng thứ tự trong tên, liền nhau hoặc
   cách quãng ("Đại Nội" trong "Đại Nội Huế"; "lăng Tự Đức" trong "Lăng vua Tự Đức"): 0.85
3. Tên nằm nguyên trong cụm nhắc tới, tên có từ 2 chữ trở lên: 0.8
4. Còn lại: độ tương đồng difflib (SequenceMatcher.ratio) nhân 0.9. Hệ số này để ký tự giống
   nhau không thắng khớp theo từ ("lăng Dục Đức" không được thắng "Lăng vua Tự Đức").

Quy tắc loại ăn uống: nếu cụm nhắc tới không có từ ăn uống (quán, cà phê, nhà hàng, cơm, bánh...),
địa điểm loại restaurant hoặc cafe bị nhân 0.8. Nhờ vậy "chùa Thiên Mụ" ra chùa chứ không ra quán
đậu hũ có tên chứa "chùa Thiên Mụ". Cụm nhắc tới có từ ăn uống thì không bị phạt.

Dưới MIN_SCORE (0.7) thì place_id là None, score vẫn là điểm tốt nhất để báo. Hòa điểm: lấy
độ tương đồng cao hơn, rồi id nhỏ hơn, để kết quả xác định.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass

from travel_agent.domain.models import Category, Place
from travel_agent.understanding.models import PlaceMention
from travel_agent.understanding.normalize import strip_diacritics

MIN_SCORE = 0.7
_SUBSEQUENCE_SCORE = 0.85
_CONTAINS_NAME_SCORE = 0.8
_FUZZY_FACTOR = 0.9
_FOOD_PENALTY = 0.8
_FOOD_CATEGORIES = frozenset({Category.RESTAURANT, Category.CAFE})
# Từ ăn uống đã bỏ dấu. Có trong cụm nhắc tới thì không phạt loại quán.
_FOOD_WORDS = frozenset(
    {
        "quan",
        "cafe",
        "ca",
        "phe",
        "nha",
        "hang",
        "an",
        "banh",
        "com",
        "bun",
        "pho",
        "mi",
        "hu",
        "che",
        "oc",
        "bar",
        "lau",
        "nuong",
        "san",
    }
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_PARENTHESIS = re.compile(r"\([^)]*\)")


@dataclass(frozen=True)
class _Candidate:
    place: Place
    variants: frozenset[str]
    tokens: frozenset[str]


def _normalize(text: str) -> str:
    return " ".join(_NON_ALNUM.sub(" ", strip_diacritics(text)).split())


def _name_variants(name: str) -> frozenset[str]:
    variants = {_normalize(name), _normalize(_PARENTHESIS.sub(" ", name))}
    variants.discard("")
    return frozenset(variants)


def _is_subsequence(needle: Sequence[str], haystack: Sequence[str]) -> bool:
    """Các từ của needle có mặt trong haystack đúng thứ tự (không nhất thiết liền nhau)."""
    position = 0
    for word in haystack:
        if position < len(needle) and word == needle[position]:
            position += 1
    return position == len(needle)


def _text_score(mention: str, name: str) -> tuple[float, float]:
    """(điểm không phạt, độ tương đồng difflib) của một biến thể tên."""
    ratio = difflib.SequenceMatcher(None, mention, name).ratio()
    if mention == name:
        return 1.0, ratio
    mention_words = mention.split()
    name_words = name.split()
    if len(mention_words) >= 2 and _is_subsequence(mention_words, name_words):
        return _SUBSEQUENCE_SCORE, ratio
    if len(name_words) >= 2 and _is_subsequence(name_words, mention_words):
        return _CONTAINS_NAME_SCORE, ratio
    return ratio * _FUZZY_FACTOR, ratio


def _best_score(mention: str, mention_has_food: bool, candidate: _Candidate) -> tuple[float, float]:
    """(điểm sau phạt, độ tương đồng thô) của một địa điểm; lấy biến thể tên tốt nhất."""
    text_best = 0.0
    ratio_best = 0.0
    for variant in candidate.variants:
        text, ratio = _text_score(mention, variant)
        text_best = max(text_best, text)
        ratio_best = max(ratio_best, ratio)
    score = text_best
    if not mention_has_food and candidate.place.category in _FOOD_CATEGORIES:
        score *= _FOOD_PENALTY
    return score, ratio_best


def link_places(mentions: Sequence[str], places: Sequence[Place]) -> list[PlaceMention]:
    """Liên kết từng cụm tên với địa điểm tốt nhất trong `places`.

    Cụm rỗng (sau khi bỏ dấu câu) bị bỏ qua. Trả về cùng thứ tự với `mentions`, mỗi cụm một mục.
    """
    candidates = [
        _Candidate(
            place=place,
            variants=_name_variants(place.name),
            tokens=frozenset(_normalize(place.name).split()),
        )
        for place in sorted(places, key=lambda item: item.id)
    ]
    linked: list[PlaceMention] = []
    for mention in mentions:
        normalized = _normalize(mention)
        if not normalized:
            continue
        tokens = set(normalized.split())
        has_food = bool(tokens & _FOOD_WORDS)
        best_place: str | None = None
        best_key = (-1.0, -1.0)
        best_score = 0.0
        for candidate in candidates:
            if tokens.isdisjoint(candidate.tokens):
                continue
            score, ratio = _best_score(normalized, has_food, candidate)
            best_score = max(best_score, score)
            if (score, ratio) > best_key:
                best_key = (score, ratio)
                best_place = candidate.place.id
        linked_id = best_place if best_key[0] >= MIN_SCORE else None
        linked.append(
            PlaceMention(
                text=mention.strip(),
                place_id=linked_id,
                score=min(1.0, max(0.0, best_score)),
            )
        )
    return linked
