"""Tour-guide text for POIs: the lead of a Vietnamese Wikipedia article, read from the committed corpus.

The corpus (`app/data/guide_corpus.json`) is built by `backend/scripts/build_guide_corpus.py`. Texts are
copied from the stored lead, never generated, so every sentence shown to a user can be traced to the article.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

from app.schemas.place import GuideSection, PlaceGuide

GUIDE_PATH = Path(__file__).resolve().parents[1] / "data" / "guide_corpus.json"
TEXT_LIMIT = 1200
SECTION_LIMIT = 900
INTRO_LIMIT = 160
ELLIPSIS = "…"

# Abbreviations whose trailing period does not end a sentence (compared case-insensitively).
ABBREVIATIONS = frozenset({"tp", "st", "dr", "ths", "gs", "ts", "pgs", "vn", "km", "tk", "sđd", "sd"})
_TERMINATORS = ".!?"
_WORD_BEFORE = re.compile(r"([^\W\d_]+)$")
_CLOSERS = "\"'”’)»"


def _is_sentence_end(text: str, index: int) -> bool:
    """True when the terminator at `index` ends a sentence: whitespace or the end follows, and the next
    word does not continue in lower case. Abbreviations ("TP.", "St.") and single letters do not end one."""
    character = text[index]
    following = index + 1
    while following < len(text) and text[following] in _CLOSERS:
        following += 1
    if following < len(text) and not text[following].isspace():
        return False  # "1.000", "v.v", "www.x.vn": the terminator is inside a token
    if character == ".":
        word = _WORD_BEFORE.search(text[:index])
        if word is not None:
            token = word.group(1).casefold()
            if token in ABBREVIATIONS:
                return False
    rest = text[following:].lstrip()
    if rest and rest[0].islower():
        return False
    return True


def split_sentences(text: str) -> list[str]:
    """Split plain text into sentences on ". ", "? " and "! ", skipping numbers and common abbreviations."""
    sentences: list[str] = []
    start = 0
    for index, character in enumerate(text):
        if character in _TERMINATORS and _is_sentence_end(text, index):
            end = index + 1
            while end < len(text) and text[end] in _CLOSERS:
                end += 1
            sentence = text[start:end].strip()
            if sentence:
                sentences.append(sentence)
            start = end
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _cut_at_word(text: str, limit: int) -> str:
    """The longest prefix of `text` that fits `limit` with the ellipsis, ending at a word boundary."""
    room = limit - len(ELLIPSIS)
    cut = text[: room + 1]
    boundary = cut.rfind(" ")
    head = cut[:boundary] if boundary > 0 else text[:room]
    return head.rstrip(" ,;:-–") + ELLIPSIS


def trim_text(lead: str, limit: int = TEXT_LIMIT) -> str:
    """At most `limit` characters, cut at the last sentence end that fits; a word cut with "…" otherwise."""
    lead = lead.strip()
    if len(lead) <= limit:
        return lead
    kept: list[str] = []
    length = 0
    for sentence in split_sentences(lead):
        added = len(sentence) if not kept else length + 1 + len(sentence)
        if added > limit:
            break
        kept.append(sentence)
        length = added
    if kept:
        return " ".join(kept)
    return _cut_at_word(lead, limit)


@functools.lru_cache(maxsize=4)
def load_corpus(path: Path) -> dict[str, dict[str, str]]:
    """The corpus by POI id; an empty mapping when the file is absent."""
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _entry(poi_id: str) -> dict[str, str] | None:
    return load_corpus(GUIDE_PATH).get(poi_id)


_HAN = re.compile(r"[㐀-鿿豈-﫿]")
_PARENTHESES = re.compile(r"\s*\(([^()]*)\)")


def strip_han(text: str) -> str:
    """Drop the parts of a parenthesis that hold Han characters ("Hán Nôm: 香江"); drop the
    parenthesis when nothing is left. Travellers reading Vietnamese do not need them."""

    def keep(match: re.Match[str]) -> str:
        parts = [part.strip() for part in match.group(1).split(",")]
        kept = [part for part in parts if part and not _HAN.search(part)]
        return f" ({', '.join(kept)})" if kept else ""

    # Wikipedia footnote numbers glued to a word ("người Chăm1.") are dropped as well.
    return _GLUED_FOOTNOTE.sub("", _PARENTHESES.sub(keep, text))


# A 1–2 digit footnote number right after a letter, before a space, punctuation or the end.
_GLUED_FOOTNOTE = re.compile(r"(?<=[^\W\d_])\d{1,2}(?=[\s.,;:!?)]|$)")


def _sections_for(entry: dict) -> list[GuideSection]:
    """The stored sections, cleaned like the lead; sections that end up empty are dropped."""
    sections: list[GuideSection] = []
    for stored in entry.get("sections") or []:
        text = trim_text(strip_han(stored["text"]), SECTION_LIMIT)
        if text:
            sections.append(GuideSection(heading=stored["heading"], text=text))
    return sections


def guide_for(poi_id: str) -> PlaceGuide | None:
    """The stored article lead and short sections for a POI, trimmed for display; None when the POI has no
    guide entry."""
    entry = _entry(poi_id)
    if entry is None:
        return None
    text = trim_text(strip_han(entry["lead"]))
    if not text:
        return None
    return PlaceGuide(
        text=text,
        title=entry["title"],
        url=entry["url"],
        license=entry["license"],
        retrieved_at=entry["retrieved_at"],
        sections=_sections_for(entry),
    )


def intro_for(poi_id: str) -> str | None:
    """The first sentence of the guide text, at most 160 characters (cut at a word, with "…")."""
    guide = guide_for(poi_id)
    if guide is None:
        return None
    first = split_sentences(guide.text)[0]
    if len(first) <= INTRO_LIMIT:
        return first
    return _cut_at_word(first, INTRO_LIMIT)


def guide_sentences(poi_id: str, n: int = 4) -> list[str]:
    """The first `n` sentences of the guide text; an empty list when there is no guide."""
    guide = guide_for(poi_id)
    if guide is None:
        return []
    return split_sentences(guide.text)[:n]
