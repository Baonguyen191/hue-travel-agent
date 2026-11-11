"""Nạp nhóm điểm tham quan lớn, phổ biến từ Cổng dữ liệu mở Huế (data.hue.gov.vn).

Quy tắc chọn, chỉ dựa trên dữ liệu chính thức, không tự đánh giá độ nổi tiếng:
1. Di tích có số lượt khách trong bộ "Dữ liệu về lượt khách tham quan các điểm Di tích của
   Trung tâm Bảo tồn Di tích Cố đô Huế".
2. Di tích có quyết định xếp hạng 1272/QĐ-TTg (di tích quốc gia đặc biệt) trong danh mục
   di tích cấp quốc gia.

Tọa độ, địa chỉ, giờ và giá theo nguồn lấy từ "Danh sách địa điểm di tích văn hóa của tỉnh".
Điểm nào không có ở đó thì lấy tọa độ từ OSM và ghi rõ nguồn; không có ở cả hai thì báo thiếu.
Giờ mở cửa theo nguồn chỉ có giờ, không ghi ngày trong tuần, nên chỉ lưu ở `attributes`;
`opening_hours_raw` để trống cho người duyệt xác nhận.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from travel_agent.domain.models import Category, Coordinates, Place
from travel_agent.routing.travel_time import haversine_m

SOURCE = "data.hue.gov.vn"
LICENSE = "Dữ liệu mở data.hue.gov.vn (yêu cầu ghi nguồn khi phát hành lại)"
SPECIAL_NATIONAL_DECISION = "1272/QĐ-TTg"

VISITORS_GLOB = "Du-lieu-ve-luot-khach-tham-quan-cac-diem-Di-tich-*.json"
RELICS_GLOB = "Danh-sach-dia-diem-di-tich-van-hoa-*.json"
TICKETS_GLOB = "Danh-muc-loai-ve_*.json"
NATIONAL_GLOB = "DANH_MUC_DI_TICH_CAP_QUOC_GIA_*.docx"

# Tên trong bộ lượt khách khác tên trong danh sách di tích vì bảo tàng đã đổi tên.
NAME_ALIASES = {"bảo tàng cổ vật cung đình huế": "bảo tàng mỹ thuật cung đình huế"}


@dataclass
class ImportResult:
    places: list[Place]
    missing: list[str] = field(default_factory=list)


@dataclass
class _Candidate:
    name: str
    domestic: int | None = None
    international: int | None = None
    ranking: str | None = None
    address: str | None = None


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFC", name).lower()
    text = re.sub(r"\(.*?\)", " ", text).replace("lăng vua", "lăng")
    return re.sub(r"\s+", " ", text).strip()


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFD", normalize_name(name).replace("đ", "d"))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def load_rows(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    rows: list[dict[str, Any]]
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw.get("data"), list):
        rows = raw["data"]
    else:
        rows = next(value for value in raw.values() if isinstance(value, list))
    return rows


def read_docx_table_rows(path: Path) -> list[list[str]]:
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    rows: list[list[str]] = []
    for row_xml in re.findall(r"<w:tr[ >].*?</w:tr>", xml, re.S):
        cells = []
        for cell_xml in re.findall(r"<w:tc>.*?</w:tc>", row_xml, re.S):
            text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", cell_xml))
            cells.append(re.sub(r"\s+", " ", text).strip())
        rows.append(cells)
    return rows


def _latest(raw_dir: Path, pattern: str) -> Path:
    matches = sorted(raw_dir.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"Không tìm thấy file {pattern} trong {raw_dir}")
    return matches[-1]


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _clean_time(text: str) -> str:
    return re.sub(r"\s*:\s*", ":", text.strip())


def _category(key: str) -> Category:
    if key.startswith("bảo tàng"):
        return Category.MUSEUM
    if key.startswith("chùa"):
        return Category.RELIGIOUS
    return Category.HISTORIC


def _collect_candidates(raw_dir: Path) -> dict[str, _Candidate]:
    candidates: dict[str, _Candidate] = {}
    for row in load_rows(_latest(raw_dir, VISITORS_GLOB)):
        key = normalize_name(row["title"])
        candidate = candidates.setdefault(key, _Candidate(name=row["title"].strip()))
        candidate.domestic = int(row["soLuotTrongNuoc"])
        candidate.international = int(row["soLuotQuocTe"])
    for cells in read_docx_table_rows(_latest(raw_dir, NATIONAL_GLOB)):
        if len(cells) < 5 or SPECIAL_NATIONAL_DECISION not in cells[4]:
            continue
        key = normalize_name(cells[1])
        candidate = candidates.setdefault(key, _Candidate(name=cells[1].strip()))
        decision = re.search(rf"{re.escape(SPECIAL_NATIONAL_DECISION)}[^;]*", cells[4])
        candidate.ranking = decision.group(0).strip() if decision else cells[4]
        candidate.address = candidate.address or cells[2]
    return candidates


def build_major_sights(
    raw_dir: Path, collected_at: dt.datetime, osm_places: Sequence[Place] = ()
) -> ImportResult:
    candidates = _collect_candidates(raw_dir)
    relics = {
        normalize_name(row["tendoituong"]): row for row in load_rows(_latest(raw_dir, RELICS_GLOB))
    }
    tickets = [
        row
        for row in load_rows(_latest(raw_dir, TICKETS_GLOB))
        if not normalize_name(row["name"]).startswith("tuyến")
    ]
    osm_by_name: dict[str, list[Place]] = {}
    for place in osm_places:
        osm_by_name.setdefault(normalize_name(place.name), []).append(place)

    result = ImportResult(places=[])
    for key, candidate in candidates.items():
        lookup = NAME_ALIASES.get(key, key)
        relic = relics.get(lookup)
        osm_matches = osm_by_name.get(lookup, []) or osm_by_name.get(key, [])
        attributes: dict[str, str] = {}
        if relic is not None:
            coords = Coordinates(lat=float(relic["vido"]), lon=float(relic["kinhdo"]))
            name = str(relic["tendoituong"]).strip()
            source_place_id = f"di-tich-van-hoa/{relic['id']}"
            attributes["Nguồn tọa độ"] = f"{SOURCE}: Danh sách địa điểm di tích văn hóa"
            if relic.get("diachi"):
                attributes["Địa chỉ"] = str(relic["diachi"]).strip()
            times = [_clean_time(t) for t in (relic["mocua"], relic["dongcua"]) if t]
            if times:
                attributes["Giờ mở cửa (theo nguồn, không ghi ngày)"] = " – ".join(times)
            prices = [p.strip() for p in (relic["giathamkhaotu"], relic["giathamkhaoden"]) if p]
            if prices:
                attributes["Giá tham khảo (theo nguồn)"] = " – ".join(dict.fromkeys(prices))
        elif osm_matches:
            coords = osm_matches[0].coords
            name = candidate.name
            source_place_id = f"danh-muc/{slugify(key)}"
            attributes["Nguồn tọa độ"] = f"OpenStreetMap {osm_matches[0].id} (ODbL-1.0)"
        else:
            result.missing.append(candidate.name)
            continue
        if candidate.address and "Địa chỉ" not in attributes:
            attributes["Địa chỉ"] = candidate.address
        if osm_matches:
            nearest = min(osm_matches, key=lambda place: haversine_m(place.coords, coords))
            distance = haversine_m(nearest.coords, coords)
            attributes["Đối chiếu OSM"] = f"{nearest.id}, cách {distance:.0f} m"
            if nearest.opening_hours_raw:
                attributes["Giờ mở cửa (OSM)"] = nearest.opening_hours_raw
        if candidate.ranking:
            attributes["Xếp hạng"] = f"Di tích quốc gia đặc biệt ({candidate.ranking})"
        if candidate.domestic is not None and candidate.international is not None:
            attributes["Lượt khách trong nước"] = _thousands(candidate.domestic)
            attributes["Lượt khách quốc tế"] = _thousands(candidate.international)
            attributes["Kỳ thống kê lượt khách"] = "không ghi trong dữ liệu nguồn"
        ticket_rows = [
            row
            for row in tickets
            if key in normalize_name(row["name"]) or lookup in normalize_name(row["name"])
        ]
        if ticket_rows:
            attributes["Giá vé"] = "; ".join(
                f"{row['customerTypeName']}: {_thousands(int(row['price']))}đ"
                for row in ticket_rows
            )
        result.places.append(
            Place(
                id=f"hueod:{slugify(key)}",
                name=name,
                category=_category(lookup),
                coords=coords,
                opening_hours_raw=None,
                source=SOURCE,
                source_place_id=source_place_id,
                license=LICENSE,
                collected_at=collected_at,
                attributes=attributes,
            )
        )
    return result


def manifest_fetched_at(raw_dir: Path) -> dt.datetime:
    """Thời điểm tải muộn nhất trong manifest; không có manifest thì dùng giờ sửa thư mục."""
    manifest = raw_dir / "manifest.json"
    if manifest.exists():
        stamps = [
            dt.datetime.fromisoformat(entry["fetched_at"])
            for entry in json.loads(manifest.read_text(encoding="utf-8"))
            if entry.get("fetched_at")
        ]
        if stamps:
            return max(stamps)
    return dt.datetime.fromtimestamp(raw_dir.stat().st_mtime, tz=dt.UTC)
