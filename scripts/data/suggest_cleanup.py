"""Tạo danh sách gợi ý dọn dữ liệu Huế để người duyệt xác nhận.

    .venv/Scripts/python.exe scripts/data/suggest_cleanup.py
    .venv/Scripts/python.exe scripts/data/suggest_cleanup.py \
        --db data/hue.sqlite --out-dir reports/data

Chỉ ĐỌC DB (mở ở chế độ `mode=ro`, file DB là dependency của DVC). Ghi hai file vào --out-dir:
- cleanup_suggestions.csv: mỗi dòng một gợi ý, UTF-8 có BOM để mở bằng Excel. Cột `decision`
  người duyệt điền (ok / bo / giu:<place_id>). Khi sinh lại, quyết định đã điền được giữ theo
  `suggestion_id`, không bị mất.
- cleanup_suggestions.md: tóm tắt số lượng, quy tắc và cách điền `decision`.
Địa điểm đã bị loại (rejected) không được xét lại. Đề xuất không tự sửa gì trong DB.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

from travel_agent.data.cleanup_suggestions import (
    CATEGORY_RULES,
    CSV_FIELDS,
    DECISION_FIELD,
    KIND_CATEGORY,
    KIND_DUPLICATE,
    KIND_MISSING,
    KIND_ORDER,
    TOP_POPULAR,
    Suggestion,
    build_suggestions,
    count_by_kind,
    merge_with_previous,
    read_csv_rows,
)
from travel_agent.domain.models import Place
from travel_agent.review.models import ReviewStatus
from travel_agent.review.store import ReviewStore

DEFAULT_DB = Path("data/hue.sqlite")
DEFAULT_OUT_DIR = Path("reports/data")
CSV_NAME = "cleanup_suggestions.csv"
MD_NAME = "cleanup_suggestions.md"

EXIT_OK = 0
EXIT_ERROR = 1


def load_active(db: Path) -> tuple[list[Place], dict[str, str]]:
    """Địa điểm đã áp override, bỏ loại REJECTED, kèm trạng thái duyệt theo id."""
    store = ReviewStore(db, read_only=True)
    try:
        items, _ = store.query(limit=-1)  # LIMIT -1 = không giới hạn
    finally:
        store.close()
    active = [item for item in items if item.status is not ReviewStatus.REJECTED]
    places = [item.effective_place() for item in active]
    statuses = {item.place.id: item.status.value for item in active}
    return places, statuses


def write_csv(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    # utf-8-sig ghi BOM đầu file để Excel nhận đúng tiếng Việt.
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def read_previous(path: Path) -> list[dict[str, str]]:
    """CSV lần trước (nếu có) để giữ quyết định đã điền. Thiếu file thì coi như chưa có gì."""
    if not path.exists():
        return []
    return read_csv_rows(path)


def write_md(
    path: Path,
    rows: Sequence[Suggestion],
    *,
    db: Path,
    place_total: int,
    top_n: int,
) -> None:
    counts = count_by_kind(rows)
    per_rule = Counter(row.reason for row in rows if row.kind == KIND_CATEGORY)
    lines = [
        "# Gợi ý dọn dữ liệu địa điểm Huế",
        "",
        f"Sinh bởi `scripts/data/suggest_cleanup.py` từ `{db.as_posix()}` (chỉ đọc).",
        "Đây là danh sách đề xuất để người duyệt xác nhận. Chưa có gì trong DB bị sửa.",
        "Sửa thật: `travel-agent review`, dùng override kèm evidence khi đổi giờ mở cửa.",
        "",
        f"Địa điểm xét (đã bỏ loại REJECTED): {place_total}.",
        "",
        "## Số dòng theo loại",
        "",
        "| Loại | Số dòng |",
        "| --- | ---: |",
    ]
    lines += [f"| {kind} | {counts.get(kind, 0)} |" for kind in KIND_ORDER]
    lines += [
        "",
        "## Quy tắc",
        "",
        f"- `{KIND_DUPLICATE}`: tên giống nhau hoặc nằm trong nhau (đã bỏ dấu, bỏ từ Huế/Hue,"
        " độ dài tên ngắn nhất từ 6 ký tự), loại tương thích, cách dưới 300 m. Giữ bản có nhiều"
        " thuộc tính hơn, rồi nhiều lượt đánh giá hơn.",
        f"- `{KIND_CATEGORY}`: từ khóa trong tên không khớp loại hiện tại. Số dòng theo quy tắc:",
    ]
    rule_labels = {rule.label for rule in CATEGORY_RULES}
    for label in sorted(rule_labels):
        if per_rule.get(label):
            lines.append(f"  - {label}: {per_rule[label]}")
    lines += [
        f"- `{KIND_MISSING}`: trong {top_n} địa điểm nhiều lượt đánh giá nhất (thuộc tính"
        ' "Đánh giá"), thiếu giờ mở cửa hợp lệ hoặc thời lượng tham quan.',
        "",
        "## Cách điền cột `decision` (trong CSV)",
        "",
        "- `ok`: áp dụng gợi ý. Với `duplicate`: loại địa điểm ở cột `place_id`, giữ"
        " `other_place_id`. Với `category`: đổi loại sang `suggested_category`.",
        "- `bo`: bỏ qua, không đổi gì.",
        "- Để trống: chưa quyết định, không đổi gì.",
        "- `giu:<place_id>` (chỉ dòng `duplicate`): chọn bản giữ. `place_id` phải là một trong"
        " hai id của cặp (`place_id` hoặc `other_place_id`); bản còn lại bị loại.",
        "- `missing_data` chỉ là thông tin, điền gì cũng không đổi. Sửa giờ mở cửa bằng"
        " `travel-agent review` (có evidence).",
        "- Không đổi tên cột hoặc thứ tự cột. Khi lưu lại từ Excel, chọn CSV UTF-8 để giữ tiếng"
        " Việt.",
        "- Quy trình: chạy `scripts/data/apply_cleanup.py` để xem trước (không ghi gì), rồi chạy"
        " lại với `--apply` để áp dụng. Chạy lại không đổi thêm gì.",
        "",
        "## Lưu ý",
        "",
        "- Trùng tên trong nhóm 3 địa điểm sẽ hiện thành 3 cặp; chỉ cần xử lý một lần.",
        '- Quy tắc từ khóa là heuristic. Từ ngắn như "hồ", "đồi", "lăng" khớp đúng dấu để'
        ' tránh nhầm "đôi", "làng".',
        '- Mục "shop" trong market không có loại tương ứng trong Category, nên chỉ cảnh báo.',
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gợi ý dọn dữ liệu địa điểm (chỉ đọc DB).")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--top", type=int, default=TOP_POPULAR, help="số địa điểm phổ biến nhất")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.db.exists():
        print(f"Không tìm thấy DB: {args.db}", file=sys.stderr)
        return EXIT_ERROR
    places, statuses = load_active(args.db)
    rows = build_suggestions(places, statuses, top_n=args.top)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / CSV_NAME
    previous = read_previous(csv_path)
    merged = merge_with_previous(rows, previous)
    write_csv(csv_path, merged)
    decided = sum(1 for row in merged if row[DECISION_FIELD])
    write_md(
        args.out_dir / MD_NAME,
        rows,
        db=args.db,
        place_total=len(places),
        top_n=args.top,
    )

    print(f"Địa điểm xét: {len(places)}")
    for kind, count in count_by_kind(rows).items():
        print(f"  {kind}: {count}")
    print(f"Quyết định đã giữ từ lần trước: {decided}")
    print(f"Ghi {args.out_dir / CSV_NAME} và {args.out_dir / MD_NAME}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
