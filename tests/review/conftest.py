import datetime as dt
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from travel_agent.data.osm import places_from_overpass
from travel_agent.data.place_repository import SqlitePlaceRepository
from travel_agent.review.store import ReviewStore

FIXTURE = Path(__file__).parent.parent / "fixtures" / "overpass_sample.json"
NOW = dt.datetime(2026, 11, 3, 9, 0, tzinfo=dt.UTC)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """DB có 3 địa điểm giả từ fixture: osm:node/1 (museum), osm:way/2 (cafe), osm:node/6."""
    path = tmp_path / "hue.sqlite"
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    repo = SqlitePlaceRepository(path)
    repo.upsert_many(places_from_overpass(payload, NOW))
    repo.close()
    return path


@pytest.fixture
def store(db_path: Path) -> Iterator[ReviewStore]:
    review_store = ReviewStore(db_path)
    yield review_store
    review_store.close()
