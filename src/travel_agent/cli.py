"""CLI: travel-agent fetch-osm | ingest-osm | places | review | export-approved."""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import sys
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from travel_agent.data.osm import OSM_ATTRIBUTION, build_overpass_query, places_from_overpass
from travel_agent.data.place_repository import SqlitePlaceRepository
from travel_agent.domain.models import Category
from travel_agent.review.store import ReviewStore

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Khung bao gần đúng: nội đô Huế, các lăng phía nam, Thuận An. Xem lại trên bản đồ trước khi tải.
HUE_BBOX = (16.36, 107.50, 16.58, 107.70)


def main(argv: Sequence[str] | None = None) -> int:
    _ensure_utf8_stdout()
    args = _build_parser().parse_args(argv)
    return int(args.func(args))


def _ensure_utf8_stdout() -> None:
    # PowerShell 5.1 có thể dùng code page không hiển thị được tiếng Việt khi pipe output.
    if isinstance(sys.stdout, io.TextIOWrapper) and sys.stdout.encoding.lower() not in (
        "utf-8",
        "utf8",
    ):
        sys.stdout.reconfigure(encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="travel-agent")
    sub = parser.add_subparsers(required=True)

    fetch = sub.add_parser("fetch-osm", help="Tải POI từ Overpass API (chạy một lần)")
    fetch.add_argument("--out", type=Path, required=True)
    fetch.add_argument("--bbox", type=_parse_bbox, default=HUE_BBOX, help="south,west,north,east")
    fetch.set_defaults(func=_cmd_fetch)

    ingest = sub.add_parser("ingest-osm", help="Nạp file Overpass JSON vào SQLite")
    ingest.add_argument("raw", type=Path)
    ingest.add_argument("--db", type=Path, required=True)
    ingest.set_defaults(func=_cmd_ingest)

    places = sub.add_parser("places", help="Liệt kê địa điểm trong DB")
    places.add_argument("--db", type=Path, required=True)
    places.add_argument("--category", type=Category, choices=list(Category))
    places.add_argument("--limit", type=int, default=30)
    places.set_defaults(func=_cmd_places)

    review = sub.add_parser("review", help="Mở trang duyệt tay địa điểm (chỉ trên máy này)")
    review.add_argument("--db", type=Path, required=True)
    review.add_argument("--port", type=int, default=8765)
    review.set_defaults(func=_cmd_review)

    export = sub.add_parser("export-approved", help="Xuất địa điểm đã duyệt ra JSONL")
    export.add_argument("--db", type=Path, required=True)
    export.add_argument("--out", type=Path, required=True)
    export.set_defaults(func=_cmd_export)
    return parser


def _parse_bbox(text: str) -> tuple[float, float, float, float]:
    parts = [float(part) for part in text.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox cần 4 số: south,west,north,east")
    return parts[0], parts[1], parts[2], parts[3]


def _cmd_fetch(args: argparse.Namespace) -> int:
    body = urllib.parse.urlencode({"data": build_overpass_query(args.bbox)}).encode()
    request = urllib.request.Request(
        OVERPASS_URL, data=body, headers={"User-Agent": "travel-agent-dev/0.1"}
    )
    with urllib.request.urlopen(request, timeout=200) as response:
        payload = response.read()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(payload)
    print(f"Đã lưu {len(payload)} bytes vào {args.out}. Dữ liệu {OSM_ATTRIBUTION}, ODbL-1.0.")
    return 0


def _collected_at(payload: Mapping[str, Any], raw_path: Path) -> dt.datetime:
    stamp = (payload.get("osm3s") or {}).get("timestamp_osm_base")
    if stamp:
        return dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    return dt.datetime.fromtimestamp(raw_path.stat().st_mtime, tz=dt.UTC)


def _cmd_ingest(args: argparse.Namespace) -> int:
    payload = json.loads(args.raw.read_text(encoding="utf-8"))
    collected_at = _collected_at(payload, args.raw)
    places = places_from_overpass(payload, collected_at)
    args.db.parent.mkdir(parents=True, exist_ok=True)
    repo = SqlitePlaceRepository(args.db)
    try:
        repo.upsert_many(places)
        counts = repo.count_by_category()
    finally:
        repo.close()
    with_hours = sum(1 for place in places if place.opening_hours_raw)
    print(f"Đã nạp {len(places)} địa điểm (dữ liệu OSM lúc {collected_at.isoformat()}).")
    print(f"Có opening_hours: {with_hours}/{len(places)}")
    for category, count in sorted(counts.items()):
        print(f"  {category.value}: {count}")
    return 0


def _require_db(db: Path) -> bool:
    if db.exists():
        return True
    print(f"Không tìm thấy DB {db}. Chạy ingest-osm trước.", file=sys.stderr)
    return False


def _cmd_places(args: argparse.Namespace) -> int:
    if not _require_db(args.db):
        return 2
    repo = SqlitePlaceRepository(args.db)
    try:
        for place in repo.list_places(args.category, args.limit):
            hours = place.opening_hours_raw or "giờ mở cửa: unknown"
            print(f"{place.id}\t{place.category.value}\t{place.name}\t{hours}")
    finally:
        repo.close()
    return 0


def _cmd_review(args: argparse.Namespace) -> int:
    if not _require_db(args.db):
        return 2
    import uvicorn

    from travel_agent.review.app import create_app

    print(f"Trang duyệt: http://127.0.0.1:{args.port}  (Ctrl+C để dừng)")
    uvicorn.run(create_app(args.db), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    if not _require_db(args.db):
        return 2
    store = ReviewStore(args.db)
    try:
        approved = store.approved()
    finally:
        store.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for item in approved:
            record = {
                "place": item.effective_place().model_dump(mode="json"),
                "osm_original": item.place.model_dump(mode="json"),
                "review": None if item.review is None else item.review.model_dump(mode="json"),
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Đã xuất {len(approved)} địa điểm đã duyệt vào {args.out}")
    return 0
