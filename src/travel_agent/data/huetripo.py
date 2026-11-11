"""Nạp địa điểm từ dữ liệu huetripo.hue.gov.vn đã crawl (scripts/crawl_huetripo.py).

Chỉ nạp loại có thể làm điểm dừng trong lịch trình: điểm du lịch, cơ sở ăn uống, chợ và
cửa hàng đặc sản. Lưu trú, lữ hành, vận chuyển và tiện ích (ATM, nhà vệ sinh...) bị bỏ qua
và được đếm trong `skipped`.

Giờ mở cửa theo nguồn chỉ có giờ, không ghi ngày trong tuần, nên chỉ lưu ở `attributes`;
`opening_hours_raw` để trống cho người duyệt xác nhận (giống importer data.hue.gov.vn).
Site không công bố giấy phép dữ liệu, nên `license` ghi rõ là chưa rõ.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from travel_agent.domain.models import Category, Coordinates, Place

SOURCE = "huetripo.hue.gov.vn"
BASE_URL = "https://huetripo.hue.gov.vn"
LICENSE = "Chưa rõ: huetripo.hue.gov.vn không công bố giấy phép dữ liệu (ghi nguồn khi dùng)"

HOURS_KEY = "Giờ mở cửa (theo nguồn, không ghi ngày)"
DURATION_KEY = "Thời gian trải nghiệm TB (phút)"
MISSING_COORDS = "thiếu tọa độ"

# loaiDoiTuongID của huetripo.
ATTRACTION_TYPE = 4
FOOD_TYPE = 2
SERVICE_TYPE = 3

ATTRACTION_FIELDS = {
    "di tích": Category.HISTORIC,
    "tâm linh": Category.RELIGIOUS,
    "không gian công cộng": Category.PARK,
}
NAME_PREFIXES = (
    ("bảo tàng", Category.MUSEUM),
    ("chùa", Category.RELIGIOUS),
    ("nhà thờ", Category.RELIGIOUS),
    ("thiền viện", Category.RELIGIOUS),
    ("tu viện", Category.RELIGIOUS),
    ("chợ", Category.MARKET),
)
CAFE_FIELDS = {"quán cà phê/trà", "tiệm bánh"}
MARKET_FIELDS = {"chợ", "cửa hàng đặc sản và quà tặng", "trung tâm thương mại"}
CONTACT_TYPES = ("Điện thoại", "Website")


@dataclass
class HuetripoImport:
    places: list[Place]
    skipped: Counter[str] = field(default_factory=Counter)


def _field(detail: dict[str, Any]) -> str:
    return re.sub(r"\s+", " ", str(detail.get("tenLinhVuc") or "")).strip()


def _category(detail: dict[str, Any]) -> Category | None:
    kind = detail.get("loaiDoiTuongID")
    linh_vuc = _field(detail).lower()
    if kind == ATTRACTION_TYPE:
        # Nhóm "Di tích" của nguồn gồm cả chùa, nhà thờ, chợ... nên ưu tiên tiền tố tên.
        name = str(detail.get("tenDiaDiem", "")).strip().lower()
        for prefix, category in NAME_PREFIXES:
            if name.startswith(prefix):
                return category
        return ATTRACTION_FIELDS.get(linh_vuc, Category.ATTRACTION)
    if kind == FOOD_TYPE:
        return Category.CAFE if linh_vuc in CAFE_FIELDS else Category.RESTAURANT
    if kind == SERVICE_TYPE and linh_vuc in MARKET_FIELDS:
        return Category.MARKET
    return None


def _kind_label(detail: dict[str, Any]) -> str:
    parts = [str(detail.get("tenLoaiDoiTuong") or "").strip(), _field(detail)]
    return " / ".join(part for part in parts if part)


def _vnd(value: float) -> str:
    return f"{round(value):,}đ".replace(",", ".")


def _hhmm(value: str | None) -> str | None:
    return value[:5] if value else None


def _hours(detail: dict[str, Any]) -> str | None:
    opens, closes = _hhmm(detail.get("gioMoCua")), _hhmm(detail.get("gioDongCua"))
    if opens and closes:
        return f"{opens} – {closes}"
    if opens:
        return f"mở {opens}"
    if closes:
        return f"đóng {closes}"
    return None


def _plain_text(markup: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", markup))
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([.,;:!?])", r"\1", text)


def _price_range(detail: dict[str, Any]) -> str | None:
    bounds = [b for b in (detail.get("giaTu"), detail.get("giaDen")) if b is not None]
    if not bounds:
        return None
    if len(bounds) == 1 or bounds[0] == bounds[1]:
        return _vnd(bounds[0])
    return f"{_vnd(bounds[0])} – {_vnd(bounds[1])}"


def _attributes(detail: dict[str, Any], url_detail: str | None) -> dict[str, str]:
    attrs: dict[str, str] = {}
    kind = _kind_label(detail)
    if kind:
        attrs["Loại hình (theo nguồn)"] = kind
    address = str(detail.get("diaChi") or "").strip()
    if address:
        attrs["Địa chỉ"] = address
    hours = _hours(detail)
    if hours:
        attrs[HOURS_KEY] = hours
    duration = detail.get("thoiGianTraiNghiemTB")
    if duration:
        attrs[DURATION_KEY] = str(duration)
    if detail.get("coMienPhi"):
        attrs["Miễn phí"] = "có"
    price = _price_range(detail)
    if price:
        attrs["Giá tham khảo (theo nguồn)"] = price
    tickets = [
        f"{', '.join(str(t[k]) for k in ('loaiVe', 'doiTuong') if t.get(k))}: {_vnd(t['giaVe'])}"
        for t in detail.get("giaVe") or []
        if t.get("giaVe") is not None
    ]
    if tickets:
        attrs["Giá vé"] = "; ".join(tickets)
    rating = detail.get("danhGia") or {}
    if rating.get("diemTBDanhGia") is not None:
        origin = rating.get("nguonDanhGia") or "không rõ nguồn"
        attrs["Đánh giá"] = (
            f"{rating['diemTBDanhGia']}/5 ({rating.get('soLuongDanhGia') or 0} lượt, {origin})"
        )
    for contact_type in CONTACT_TYPES:
        values = [
            str(c["giaTri"]).strip()
            for c in detail.get("lienHe") or []
            if c.get("loaiThongTin") == contact_type and c.get("giaTri")
        ]
        if values:
            attrs[contact_type] = "; ".join(dict.fromkeys(values))
    summary = _plain_text(str(detail.get("tomTat") or ""))
    if summary:
        attrs["Tóm tắt"] = summary
    if detail.get("anhDaiDien"):
        attrs["Ảnh đại diện"] = BASE_URL + str(detail["anhDaiDien"])
    if url_detail:
        attrs["Trang nguồn"] = BASE_URL + url_detail
    return attrs


def _coords(detail: dict[str, Any]) -> Coordinates | None:
    lat, lon = detail.get("latitude"), detail.get("longitude")
    if not lat or not lon:
        return None
    return Coordinates(lat=float(lat), lon=float(lon))


def place_from_detail(
    detail: dict[str, Any], collected_at: dt.datetime, url_detail: str | None = None
) -> Place | None:
    """Chuyển `value` của GetById thành Place; None nếu không phải điểm dừng hoặc thiếu tọa độ."""
    category = _category(detail)
    coords = _coords(detail)
    if category is None or coords is None:
        return None
    return Place(
        id=f"huetripo:{detail.get('slugID') or detail['diaDiemID']}",
        name=str(detail["tenDiaDiem"]).strip(),
        category=category,
        coords=coords,
        opening_hours_raw=None,
        source=SOURCE,
        source_place_id=str(detail["diaDiemID"]),
        license=LICENSE,
        collected_at=collected_at,
        attributes=_attributes(detail, url_detail),
    )


def _collected_at(raw_dir: Path) -> dt.datetime:
    """Giờ crawl xong trong manifest (giờ máy, không ghi múi giờ); không có thì giờ sửa thư mục."""
    manifest = raw_dir / "manifest.json"
    if manifest.exists():
        stamp = json.loads(manifest.read_text(encoding="utf-8")).get("finished")
        if stamp:
            return dt.datetime.fromisoformat(stamp).astimezone()
    return dt.datetime.fromtimestamp(raw_dir.stat().st_mtime, tz=dt.UTC)


def _detail_urls(raw_dir: Path) -> dict[str, str]:
    urls: dict[str, str] = {}
    for path in sorted((raw_dir / "lists").glob("*.json")):
        for row in json.loads(path.read_text(encoding="utf-8")):
            if row.get("diaDiemID") and row.get("urlDetail"):
                urls.setdefault(str(row["diaDiemID"]), str(row["urlDetail"]))
    return urls


def load_huetripo(raw_dir: Path) -> HuetripoImport:
    collected_at = _collected_at(raw_dir)
    urls = _detail_urls(raw_dir)
    result = HuetripoImport(places=[])
    for path in sorted((raw_dir / "details" / "dia_diem").glob("*.json")):
        detail = json.loads(path.read_text(encoding="utf-8")).get("value")
        if not detail:
            result.skipped["file rỗng"] += 1
            continue
        place = place_from_detail(detail, collected_at, urls.get(str(detail["diaDiemID"])))
        if place is not None:
            result.places.append(place)
        elif _category(detail) is None:
            result.skipped[_kind_label(detail) or "không rõ loại"] += 1
        else:
            result.skipped[MISSING_COORDS] += 1
    return result
