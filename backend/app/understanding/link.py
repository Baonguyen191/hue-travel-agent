"""Link place names the user wrote to a POI in the Hue database.

Matching runs on folded names (no diacritics, lower case, no punctuation). Each place gets the
best score of the first rule that applies:
1. Exact match, also after dropping a parenthesis ("Chùa Thiên Mụ (Chùa Linh Mụ)"): 1.0
2. The mention's words (2 or more) appear in the name in the same order: 0.85
3. The name (2 or more words) appears in the mention in order: 0.8
4. Otherwise difflib ratio times 0.9, so character overlap alone cannot beat a word match.

Food rule: when the mention has no food word, restaurant and cafe places are multiplied by
0.8, so "chùa Thiên Mụ" links to the pagoda and not to a tofu stall with the pagoda's name.

Below MIN_SCORE the poi_id is None and the best score is still reported. When two different
places are close to the best one, a note lists them and the best one is still chosen.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.schemas.place import Place
from app.understanding.models import PlaceMention
from app.understanding.normalize import strip_diacritics

MIN_SCORE = 0.7
AMBIGUITY_GAP = 0.2
_SUBSEQUENCE_SCORE = 0.85
_CONTAINS_NAME_SCORE = 0.8
_FUZZY_FACTOR = 0.9
_FOOD_PENALTY = 0.8
_FOOD_CATEGORIES = frozenset({"restaurant", "cafe"})
# Food words (folded). A mention that contains one is not penalised for a food place.
_FOOD_WORDS = frozenset(
    {
        "quan", "cafe", "ca", "phe", "nha", "hang", "an", "banh", "com", "bun", "pho", "mi",
        "hu", "che", "oc", "bar", "lau", "nuong", "san",
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
    """True when the words of needle appear in haystack in order (not necessarily adjacent)."""
    position = 0
    for word in haystack:
        if position < len(needle) and word == needle[position]:
            position += 1
    return position == len(needle)


def _text_score(mention: str, name: str) -> tuple[float, float]:
    """(score before the food penalty, difflib ratio) for one name variant."""
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
    """(score after the food penalty, best raw ratio) for one place."""
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


def _candidates(places: Sequence[Place]) -> list[_Candidate]:
    return [
        _Candidate(
            place=place,
            variants=_name_variants(place.name),
            tokens=frozenset(_normalize(place.name).split()),
        )
        for place in sorted(places, key=lambda item: item.id)
    ]


def _scored(normalized: str, candidates: Sequence[_Candidate]) -> list[tuple[float, float, _Candidate]]:
    """(score, ratio, candidate) for every place that shares at least one word with the mention."""
    tokens = set(normalized.split())
    has_food = bool(tokens & _FOOD_WORDS)
    scored: list[tuple[float, float, _Candidate]] = []
    for candidate in candidates:
        if tokens.isdisjoint(candidate.tokens):
            continue
        score, ratio = _best_score(normalized, has_food, candidate)
        scored.append((score, ratio, candidate))
    return sorted(scored, key=lambda item: (-item[0], -item[1], item[2].place.id))


def _ambiguity_note(mention: str, ranked: Sequence[tuple[float, float, _Candidate]]) -> str | None:
    """A note when a second place is within AMBIGUITY_GAP of the best and also above MIN_SCORE."""
    if len(ranked) < 2:
        return None
    best, second = ranked[0], ranked[1]
    if second[0] < MIN_SCORE or best[0] - second[0] >= AMBIGUITY_GAP:
        return None
    return (
        f"Tên '{mention}' khớp nhiều địa điểm: "
        f"{best[2].place.id} ({best[2].place.name}), {second[2].place.id} ({second[2].place.name})."
    )


def link_places(
    mentions: Sequence[str],
    places: Sequence[Place],
    notes: list[str] | None = None,
) -> list[PlaceMention]:
    """Link each mention to its best place; one result per non-blank mention, in input order.

    notes, when given, receives a line for every mention that matched several places closely.
    Invented ids never happen: poi_id is only set from `places`.
    """
    candidates = _candidates(places)
    linked: list[PlaceMention] = []
    for mention in mentions:
        normalized = _normalize(mention)
        if not normalized:
            continue
        ranked = _scored(normalized, candidates)
        if not ranked:
            linked.append(PlaceMention(text=mention.strip(), score=0.0))
            continue
        best_score, _, best = ranked[0]
        is_linked = best_score >= MIN_SCORE
        linked.append(
            PlaceMention(
                text=mention.strip(),
                poi_id=best.place.id if is_linked else None,
                name=best.place.name if is_linked else None,
                score=min(1.0, max(0.0, best_score)),
            )
        )
        note = _ambiguity_note(mention.strip(), ranked)
        if note is not None and notes is not None:
            notes.append(note)
    return linked
