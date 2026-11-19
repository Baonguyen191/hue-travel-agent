"""Test scripts/data/suggest_cleanup.py: ghi CSV có BOM, tóm tắt, và đường đọc DB chỉ đọc."""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

import pytest

from scripts.data import suggest_cleanup
from travel_agent.data.cleanup_suggestions import CSV_FIELDS, KIND_DUPLICATE, Suggestion
from travel_agent.data.place_repository import SqlitePlaceRepository
from travel_agent.domain.models import Category, Coordinates, Place
from travel_agent.review.models import ReviewInput, ReviewStatus
from travel_agent.review.store import ReviewStore

COLLECTED = dt.datetime(2026, 11, 3, 8, 0, tzinfo=dt.UTC)


def make_place(pid: str, name: str, category: Category, lat: float = 16.47) -> Place:
    return Place(
        id=pid,
        name=name,
        category=category,
        coords=Coordinates(lat=lat, lon=107.58),
        opening_hours_raw="07:30-17:30",
        source="huetripo.hue.gov.vn",
        source_place_id=pid.removeprefix("huetripo:"),
        license="test",
        collected_at=COLLECTED,
        attributes={"Thời gian trải nghiệm TB (phút)": "60"},
    )


def test_write_csv_has_bom_header_and_vietnamese_text(tmp_path: Path) -> None:
    path = tmp_path / "out.csv"
    row = Suggestion(
        kind=KIND_DUPLICATE,
        place_id="huetripo:1",
        name="Chợ Đông Ba Huế",
        category="market",
        status="pending",
        other_place_id="huetripo:2",
        suggested_action="gộp: giữ huetripo:2",
    )
    suggest_cleanup.write_csv(path, [row])

    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0].keys()) == list(CSV_FIELDS)
    assert rows[0]["name"] == "Chợ Đông Ba Huế"
    assert rows[0]["suggested_action"] == "gộp: giữ huetripo:2"


def test_main_returns_error_when_db_missing(tmp_path: Path) -> None:
    code = suggest_cleanup.main(
        ["--db", str(tmp_path / "missing.sqlite"), "--out-dir", str(tmp_path)]
    )
    assert code == suggest_cleanup.EXIT_ERROR
    assert not (tmp_path / suggest_cleanup.CSV_NAME).exists()


def test_main_reads_db_read_only_and_skips_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "hue.sqlite"
    repo = SqlitePlaceRepository(db)
    repo.upsert_many(
        [
            make_place("huetripo:1", "Chợ Đông Ba", Category.MARKET),
            make_place("huetripo:2", "Chợ Đông Ba Huế", Category.MARKET, lat=16.471),
            make_place("huetripo:3", "Cầu Trường Tiền", Category.PARK),
        ]
    )
    repo.close()
    # Loại huetripo:2 bằng review; sau đó nó không được xét và không tạo cặp trùng.
    store = ReviewStore(db)
    store.save(
        ReviewInput(place_id="huetripo:2", status=ReviewStatus.REJECTED),
        dt.datetime(2026, 11, 4, tzinfo=dt.UTC),
    )
    store.close()
    before = db.read_bytes()

    out_dir = tmp_path / "reports"
    code = suggest_cleanup.main(["--db", str(db), "--out-dir", str(out_dir), "--top", "5"])

    assert code == suggest_cleanup.EXIT_OK
    assert db.read_bytes() == before  # DB không bị đổi byte
    assert "Địa điểm xét: 2" in capsys.readouterr().out
    with (out_dir / suggest_cleanup.CSV_NAME).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    kinds = [row["kind"] for row in rows]
    assert KIND_DUPLICATE not in kinds
    assert "category" in kinds
    md = (out_dir / suggest_cleanup.MD_NAME).read_text(encoding="utf-8")
    assert "Địa điểm xét (đã bỏ loại REJECTED): 2." in md
    assert "chỉ đọc" in md
