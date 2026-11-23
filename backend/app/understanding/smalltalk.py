"""Smalltalk: greetings, thanks, goodbyes and questions about the assistant itself.

`smalltalk_kind` decides from the folded text only (no diacritics, lower case, words of a-z0-9).
Short messages only: more than 8 words, or any digit, is a trip or a question, not smalltalk.
Phrases match on whole words. A greeting must start the message and be followed only by filler
words, so "Cháo ở đâu ngon?" (folds to "chao") is not a greeting.

The chat answers smalltalk with fixed templates from `app.chat.texts`; the LLM never writes it.
"""

from __future__ import annotations

import re
from typing import Literal

from app.understanding.normalize import strip_diacritics

SmalltalkKind = Literal["identity", "thanks", "goodbye", "greeting"]

MAX_WORDS = 8
_NON_WORD = re.compile(r"[^a-z0-9]+")
_DIGIT = re.compile(r"\d")

_IDENTITY_PHRASES = (
    "ban la ai",
    "ban lam duoc gi",
    "ban giup duoc gi",
    "ban co the lam gi",
    "ban giup gi duoc",
    "huong dan su dung",
)
# "làm được gì" alone is too broad: "Ở Huế làm được gì vui?" is a trip question.
_THANKS_PHRASES = ("cam on", "thanks", "thank you", "tks", "camon")
_GOODBYE_PHRASES = ("tam biet", "bye", "hen gap lai")
_GREETING_OPENERS = ("xin chao", "chao", "hello", "hi", "alo", "hey")
_GREETING_FILLERS = frozenset(
    {"ban", "nhe", "a", "nha", "minh", "em", "anh", "chi", "shop", "bot", "tro", "ly", "oi"}
)


def _words(text: str) -> list[str]:
    return _NON_WORD.sub(" ", strip_diacritics(text)).split()


def _has_phrase(words: list[str], phrases: tuple[str, ...]) -> bool:
    padded = f" {' '.join(words)} "
    return any(f" {phrase} " in padded for phrase in phrases)


def _is_greeting(words: list[str]) -> bool:
    for opener in _GREETING_OPENERS:
        head = opener.split()
        if words[: len(head)] == head and all(word in _GREETING_FILLERS for word in words[len(head) :]):
            return True
    return False


def smalltalk_kind(text: str) -> SmalltalkKind | None:
    """The smalltalk kind of a short message, or None when it is not smalltalk."""
    if _DIGIT.search(text):
        return None
    words = _words(text)
    if not words or len(words) > MAX_WORDS:
        return None
    if _has_phrase(words, _IDENTITY_PHRASES):
        return "identity"
    if _has_phrase(words, _THANKS_PHRASES):
        return "thanks"
    if _has_phrase(words, _GOODBYE_PHRASES):
        return "goodbye"
    if _is_greeting(words):
        return "greeting"
    return None
