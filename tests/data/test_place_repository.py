import datetime as dt
import sqlite3
from pathlib import Path

from travel_agent.data.place_repository import SqlitePlaceRepository
from travel_agent.domain.models import Category, Coordinates, Place

COLLECTED = dt.datetime(2026, 11, 3, 8, 0, tzinfo=dt.UTC)


def make_place(pid: str, category: Category, name: str = "Mẫu", hours: str | None = None) -> Place:
    return Place(
        id=pid,
        name=name,
        category=category,
        coords=Coordinates(lat=16.47, lon=107.58),
        opening_hours_raw=hours,
        source="osm",
        source_place_id=pid.removeprefix("osm:"),
        license="ODbL-1.0",
        collected_at=COLLECTED,
    )


def test_roundtrip(tmp_path: Path) -> None:
    repo = SqlitePlaceRepository(tmp_path / "places.sqlite")
    original = make_place("osm:node/1", Category.MUSEUM, hours="Mo-Su 07:00-17:00")
    repo.upsert_many([original])
    assert repo.get("osm:node/1") == original
    assert repo.get("osm:node/404") is None
    repo.close()


def test_attributes_roundtrip_and_source_filter(tmp_path: Path) -> None:
    repo = SqlitePlaceRepository(tmp_path / "places.sqlite")
    official = make_place("hueod:a", Category.HISTORIC).model_copy(
        update={"source": "data.hue.gov.vn", "attributes": {"Giá vé": "Người lớn: 200.000đ"}}
    )
    repo.upsert_many([official, make_place("osm:node/1", Category.CAFE)])
    assert repo.get("hueod:a") == official
    assert [p.id for p in repo.list_places(source="data.hue.gov.vn")] == ["hueod:a"]
    assert repo.count_by_category(source="osm") == {Category.CAFE: 1}
    repo.close()


def test_old_database_without_attributes_column_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE places (id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, "
        "lat REAL NOT NULL, lon REAL NOT NULL, opening_hours_raw TEXT, source TEXT NOT NULL, "
        "source_place_id TEXT NOT NULL, license TEXT NOT NULL, collected_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO places VALUES ('osm:node/1', 'Cũ', 'cafe', 16.47, 107.58, NULL, 'osm', "
        "'node/1', 'ODbL-1.0', '2026-11-03T08:00:00+00:00')"
    )
    conn.commit()
    conn.close()
    repo = SqlitePlaceRepository(path)
    place = repo.get("osm:node/1")
    assert place is not None
    assert place.attributes == {}
    repo.close()


def test_upsert_updates_existing(tmp_path: Path) -> None:
    repo = SqlitePlaceRepository(tmp_path / "places.sqlite")
    repo.upsert_many([make_place("osm:node/1", Category.MUSEUM, name="Cũ")])
    repo.upsert_many([make_place("osm:node/1", Category.MUSEUM, name="Mới")])
    place = repo.get("osm:node/1")
    assert place is not None
    assert place.name == "Mới"
    repo.close()


def test_list_filters_by_category_sorted_by_name_and_counts(tmp_path: Path) -> None:
    repo = SqlitePlaceRepository(tmp_path / "places.sqlite")
    repo.upsert_many(
        [
            make_place("osm:node/1", Category.CAFE, name="B"),
            make_place("osm:node/2", Category.CAFE, name="A"),
            make_place("osm:node/3", Category.MUSEUM),
        ]
    )
    assert [p.id for p in repo.list_places(Category.CAFE)] == ["osm:node/2", "osm:node/1"]
    assert repo.count_by_category() == {Category.CAFE: 2, Category.MUSEUM: 1}
    repo.close()
