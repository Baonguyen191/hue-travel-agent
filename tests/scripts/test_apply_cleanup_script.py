"""Test scripts/data/apply_cleanup.py trên DB tạm: dry-run, idempotent, bo/trống, giu:<id>,
audit log, từ chối khi CSV lỗi hoặc DB chỉ đọc, và giữ quyết định khi sinh lại CSV.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from scripts.data import apply_cleanup, suggest_cleanup
from travel_agent.data.cleanup_suggestions import (
    DECISION_FIELD,
    ID_FIELD,
    KIND_CATEGORY,
    KIND_DUPLICATE,
    read_csv_rows,
)
from travel_agent.data.place_repository import SqlitePlaceRepository
from travel_agent.domain.models import Category, Coordinates, Place
from travel_agent.review.models import ReviewedPlace, ReviewInput, ReviewStatus
from travel_agent.review.store import ReviewStore

COLLECTED = dt.datetime(2026, 11, 3, 8, 0, tzinfo=dt.UTC)
DURATION = {"Thời gian trải nghiệm TB (phút)": "60"}
DUP_KEPT = "huetripo:1"  # giữ mặc định: id nhỏ hơn khi số thuộc tính bằng nhau
DUP_DROPPED = "huetripo:2"
BRIDGE = "huetripo:3"


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
        attributes=dict(DURATION),
    )


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


@pytest.fixture
def env(tmp_path: Path) -> tuple[Path, Path, Path]:
    """DB nhỏ có 1 cặp trùng và 1 cầu nằm trong công viên. Trả về (db, out_dir, csv)."""
    db = tmp_path / "hue.sqlite"
    repo = SqlitePlaceRepository(db)
    repo.upsert_many(
        [
            make_place(DUP_KEPT, "Chợ Đông Ba", Category.MARKET),
            make_place(DUP_DROPPED, "Chợ Đông Ba Huế", Category.MARKET, lat=16.471),
            make_place(BRIDGE, "Cầu Trường Tiền", Category.PARK),
        ]
    )
    repo.close()
    out_dir = tmp_path / "reports"
    assert suggest_cleanup.main(["--db", str(db), "--out-dir", str(out_dir)]) == 0
    return db, out_dir, out_dir / suggest_cleanup.CSV_NAME


def set_decisions(csv_path: Path, decisions: dict[tuple[str, str], str]) -> None:
    """Điền decision theo (kind, place_id), như người duyệt làm trong Excel."""
    rows = read_csv_rows(csv_path)
    for row in rows:
        key = (row["kind"], row["place_id"])
        if key in decisions:
            row[DECISION_FIELD] = decisions[key]
    suggest_cleanup.write_csv(csv_path, rows)


def review_of(db: Path, place_id: str) -> ReviewedPlace | None:
    store = ReviewStore(db, read_only=True)
    try:
        return store.get(place_id)
    finally:
        store.close()


def audit_files(out_dir: Path) -> list[Path]:
    return sorted(out_dir.glob("cleanup_applied_*.json"))


def test_dry_run_changes_nothing(env: tuple[Path, Path, Path]) -> None:
    db, out_dir, csv_path = env
    set_decisions(csv_path, {(KIND_DUPLICATE, DUP_DROPPED): "ok", (KIND_CATEGORY, BRIDGE): "ok"})
    before = md5(db)

    code = apply_cleanup.main(["--csv", str(csv_path), "--db", str(db)])

    assert code == apply_cleanup.EXIT_OK
    assert md5(db) == before
    assert audit_files(out_dir) == []


def test_apply_then_reapply_is_idempotent(
    env: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    db, out_dir, csv_path = env
    set_decisions(csv_path, {(KIND_DUPLICATE, DUP_DROPPED): "ok", (KIND_CATEGORY, BRIDGE): "ok"})

    assert apply_cleanup.main(["--csv", str(csv_path), "--db", str(db), "--apply"]) == 0
    after_first = md5(db)
    assert len(audit_files(out_dir)) == 1

    dropped = review_of(db, DUP_DROPPED)
    assert dropped is not None and dropped.status is ReviewStatus.REJECTED
    assert dropped.review is not None and dropped.review.note == f"trùng với {DUP_KEPT}"
    kept = review_of(db, DUP_KEPT)
    assert kept is not None and kept.status is ReviewStatus.PENDING
    bridge = review_of(db, BRIDGE)
    assert bridge is not None
    assert bridge.effective_place().category is Category.VIEWPOINT
    assert bridge.status is ReviewStatus.NEEDS_FIX  # chưa có đánh giá: không tự duyệt

    # Chạy lại: không đổi gì, không tạo audit log mới.
    capsys.readouterr()
    assert apply_cleanup.main(["--csv", str(csv_path), "--db", str(db), "--apply"]) == 0
    assert md5(db) == after_first
    assert len(audit_files(out_dir)) == 1
    assert "Không có thay đổi" in capsys.readouterr().out


def test_bo_and_empty_are_skipped(env: tuple[Path, Path, Path]) -> None:
    db, out_dir, csv_path = env
    set_decisions(csv_path, {(KIND_DUPLICATE, DUP_DROPPED): "bo", (KIND_CATEGORY, BRIDGE): "  "})
    before = md5(db)

    code = apply_cleanup.main(["--csv", str(csv_path), "--db", str(db), "--apply"])

    assert code == apply_cleanup.EXIT_OK
    assert md5(db) == before
    assert audit_files(out_dir) == []


def test_giu_chooses_which_place_to_keep(env: tuple[Path, Path, Path]) -> None:
    db, out_dir, csv_path = env
    # Dòng duplicate có place_id = DUP_DROPPED; giu:<DUP_DROPPED> nghĩa là giữ chính nó.
    set_decisions(csv_path, {(KIND_DUPLICATE, DUP_DROPPED): f"giu:{DUP_DROPPED}"})

    assert apply_cleanup.main(["--csv", str(csv_path), "--db", str(db), "--apply"]) == 0

    kept = review_of(db, DUP_DROPPED)
    assert kept is not None and kept.status is ReviewStatus.PENDING
    loser = review_of(db, DUP_KEPT)
    assert loser is not None and loser.status is ReviewStatus.REJECTED
    assert loser.review is not None and loser.review.note == f"trùng với {DUP_DROPPED}"
    assert len(audit_files(out_dir)) == 1


def test_invalid_decision_refuses_without_writing(env: tuple[Path, Path, Path]) -> None:
    db, out_dir, csv_path = env
    set_decisions(csv_path, {(KIND_DUPLICATE, DUP_DROPPED): "xong"})
    before = md5(db)

    assert apply_cleanup.main(["--csv", str(csv_path), "--db", str(db), "--apply"]) == 2
    assert apply_cleanup.main(["--csv", str(csv_path), "--db", str(db)]) == 2
    assert md5(db) == before
    assert audit_files(out_dir) == []


def test_giu_with_unknown_id_refuses(env: tuple[Path, Path, Path]) -> None:
    db, _, csv_path = env
    set_decisions(csv_path, {(KIND_DUPLICATE, DUP_DROPPED): "giu:huetripo:999"})
    before = md5(db)

    assert apply_cleanup.main(["--csv", str(csv_path), "--db", str(db), "--apply"]) == 2
    assert md5(db) == before


def test_missing_place_refuses(env: tuple[Path, Path, Path]) -> None:
    db, _, csv_path = env
    rows = read_csv_rows(csv_path)
    for row in rows:
        if row["kind"] == KIND_CATEGORY:
            row["place_id"] = "huetripo:999"  # địa điểm đã bị xóa khỏi DB
            row[DECISION_FIELD] = "ok"
    suggest_cleanup.write_csv(csv_path, rows)
    before = md5(db)

    assert apply_cleanup.main(["--csv", str(csv_path), "--db", str(db), "--apply"]) == 2
    assert md5(db) == before


def test_read_only_db_refuses_apply(env: tuple[Path, Path, Path]) -> None:
    db, out_dir, csv_path = env
    set_decisions(csv_path, {(KIND_CATEGORY, BRIDGE): "ok"})
    os.chmod(db, stat.S_IREAD)
    try:
        if os.access(db, os.W_OK):
            pytest.skip("môi trường này bỏ qua quyền chỉ đọc (ví dụ chạy bằng root)")
        assert apply_cleanup.main(["--csv", str(csv_path), "--db", str(db), "--apply"]) == 2
        assert audit_files(out_dir) == []
    finally:
        os.chmod(db, stat.S_IREAD | stat.S_IWRITE)


def test_audit_log_lists_every_change(env: tuple[Path, Path, Path]) -> None:
    db, out_dir, csv_path = env
    set_decisions(csv_path, {(KIND_DUPLICATE, DUP_DROPPED): "ok", (KIND_CATEGORY, BRIDGE): "ok"})
    rows = {row["kind"]: row for row in read_csv_rows(csv_path)}

    assert apply_cleanup.main(["--csv", str(csv_path), "--db", str(db), "--apply"]) == 0

    (log_path,) = audit_files(out_dir)
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    assert payload["count"] == 2
    assert payload["csv"].endswith("cleanup_suggestions.csv")
    by_kind = {change["kind"]: change for change in payload["changes"]}

    dup = by_kind[KIND_DUPLICATE]
    assert dup["action"] == "reject"
    assert dup["place_id"] == DUP_DROPPED
    assert dup["suggestion_id"] == rows[KIND_DUPLICATE][ID_FIELD]
    assert dup["before"]["status"] == "pending"
    assert dup["after"]["status"] == "rejected"
    assert dup["note"] == f"trùng với {DUP_KEPT}"

    cat = by_kind[KIND_CATEGORY]
    assert cat["action"] == "set_category"
    assert cat["place_id"] == BRIDGE
    assert cat["before"]["category"] == "park"
    assert cat["after"]["category"] == "viewpoint"
    assert cat["suggestion_id"] == rows[KIND_CATEGORY][ID_FIELD]


def test_regeneration_keeps_decisions(env: tuple[Path, Path, Path]) -> None:
    db, out_dir, csv_path = env
    set_decisions(csv_path, {(KIND_DUPLICATE, DUP_DROPPED): "giu:" + DUP_KEPT})
    old_id = {row["kind"]: row[ID_FIELD] for row in read_csv_rows(csv_path)}

    # Sinh lại từ cùng DB: quyết định phải còn nguyên, đúng dòng (theo suggestion_id).
    assert suggest_cleanup.main(["--db", str(db), "--out-dir", str(out_dir)]) == 0
    rows = read_csv_rows(csv_path)
    dup = next(row for row in rows if row["kind"] == KIND_DUPLICATE)
    assert dup[ID_FIELD] == old_id[KIND_DUPLICATE]
    assert dup[DECISION_FIELD] == "giu:" + DUP_KEPT
    cat = next(row for row in rows if row["kind"] == KIND_CATEGORY)
    assert cat[DECISION_FIELD] == ""


def test_regeneration_keeps_orphan_decisions(env: tuple[Path, Path, Path]) -> None:
    db, out_dir, csv_path = env
    rows = read_csv_rows(csv_path)
    rows.append({**rows[0], ID_FIELD: "0123456789abcdef", DECISION_FIELD: "ok", "reason": "cũ"})
    suggest_cleanup.write_csv(csv_path, rows)

    assert suggest_cleanup.main(["--db", str(db), "--out-dir", str(out_dir)]) == 0

    kept = [row for row in read_csv_rows(csv_path) if row[ID_FIELD] == "0123456789abcdef"]
    assert len(kept) == 1
    assert kept[0][DECISION_FIELD] == "ok"
    assert kept[0]["reason"].startswith("[không còn trong lần sinh mới]")


def test_existing_note_is_kept_when_rejecting(env: tuple[Path, Path, Path]) -> None:
    """Ghi chú sẵn có của người duyệt không bị mất khi loại trùng: nối thêm, không ghi đè."""
    db, _, csv_path = env
    store = ReviewStore(db)
    store.save(
        ReviewInput(place_id=DUP_DROPPED, status=ReviewStatus.APPROVED, note="đã kiểm tra"),
        dt.datetime(2026, 11, 4, tzinfo=dt.UTC),
    )
    store.close()
    set_decisions(csv_path, {(KIND_DUPLICATE, DUP_DROPPED): "ok"})

    assert apply_cleanup.main(["--csv", str(csv_path), "--db", str(db), "--apply"]) == 0

    dropped = review_of(db, DUP_DROPPED)
    assert dropped is not None and dropped.review is not None
    assert dropped.status is ReviewStatus.REJECTED
    assert dropped.review.note == f"đã kiểm tra | trùng với {DUP_KEPT}"
