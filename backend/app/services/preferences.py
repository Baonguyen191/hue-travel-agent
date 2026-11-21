"""Pure mapping from free-text preferences and keywords to POI categories.

All phrases are stored in normalized form (see `normalize_vietnamese`). A phrase
matches only as a whole word, so `cho` does not match `choi`.
"""

from __future__ import annotations

from app.schemas.place import Place, PlaceCategory
from app.services.poi_search import normalize_vietnamese

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
    "am thuc": ("restaurant",),
    "an uong": ("restaurant",),
    "mon hue": ("restaurant",),
    "quan an": ("restaurant",),
    "nha hang": ("restaurant",),
    "ca phe": ("cafe",),
    "cafe": ("cafe",),
    "coffee": ("cafe",),
    "cho": ("market",),
    "mua sam": ("market",),
    "thien nhien": ("park", "attraction"),
    "cong vien": ("park", "attraction"),
    "song nuoc": ("park", "attraction"),
    "check in": ("park", "attraction"),
    "song huong": ("park", "attraction"),
    "phong canh": ("park", "attraction"),
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
