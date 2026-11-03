import datetime as dt
import json
from pathlib import Path

from travel_agent.data.osm import build_overpass_query, category_from_tags, places_from_overpass
from travel_agent.domain.models import Category, Place

FIXTURE = Path(__file__).parent.parent / "fixtures" / "overpass_sample.json"
COLLECTED = dt.datetime(2026, 11, 3, tzinfo=dt.UTC)


def load_places() -> list[Place]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return places_from_overpass(payload, COLLECTED)


def test_keeps_only_named_categorised_elements_with_position() -> None:
    assert sorted(p.id for p in load_places()) == ["osm:node/1", "osm:node/6", "osm:way/2"]


def test_maps_fields_and_provenance() -> None:
    museum = next(p for p in load_places() if p.id == "osm:node/1")
    assert museum.category is Category.MUSEUM
    assert museum.opening_hours_raw == "Mo-Su 07:00-17:00"
    assert museum.source == "osm"
    assert museum.source_place_id == "node/1"
    assert museum.license == "ODbL-1.0"
    assert museum.collected_at == COLLECTED


def test_way_uses_center_and_name_is_trimmed() -> None:
    places = {p.id: p for p in load_places()}
    assert places["osm:way/2"].coords.lat == 16.46
    assert places["osm:node/6"].name == "Quán Mẫu"
    assert places["osm:node/6"].opening_hours_raw is None


def test_category_priority() -> None:
    religious = category_from_tags({"amenity": "place_of_worship", "historic": "yes"})
    assert religious is Category.RELIGIOUS
    assert category_from_tags({"tourism": "attraction", "historic": "tomb"}) is Category.HISTORIC
    assert category_from_tags({"shop": "convenience"}) is None


def test_query_contains_bbox_and_center_output() -> None:
    query = build_overpass_query((16.36, 107.5, 16.58, 107.7))
    assert "(16.36,107.5,16.58,107.7)" in query
    assert "out center tags;" in query
