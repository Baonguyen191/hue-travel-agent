"""Áp dụng quyết định trong cột `decision` của CSV gợi ý dọn dữ liệu Huế.

    .venv/Scripts/python.exe scripts/data/apply_cleanup.py            (dry-run, mặc định)
    .venv/Scripts/python.exe scripts/data/apply_cleanup.py --apply    (ghi thật)
    Mặc định: --csv reports/data/cleanup_suggestions.csv --db data/hue.sqlite

Mặc định là dry-run: chỉ đọc DB (mode=ro) và in đúng những thay đổi sẽ xảy ra, không ghi gì.
Có `--apply` thì ghi qua `ReviewStore.save` (không SQL trực tiếp lên bảng):
- duplicate, `ok` hoặc `giu:<id>`: bản bị bỏ chuyển sang REJECTED, ghi chú "trùng với <id giữ>".
- category, `ok`: đặt category_override = suggested_category. Địa điểm chưa có đánh giá thì đặt
  NEEDS_FIX (chưa duyệt, không lọt vào export-approved).
- missing_data: chỉ là thông tin, không đổi gì. `bo` và ô trống: bỏ qua.

Chạy lại không đổi thêm gì (idempotent). Mỗi lần có thay đổi, ghi audit log JSON cạnh CSV.
Gặp lỗi (decision sai, place không còn trong DB, xung đột giữa các dòng) thì dừng ngay với mã 2,
không ghi gì, kể cả khi dry-run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from travel_agent.data.cleanup_suggestions import (
    DECISION_FIELD,
    DECISION_KEEP,
    DECISION_OK,
    KIND_CATEGORY,
    KIND_DUPLICATE,
    KIND_MISSING,
    Decision,
    parse_decision,
    read_csv_rows,
)
from travel_agent.domain.models import Category
from travel_agent.review.models import ReviewedPlace, ReviewInput, ReviewStatus
from travel_agent.review.store import ReviewStore

DEFAULT_CSV = Path("reports/data/cleanup_suggestions.csv")
DEFAULT_DB = Path("data/hue.sqlite")
EXIT_OK = 0
EXIT_REFUSED = 2  # CSV lỗi hoặc DB không ghi được: không ghi gì

ACTION_REJECT = "reject"
ACTION_CATEGORY = "set_category"
NOTE_DUPLICATE = "trùng với {kept}"
NOTE_CATEGORY = "đổi loại theo cleanup: {reason}"


@dataclass(frozen=True)
class Intent:
    """Một quyết định đã hiểu được, chưa đối chiếu với DB."""

    suggestion_id: str
    line_no: int
    kind: str
    action: str  # ACTION_REJECT hoặc ACTION_CATEGORY
    place_id: str
    target: str  # bản giữ (reject) hoặc loại mới (category)
    reason: str


@dataclass(frozen=True)
class Change:
    suggestion_id: str
    kind: str
    action: str
    place_id: str
    place_name: str
    before: Mapping[str, str | None]
    after: Mapping[str, str | None]
    review: ReviewInput

    def as_log(self) -> dict[str, Any]:
        return {
            "suggestion_id": self.suggestion_id,
            "kind": self.kind,
            "action": self.action,
            "place_id": self.place_id,
            "place_name": self.place_name,
            "before": dict(self.before),
            "after": dict(self.after),
            "note": self.review.note,
        }


@dataclass(frozen=True)
class Skip:
    suggestion_id: str
    place_id: str
    reason: str


@dataclass
class Plan:
    changes: list[Change] = field(default_factory=list)
    skipped: list[Skip] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    undecided: int = 0


def _snapshot(item: ReviewedPlace) -> dict[str, str | None]:
    return {
        "status": item.status.value,
        "category": item.effective_place().category.value,
        "note": None if item.review is None else item.review.note,
    }


def _carry(item: ReviewedPlace) -> dict[str, Any]:
    """Giữ nguyên các trường đã có khi ghi lại đánh giá (save luôn ghi đủ mọi cột)."""
    review = item.review
    if review is None:
        return {}
    return {
        "name_override": review.name_override,
        "category_override": review.category_override,
        "opening_hours_override": review.opening_hours_override,
        "evidence": review.evidence,
        "note": review.note,
    }


def _duplicate_choice(row: Mapping[str, str], decision: Decision) -> tuple[str, str]:
    """Trả về (bản giữ, bản bỏ) của một dòng duplicate. Ném ValueError nếu giu: sai id."""
    place_id = row["place_id"]
    other = row.get("other_place_id", "")
    if decision.action == DECISION_OK:
        # Mặc định của gợi ý: giữ other_place_id, bỏ place_id.
        return other, place_id
    if decision.keep_id == place_id:
        return place_id, other
    if decision.keep_id == other:
        return other, place_id
    raise ValueError(
        f"giu:{decision.keep_id} không khớp place_id ({place_id}) hay "
        f"other_place_id ({other}) của dòng này"
    )


def _intent(line_no: int, row: Mapping[str, str], decision: Decision) -> Intent | Skip | str:
    """Trả về Intent (sẽ thực hiện), Skip (bỏ qua có lý do) hoặc chuỗi lỗi."""
    sid = row.get("suggestion_id", "")
    place_id = row["place_id"]
    kind = row.get("kind", "")
    if decision.action == DECISION_KEEP and kind != KIND_DUPLICATE:
        return f"dòng {line_no}: giu:<id> chỉ dùng cho dòng duplicate"
    if decision.action == "bo":
        return Skip(sid, place_id, "bo: bỏ qua")
    if kind == KIND_MISSING:
        return Skip(sid, place_id, "missing_data chỉ là thông tin, không đổi gì")
    if kind == KIND_DUPLICATE:
        try:
            kept, dropped = _duplicate_choice(row, decision)
        except ValueError as exc:
            return f"dòng {line_no}: {exc}"
        return Intent(sid, line_no, kind, ACTION_REJECT, dropped, kept, row.get("reason", ""))
    if kind == KIND_CATEGORY:
        target = row.get("suggested_category", "")
        if not target:
            return Skip(sid, place_id, "không có loại để đổi (cần người duyệt quyết định)")
        return Intent(sid, line_no, kind, ACTION_CATEGORY, place_id, target, row.get("reason", ""))
    return f"dòng {line_no}: kind không rõ {kind!r}"


def build_plan(rows: Sequence[Mapping[str, str]], store: ReviewStore) -> Plan:
    """Đối chiếu CSV với DB (đọc qua `store`) và tạo kế hoạch. Không ghi gì."""
    plan = Plan()
    intents: list[Intent] = []

    for line_no, row in enumerate(rows, start=2):  # dòng 1 là tiêu đề
        place_id = row.get("place_id", "")
        if store.get(place_id) is None:
            plan.errors.append(f"dòng {line_no}: place {place_id} không còn trong DB; hãy sinh lại")
            continue
        if row.get("kind") == KIND_DUPLICATE and store.get(row.get("other_place_id", "")) is None:
            plan.errors.append(
                f"dòng {line_no}: other_place {row.get('other_place_id')} không còn trong DB; "
                "hãy sinh lại"
            )
            continue
        try:
            decision = parse_decision(row.get(DECISION_FIELD))
        except ValueError as exc:
            plan.errors.append(f"dòng {line_no}: {exc}")
            continue
        if not decision.action:
            plan.undecided += 1
            continue
        result = _intent(line_no, row, decision)
        if isinstance(result, str):
            plan.errors.append(result)
        elif isinstance(result, Skip):
            plan.skipped.append(result)
        else:
            intents.append(result)

    # Xung đột: một địa điểm vừa là bản giữ vừa là bản bỏ, hoặc bản giữ đã bị loại.
    dropped_ids = {i.place_id for i in intents if i.action == ACTION_REJECT}
    kept_ids = {i.target for i in intents if i.action == ACTION_REJECT}
    for pid in sorted(dropped_ids & kept_ids):
        plan.errors.append(f"xung đột: {pid} vừa được giữ vừa bị loại trong các dòng khác")
    for pid in sorted(kept_ids):
        current = store.get(pid)
        if current is not None and current.status is ReviewStatus.REJECTED:
            plan.errors.append(f"bản giữ {pid} đang bị loại (REJECTED); xem lại trước khi áp")

    # Một địa điểm chỉ được đổi loại sang một giá trị trong cùng một lần chạy.
    category_targets: dict[str, str] = {}
    for intent in intents:
        if intent.action != ACTION_CATEGORY:
            continue
        seen = category_targets.setdefault(intent.place_id, intent.target)
        if seen != intent.target:
            plan.errors.append(
                f"xung đột: {intent.place_id} được gợi ý đổi sang {seen} và {intent.target}"
            )
    if plan.errors:
        return plan

    planned: set[tuple[str, str]] = set()
    for intent in intents:
        current = store.get(intent.place_id)
        if current is None:  # đã kiểm tra ở trên; để mypy hiểu
            continue
        key = (intent.action, intent.place_id)
        before = _snapshot(current)
        if intent.action == ACTION_REJECT:
            if current.status is ReviewStatus.REJECTED:
                plan.skipped.append(Skip(intent.suggestion_id, intent.place_id, "đã loại trước đó"))
                continue
            if key in planned:
                plan.skipped.append(
                    Skip(intent.suggestion_id, intent.place_id, "đã có trong kế hoạch")
                )
                continue
            note = NOTE_DUPLICATE.format(kept=intent.target)
            if current.review is not None and current.review.note:
                note = note if note in current.review.note else f"{current.review.note} | {note}"
            review = ReviewInput(
                **{
                    **_carry(current),
                    "place_id": intent.place_id,
                    "status": ReviewStatus.REJECTED,
                    "note": note,
                }
            )
            after = {**before, "status": ReviewStatus.REJECTED.value, "note": note}
        else:
            target = Category(intent.target)
            if current.effective_place().category is target:
                plan.skipped.append(Skip(intent.suggestion_id, intent.place_id, "đã đúng loại"))
                continue
            if key in planned:
                plan.skipped.append(
                    Skip(intent.suggestion_id, intent.place_id, "đã có trong kế hoạch")
                )
                continue
            status = current.status if current.review is not None else ReviewStatus.NEEDS_FIX
            note = (
                current.review.note
                if current.review is not None
                else NOTE_CATEGORY.format(reason=intent.reason)
            )
            review = ReviewInput(
                **{
                    **_carry(current),
                    "place_id": intent.place_id,
                    "status": status,
                    "category_override": target,
                    "note": note,
                }
            )
            after = {**before, "status": status.value, "category": target.value}
        planned.add(key)
        plan.changes.append(
            Change(
                suggestion_id=intent.suggestion_id,
                kind=intent.kind,
                action=intent.action,
                place_id=intent.place_id,
                place_name=current.effective_place().name,
                before=before,
                after=after,
                review=review,
            )
        )
    return plan


def _describe(change: Change) -> str:
    label = "loại (REJECTED)" if change.action == ACTION_REJECT else "đổi loại"
    before = " ".join(f"{k}={v}" for k, v in change.before.items() if k != "note")
    after = " ".join(f"{k}={v}" for k, v in change.after.items() if k != "note")
    head = f"  {label}: {change.place_id} ({change.place_name})"
    return f"{head}\n      trước: {before}\n      sau:   {after}"


def print_plan(plan: Plan) -> None:
    for error in plan.errors:
        print(f"LỖI {error}", file=sys.stderr)
    for change in plan.changes:
        print(_describe(change))
    for skip in plan.skipped:
        print(f"  bỏ qua: {skip.place_id} ({skip.suggestion_id}): {skip.reason}")
    print(
        f"Tổng thay đổi: {len(plan.changes)}; bỏ qua: {len(plan.skipped)}; "
        f"chưa quyết định: {plan.undecided}; lỗi: {len(plan.errors)}"
    )


def write_audit(csv_path: Path, db: Path, applied: Sequence[Change]) -> Path:
    now = dt.datetime.now(dt.UTC)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    path = csv_path.parent / f"cleanup_applied_{stamp}.json"
    payload = {
        "applied_at": now.isoformat(),
        "csv": csv_path.as_posix(),
        "db": db.as_posix(),
        "count": len(applied),
        "changes": [change.as_log() for change in applied],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def check_writable(db: Path) -> str | None:
    """Trả về lý do không ghi được, hoặc None nếu ghi được."""
    if not os.access(db, os.W_OK):
        return f"DB không ghi được (file chỉ đọc?): {db}"
    # Không dùng ReviewStore để thử: mở ở chế độ ghi sẽ tạo bảng place_reviews và đổi file.
    # BEGIN IMMEDIATE xin khóa ghi rồi rollback, không ghi gì và thất bại nếu không ghi được.
    try:
        conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=rw", uri=True)
    except sqlite3.Error as exc:
        return f"không mở được DB để ghi: {exc}"
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.rollback()
    except sqlite3.Error as exc:
        return f"DB không ghi được: {exc}"
    finally:
        conn.close()
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Áp dụng quyết định trong CSV gợi ý dọn dữ liệu.")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true", help="ghi thật; mặc định chỉ dry-run")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.csv.exists():
        print(f"Không tìm thấy CSV: {args.csv}", file=sys.stderr)
        return EXIT_REFUSED
    if not args.db.exists():
        print(f"Không tìm thấy DB: {args.db}", file=sys.stderr)
        return EXIT_REFUSED
    rows = read_csv_rows(args.csv)
    if rows and DECISION_FIELD not in rows[0]:
        print(f"CSV thiếu cột {DECISION_FIELD}: {args.csv}", file=sys.stderr)
        return EXIT_REFUSED
    if args.apply:
        reason = check_writable(args.db)
        if reason is not None:
            print(f"Từ chối --apply: {reason}", file=sys.stderr)
            return EXIT_REFUSED

    reader = ReviewStore(args.db, read_only=True)
    try:
        plan = build_plan(rows, reader)
    finally:
        reader.close()

    print_plan(plan)
    if plan.errors:
        print(
            "Dừng: CSV có lỗi, không ghi gì. Sửa cột decision hoặc sinh lại gợi ý.", file=sys.stderr
        )
        return EXIT_REFUSED
    if not args.apply:
        print("Dry-run: chưa ghi gì. Chạy lại với --apply để áp dụng.")
        return EXIT_OK
    if not plan.changes:
        print("Không có thay đổi nào (đã áp dụng trước đó hoặc chưa có quyết định).")
        return EXIT_OK

    applied: list[Change] = []
    store = ReviewStore(args.db)
    try:
        for change in plan.changes:
            store.save(change.review, dt.datetime.now(dt.UTC))
            applied.append(change)
    finally:
        store.close()
        # Ghi log kể cả khi lỗi giữa chừng, để biết đã đổi những gì.
        if applied:
            log_path = write_audit(args.csv, args.db, applied)
            print(f"Audit log: {log_path}")
    print(f"Đã áp {len(applied)} thay đổi.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
