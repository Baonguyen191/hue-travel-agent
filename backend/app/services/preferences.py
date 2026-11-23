"""Pure mapping from free-text preferences and keywords to POI categories.

All phrases are stored in normalized form (see `normalize_vietnamese`). A phrase
matches only as a whole word, so `cho` does not match `choi`.
"""

from __future__ import annotations

import re

from app.schemas.place import Place, PlaceCategory
from app.schemas.request import Theme, TripRequest
from app.services.poi_search import normalize_vietnamese

NATURE_THEME: Theme = "nature"

# Normalized phrases that mean "nature and scenery"; whole-word match, see `map_themes`.
NATURE_PHRASES: tuple[str, ...] = (
    "thien nhien",
    "ngam canh",
    "phong canh",
    "canh dep",
    "hoang hon",
    "song nuoc",
    "song huong",
    "doi thong",
    "bien",
    "check in",
)

# Normalized name terms that make a cafe a view cafe (riverside, garden, lake, rooftop).
VIEW_CAFE_TERMS: tuple[str, ...] = (
    "garden",
    "riverside",
    "song",
    "ho",
    "view",
    "vuon",
    "doi",
    "rooftop",
)

# Source type ("Loại hình (theo nguồn)" after the last "/"), normalized.
_NATURE_SOURCE_TYPE = "thien nhien"
_FOOD_MARKET_SOURCE_TYPES = frozenset({"cho", "cua hang dac san va qua tang"})
# Normalized name terms that mark a shopping centre or supermarket, never a food market.
_MARKET_CHAIN_TERMS: tuple[str, ...] = (
    "sieu thi",
    "vincom",
    "go",
    "mart",
    "plaza",
    "trung tam thuong mai",
)

# Normalized preference phrase -> categories it implies.
PREFERENCE_CATEGORIES: dict[str, tuple[PlaceCategory, ...]] = {
    "di tich": ("historic", "religious"),
    "lich su": ("historic", "religious"),
    "lang": ("historic", "religious"),
    "lang tam": ("historic", "religious"),
    "kinh thanh": ("historic", "religious"),
    "co do": ("historic", "religious"),
    "hoang cung": ("historic", "religious"),
    "chua": ("religious",),
    "nha tho": ("religious",),
    "tam linh": ("religious",),
    "den thap": ("religious",),
    "dac san": ("restaurant",),
    "am thuc": ("restaurant", "cafe", "market"),
    "an uong": ("restaurant",),
    "mon hue": ("restaurant",),
    "quan an": ("restaurant",),
    "nha hang": ("restaurant",),
    "ca phe": ("cafe",),
    "cafe": ("cafe",),
    "coffee": ("cafe",),
    "cho": ("market",),
    "mua sam": ("market",),
    "thien nhien": ("attraction",),
    "cong vien": ("park", "attraction"),
    "song nuoc": ("attraction",),
    "check in": ("attraction",),
    "song huong": ("attraction",),
    "phong canh": ("attraction",),
    "ngam canh": ("attraction",),
    "hoang hon": ("attraction",),
    "bao tang": ("museum",),
}

# Free-text keyword hints. Ambiguous short words (`cho`, `lang`, `chua`) are
# left out because they are also common non-place words.
KEYWORD_HINTS: dict[str, tuple[PlaceCategory, ...]] = {
    "quan ca phe": ("cafe",),
    "ca phe": ("cafe",),
    "cafe": ("cafe",),
    "coffee": ("cafe",),
    "quan an": ("restaurant",),
    "nha hang": ("restaurant",),
    "dac san": ("restaurant",),
    "di tich": ("historic", "religious"),
    "bao tang": ("museum",),
    "cho dong ba": ("market",),
    "cho dem": ("market",),
    "cong vien": ("park", "attraction"),
}

# Words that carry no place meaning once the category hint is removed.
_FILLER_TOKENS = frozenset({"quan", "tiem", "o", "tai", "hue"})

# Normalized phrases that mark a restaurant as a Hue specialty.
HUE_SPECIALTY_TERMS: tuple[str, ...] = (
    "bun bo",
    "com hen",
    "bun hen",
    "banh beo",
    "banh khoai",
    "banh nam",
    "banh loc",
    "che hue",
    "nem lui",
    "bun thit nuong",
    "banh canh",
    "mon hue",
    "dac san",
)


def _contains_phrase(text: str, phrase: str) -> bool:
    """Return True when `phrase` appears in `text` as whole words."""
    return f" {phrase} " in f" {text} "


