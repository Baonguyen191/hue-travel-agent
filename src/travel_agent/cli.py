"""CLI: travel-agent fetch-osm | ingest-* | places | review | export-... | make-evalset | eval"""

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

from travel_agent.data.hue_open_data import build_major_sights, manifest_fetched_at
from travel_agent.data.huetripo import DURATION_KEY as HUETRIPO_DURATION_KEY
from travel_agent.data.huetripo import HOURS_KEY as HUETRIPO_HOURS_KEY
from travel_agent.data.huetripo import SOURCE as HUETRIPO_SOURCE
from travel_agent.data.huetripo import load_huetripo
from travel_agent.data.osm import OSM_ATTRIBUTION, build_overpass_query, places_from_overpass
from travel_agent.data.place_repository import SqlitePlaceRepository
from travel_agent.domain.models import Category
from travel_agent.review.store import ReviewStore
from travel_agent.sources.models import LinkStatus
from travel_agent.sources.store import LinkStore
from travel_agent.training.commands import add_training_commands

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

    hue_od = sub.add_parser(
        "ingest-hue-open-data",
        help="Nạp điểm tham quan lớn, phổ biến từ dữ liệu mở data.hue.gov.vn đã tải",
    )
    hue_od.add_argument("raw_dir", type=Path)
    hue_od.add_argument("--db", type=Path, required=True)
    hue_od.set_defaults(func=_cmd_ingest_hue_open_data)

    huetripo = sub.add_parser(
        "ingest-huetripo",
        help="Nạp điểm tham quan, ăn uống, chợ từ dữ liệu huetripo.hue.gov.vn đã crawl",
    )
    huetripo.add_argument("raw_dir", type=Path)
    huetripo.add_argument("--db", type=Path, required=True)
    huetripo.set_defaults(func=_cmd_ingest_huetripo)

    places = sub.add_parser("places", help="Liệt kê địa điểm trong DB")
    places.add_argument("--db", type=Path, required=True)
    places.add_argument("--category", type=Category, choices=list(Category))
    places.add_argument("--limit", type=int, default=30)
    places.set_defaults(func=_cmd_places)

    review = sub.add_parser("review", help="Mở trang duyệt tay địa điểm (chỉ trên máy này)")
    review.add_argument("--db", type=Path, required=True)
    review.add_argument("--port", type=int, default=8765)
    review.set_defaults(func=_cmd_review)

    links = sub.add_parser("links", help="Liệt kê link nguồn dữ liệu đã thêm")
    links.add_argument("--db", type=Path, required=True)
    links.add_argument("--status", type=LinkStatus, choices=list(LinkStatus))
    links.set_defaults(func=_cmd_links)

    export = sub.add_parser("export-approved", help="Xuất địa điểm đã duyệt ra JSONL")
    export.add_argument("--db", type=Path, required=True)
    export.add_argument("--out", type=Path, required=True)
    export.set_defaults(func=_cmd_export)
    add_training_commands(sub)
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


def _cmd_ingest_hue_open_data(args: argparse.Namespace) -> int:
    args.db.parent.mkdir(parents=True, exist_ok=True)
    repo = SqlitePlaceRepository(args.db)
    try:
        osm_places = repo.list_places(limit=-1, source="osm")
        result = build_major_sights(args.raw_dir, manifest_fetched_at(args.raw_dir), osm_places)
        repo.upsert_many(result.places)
    finally:
        repo.close()
    print(f"Đã nạp {len(result.places)} điểm tham quan lớn, phổ biến (nguồn data.hue.gov.vn).")
    for place in sorted(result.places, key=lambda p: p.name):
        print(f"  {place.id}\t{place.name}\t{place.attributes.get('Nguồn tọa độ', '')}")
    if result.missing:
        print("Thiếu tọa độ ở cả dữ liệu mở và OSM, chưa nạp: " + ", ".join(result.missing))
    return 0


def _cmd_ingest_huetripo(args: argparse.Namespace) -> int:
    result = load_huetripo(args.raw_dir)
    args.db.parent.mkdir(parents=True, exist_ok=True)
    repo = SqlitePlaceRepository(args.db)
    try:
        repo.upsert_many(result.places)
        counts = repo.count_by_category(source=HUETRIPO_SOURCE)
    finally:
        repo.close()
    total = len(result.places)
    with_hours = sum(1 for place in result.places if HUETRIPO_HOURS_KEY in place.attributes)
    with_duration = sum(1 for place in result.places if HUETRIPO_DURATION_KEY in place.attributes)
    print(f"Đã nạp {total} địa điểm (nguồn {HUETRIPO_SOURCE}).")
    print(f"Có giờ mở cửa theo nguồn: {with_hours}/{total}")
    print(f"Có thời gian trải nghiệm TB: {with_duration}/{total}")
    for category, count in sorted(counts.items()):
        print(f"  {category.value}: {count}")
    if result.skipped:
        print("Bỏ qua (không phải điểm dừng trong lịch trình hoặc thiếu tọa độ):")
        for label, count in result.skipped.most_common():
            print(f"  {label}: {count}")
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

    print(f"Trang duyệt: http://127.0.0.1:{args.port}")
    print(f"Thêm link nguồn dữ liệu: http://127.0.0.1:{args.port}/links  (Ctrl+C để dừng)")
    uvicorn.run(create_app(args.db), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def _cmd_links(args: argparse.Namespace) -> int:
    if not _require_db(args.db):
        return 2
    store = LinkStore(args.db)
    try:
        for link in store.list(args.status):
            note = link.note or ""
            print(f"{link.id}\t{link.status.value}\t{link.topic.value}\t{link.url}\t{note}")
    finally:
        store.close()
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
