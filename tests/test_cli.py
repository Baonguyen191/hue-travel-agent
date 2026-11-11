import json
from pathlib import Path

import pytest

from tests.data.test_hue_open_data import LANG_B_OSM, make_raw_dir
from tests.data.test_huetripo import make_raw_dir as make_huetripo_raw_dir
from tests.review.conftest import NOW
from travel_agent.cli import main
from travel_agent.data.place_repository import SqlitePlaceRepository
from travel_agent.review.models import ReviewInput, ReviewStatus
from travel_agent.review.store import ReviewStore

FIXTURE = Path(__file__).parent / "fixtures" / "overpass_sample.json"


def test_ingest_then_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "hue.sqlite"
    assert main(["ingest-osm", str(FIXTURE), "--db", str(db)]) == 0
    ingest_out = capsys.readouterr().out
    assert "Đã nạp 3 địa điểm" in ingest_out
    assert "2026-11-03T08:00:00+00:00" in ingest_out
    assert "Có opening_hours: 1/3" in ingest_out
    assert main(["places", "--db", str(db), "--category", "museum"]) == 0
    listed = capsys.readouterr().out
    assert "osm:node/1" in listed
    assert "osm:way/2" not in listed


def test_ingest_hue_open_data_uses_osm_for_missing_coords(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "hue.sqlite"
    raw = make_raw_dir(tmp_path)
    repo = SqlitePlaceRepository(db)
    repo.upsert_many(LANG_B_OSM)
    repo.close()
    assert main(["ingest-hue-open-data", str(raw), "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "Đã nạp 3 điểm tham quan" in out
    assert "Không có tọa độ" in out
    store = ReviewStore(db)
    assert store.sources() == {"data.hue.gov.vn": 3, "osm": 1}
    store.close()


def test_ingest_huetripo_loads_itinerary_places(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "hue.sqlite"
    raw = make_huetripo_raw_dir(tmp_path)
    assert main(["ingest-huetripo", str(raw), "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "Đã nạp 1 địa điểm (nguồn huetripo.hue.gov.vn)" in out
    assert "historic: 1" in out
    assert "Có giờ mở cửa theo nguồn: 1/1" in out
    assert "Có thời gian trải nghiệm TB: 1/1" in out
    assert "Cơ sở lưu trú du lịch / Khách sạn: 1" in out
    store = ReviewStore(db)
    assert store.sources() == {"huetripo.hue.gov.vn": 1}
    store.close()


def test_places_refuses_missing_db(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite"
    assert main(["places", "--db", str(missing)]) == 2
    assert not missing.exists()


def test_export_approved_writes_effective_places(tmp_path: Path) -> None:
    db = tmp_path / "hue.sqlite"
    assert main(["ingest-osm", str(FIXTURE), "--db", str(db)]) == 0
    store = ReviewStore(db)
    store.save(
        ReviewInput(place_id="osm:node/1", status=ReviewStatus.APPROVED, name_override="Mới"), NOW
    )
    store.save(ReviewInput(place_id="osm:way/2", status=ReviewStatus.REJECTED), NOW)
    store.close()
    out = tmp_path / "approved.jsonl"
    assert main(["export-approved", "--db", str(db), "--out", str(out)]) == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["place"]["name"] == "Mới"
    assert record["osm_original"]["name"] == "Bảo tàng Mẫu"
    assert record["review"]["status"] == "approved"
