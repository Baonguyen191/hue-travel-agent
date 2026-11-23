"""Which photo a place shows: its source photo, a curated Commons photo, or a category stand-in."""

from __future__ import annotations

import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.chat.cards import place_card  # noqa: E402
from app.core.config import hue_database_path  # noqa: E402
from app.repositories.hue_places import HuePlacesRepository  # noqa: E402
from app.schemas.place import Place  # noqa: E402
from app.services.photo_fallbacks import load_fallbacks, resolve_photo  # noqa: E402
from app.services.photos import allowed_source  # noqa: E402

SOURCE = "https://huetripo.hue.gov.vn/uploads/a.jpg"
FALLBACK_CATEGORIES = ("restaurant", "cafe", "market", "historic", "religious")


def rule_photos(category: str, keyword: str | None) -> set[str]:
    """URLs of the category rule whose keywords are exactly `keyword` (None = the default rule)."""
    for rule in load_fallbacks()["categories"][category]:
        if (keyword is None and not rule["keywords"]) or rule["keywords"] == [keyword]:
            return {photo["url"] for photo in rule["photos"]}
    raise AssertionError(f"no rule {category}/{keyword}")


def historic_rule_urls(keywords: tuple[str, ...]) -> set[str]:
    for rule in load_fallbacks()["categories"]["historic"]:
        if tuple(rule["keywords"]) == keywords:
            return {photo["url"] for photo in rule["photos"]}
    raise AssertionError(f"no historic rule {keywords}")


def make_place(poi_id: str, name: str, category: str, photo_url: str | None, photo) -> Place:
    return Place.model_validate(
        {
            "id": poi_id,
            "name": name,
            "category": category,
            "lat": 16.46,
            "lon": 107.56,
            "opening_hours_confidence": "UNKNOWN",
            "price_status": "UNKNOWN",
            "source": "huetripo",
            "source_place_id": poi_id.split(":")[1],
            "collected_at": datetime(2026, 11, 1, tzinfo=timezone.utc),
            "photo_url": photo_url,
            "photo": photo,
            "raw_attributes": {},
        }
    )


def test_source_photo_on_huetripo_resolves_to_source_kind() -> None:
    photo = resolve_photo("huetripo:1", "Đại Nội Huế", "historic", SOURCE)
    assert photo is not None
    assert photo.kind == "source"
    assert photo.url == SOURCE
    assert photo.author is None
    assert photo.license is None
    assert photo.credit_url is None


def test_place_with_curated_commons_photo_gets_credit_fields() -> None:
    photo = resolve_photo("huetripo:544139", "Điện Voi Ré", "historic", None)
    assert photo is not None
    assert photo.kind == "commons_place"
    assert photo.author == "Christophe95"
    assert photo.license == "CC BY-SA 4.0"
    assert photo.credit_url == load_fallbacks()["places"]["huetripo:544139"]["page_url"]
    assert photo.credit_url.startswith("https://commons.wikimedia.org/wiki/File:")


def test_restaurant_without_photo_gets_a_deterministic_illustrative_photo() -> None:
    first = resolve_photo("huetripo:r1", "Bún bò Huế Cô Hương", "restaurant", None)
    second = resolve_photo("huetripo:r1", "Bún bò Huế Cô Hương", "restaurant", None)
    assert first is not None and second is not None
    assert first.kind == "commons_illustrative"
    assert first.url == second.url
    assert first.url in rule_photos("restaurant", None)
    assert first.credit_url is not None


def test_historic_keyword_rules_pick_their_own_photos() -> None:
    dinh = resolve_photo("huetripo:h1", "Đình làng An Cựu", "historic", None)
    assert dinh is not None and dinh.url in historic_rule_urls(("đình",))

    tomb = resolve_photo("huetripo:h2", "Lăng mộ Đặng Huy Trứ", "historic", None)
    assert tomb is not None and tomb.url in historic_rule_urls(("lăng", "tẩm", "mộ"))

    default = resolve_photo("huetripo:h3", "Trụ sở Xứ ủy Trung Kỳ", "historic", None)
    assert default is not None and default.url in rule_photos("historic", None)

    tunnel = resolve_photo("huetripo:h4", "Địa đạo Xuân Lộc", "historic", None)
    assert tunnel is not None and tunnel.url in historic_rule_urls(("địa đạo",))