def _remove_phrase(text: str, phrase: str) -> str:
    """Remove every whole-word occurrence of `phrase` from `text`."""
    padded = f" {text} "
    while f" {phrase} " in padded:
        padded = padded.replace(f" {phrase} ", " ", 1)
    return padded.strip()


def _categories_for(text: str, table: dict[str, tuple[PlaceCategory, ...]]) -> list[PlaceCategory]:
    """Collect categories of every phrase in `table` found in normalized `text`."""
    categories: list[PlaceCategory] = []
    for phrase, phrase_categories in table.items():
        if not _contains_phrase(text, phrase):
            continue
        for category in phrase_categories:
            if category not in categories:
                categories.append(category)
    return categories


def map_preferences(preferences: list[str]) -> tuple[list[PlaceCategory], list[str]]:
    """Return (categories in first-seen order, preferences that matched nothing)."""
    categories: list[PlaceCategory] = []
    unmapped: list[str] = []
    for preference in preferences:
        matched = _categories_for(normalize_vietnamese(preference), PREFERENCE_CATEGORIES)
        if not matched:
            unmapped.append(preference)
            continue
        for category in matched:
            if category not in categories:
                categories.append(category)
    return categories, unmapped


def extract_keyword_hints(keyword: str) -> tuple[list[PlaceCategory], str | None]:
    """Return (hinted categories, residual query); residual is None when empty."""
    residual = normalize_vietnamese(keyword)
    categories: list[PlaceCategory] = []
    # Longest phrases first so `quan ca phe` is consumed before `ca phe`.
    for phrase in sorted(KEYWORD_HINTS, key=len, reverse=True):
        if not _contains_phrase(residual, phrase):
            continue
        for category in KEYWORD_HINTS[phrase]:
            if category not in categories:
                categories.append(category)
        residual = _remove_phrase(residual, phrase)
    tokens = [token for token in residual.split() if token not in _FILLER_TOKENS]
    return categories, " ".join(tokens) or None


def is_hue_specialty(place: Place) -> bool:
    """Return True for a restaurant whose name or summary names a Hue specialty."""
    if place.category != "restaurant":
        return False
    text = f"{normalize_vietnamese(place.name)} {normalize_vietnamese(place.summary or '')}"
    return any(_contains_phrase(text, term) for term in HUE_SPECIALTY_TERMS)


def _plain(text: str) -> str:
    """Normalized text with punctuation as spaces, so `GO!` reads as the word `go`."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", normalize_vietnamese(text)).split())


def source_type(place: Place) -> str | None:
    """The source's type: the part of `Loại hình (theo nguồn)` after the last "/"; None if missing."""
    value = place.raw_attributes.get("Loại hình (theo nguồn)")
    if not value:
        return None
    return str(value).rsplit("/", 1)[-1].strip() or None


def map_themes(preferences: list[str]) -> list[str]:
    """["nature"] when any preference names nature or scenery, else []."""
    for preference in preferences:
        text = _plain(preference)
        if any(_contains_phrase(text, phrase) for phrase in NATURE_PHRASES):
            return [NATURE_THEME]
    return []


def request_themes(request: TripRequest) -> list[str]:
    """Themes stated on the request plus those implied by its free-text preferences."""
    themes = list(request.themes)
    for theme in map_themes(request.preferences):
        if theme not in themes:
            themes.append(theme)
    return themes


def is_food_market(place: Place) -> bool:
    """A market where people eat or buy food: a "Chợ" or specialty shop, not a mall or supermarket."""
    if place.category != "market":
        return False
    kind = source_type(place)
    name = _plain(place.name)
    food_type = kind is not None and _plain(kind) in _FOOD_MARKET_SOURCE_TYPES
    # Some markets carry another source type (Chợ Đông Ba is "Di tích"); the name still says "Chợ".
    named_market = _contains_phrase(name, "cho")
    if not (food_type or named_market):
        return False
    return not any(_contains_phrase(name, term) for term in _MARKET_CHAIN_TERMS)


def is_nature(place: Place) -> bool:
    """A place whose source type is "Thiên nhiên" (nature and scenery)."""
    kind = source_type(place)
    return kind is not None and _plain(kind) == _NATURE_SOURCE_TYPE


def is_view_cafe(place: Place) -> bool:
    """A cafe whose name names a view: a garden, river, lake, hill or rooftop."""
    if place.category != "cafe":
        return False
    name = _plain(place.name)
    return any(_contains_phrase(name, term) for term in VIEW_CAFE_TERMS)