def test_every_place_in_the_hue_database_gets_a_photo() -> None:
    database = hue_database_path()
    if not database.is_file():
        pytest.skip(f"Hue SQLite source is missing: {database}")
    places = HuePlacesRepository(database).list_all()
    checked = [place for place in places if place.category in FALLBACK_CATEGORIES]
    assert checked
    missing = [place.id for place in checked if place.photo is None]
    assert missing == []


@pytest.mark.parametrize(
    "url",
    [
        "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/a/a.jpg",
    ],
)
def test_allowed_source_accepts_wikimedia_https(url: str) -> None:
    assert allowed_source(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://upload.wikimedia.org/wikipedia/commons/a/a.jpg",
        "https://wikimedia.org.evil.example/a.jpg",
    ],
)
def test_allowed_source_rejects_insecure_and_lookalike_hosts(url: str) -> None:
    assert not allowed_source(url)


def test_place_card_flags_illustrative_photos_only() -> None:
    illustrative = resolve_photo("huetripo:r2", "Cà phê A", "cafe", None)
    source = resolve_photo("huetripo:c1", "Cà phê B", "cafe", SOURCE)
    assert place_card(make_place("huetripo:r2", "Cà phê A", "cafe", None, illustrative)).photo_illustrative is True
    assert place_card(make_place("huetripo:c1", "Cà phê B", "cafe", SOURCE, source)).photo_illustrative is False


FREE_LICENSE = re.compile(r"^(CC0|CC BY(-SA)? \d\.\d|Public domain)$", re.IGNORECASE)


def all_fallback_photos() -> list[dict]:
    data = load_fallbacks()
    photos = list(data["places"].values())
    for rules in data["categories"].values():
        for rule in rules:
            photos.extend(rule["photos"])
    return photos


def test_banh_canh_restaurant_gets_a_banh_canh_photo() -> None:
    photo = resolve_photo("huetripo:bc1", "Bánh canh cua Vui", "restaurant", None)
    assert photo is not None and photo.kind == "commons_illustrative"
    assert photo.url in rule_photos("restaurant", "bánh canh")


def test_hen_rice_restaurant_gets_a_hen_photo() -> None:
    photo = resolve_photo("huetripo:hr1", "Quán cơm hến Chi", "restaurant", None)
    assert photo is not None and photo.url in rule_photos("restaurant", "hến")


def test_lang_historic_site_without_curated_photo_uses_tomb_rule() -> None:
    photo = resolve_photo("huetripo:lm1", "Lăng mộ Nguyễn Cư Trinh", "historic", None)
    assert photo is not None and photo.url in historic_rule_urls(("lăng", "tẩm", "mộ"))


def test_lac_tinh_vien_keeps_an_illustrative_photo() -> None:
    # The only Commons candidate is an archive portrait of a family; it does not show the house.
    photo = resolve_photo("huetripo:658476", "Nhà vườn Lạc Tịnh Viên", "historic", None)
    assert photo is not None
    assert photo.kind == "commons_illustrative"


def test_every_fallback_photo_has_a_free_license_and_an_author() -> None:
    photos = all_fallback_photos()
    assert photos
    for photo in photos:
        assert FREE_LICENSE.match(photo["license"]), photo
        assert photo["author"].strip(), photo
        assert photo["page_url"].startswith("https://commons.wikimedia.org/wiki/File:"), photo


def test_illustrative_photo_reuse_is_capped_over_the_hue_database() -> None:
    database = hue_database_path()
    if not database.is_file():
        pytest.skip(f"Hue SQLite source is missing: {database}")
    places = HuePlacesRepository(database).list_all()
    reuse = Counter(
        place.photo.url for place in places if place.photo is not None and place.photo.kind == "commons_illustrative"
    )
    assert reuse
    assert max(reuse.values()) <= 8
