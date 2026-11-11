"""Test importer dữ liệu mở Huế bằng file giả nhỏ (không phải dữ liệu thật)."""

import datetime as dt
import json
import zipfile
from pathlib import Path

from travel_agent.data.hue_open_data import build_major_sights, normalize_name, slugify
from travel_agent.domain.models import Category, Coordinates, Place

NOW = dt.datetime(2026, 11, 4, tzinfo=dt.UTC)


def _docx(path: Path, rows: list[list[str]]) -> None:
    def cell(text: str) -> str:
        return f"<w:tc><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>"

    body = "".join(f"<w:tr>{''.join(cell(c) for c in row)}</w:tr>" for row in rows)
    xml = f'<w:document xmlns:w="w"><w:body><w:tbl>{body}</w:tbl></w:body></w:document>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)


def _relic(rid: str, name: str, lat: str, lon: str, opens: str = "", closes: str = "") -> dict:
    return {
        "id": rid,
        "tendoituong": name,
        "diachi": "Phường X" if rid == "7" else "",
        "kinhdo": lon,
        "vido": lat,
        "mocua": opens,
        "dongcua": closes,
        "giathamkhaotu": "Miễn phí" if rid == "7" else "",
        "giathamkhaoden": "Miễn phí" if rid == "7" else "",
    }


def _visit(pid: str, title: str, domestic: str, international: str) -> dict:
    return {
        "placeId": pid,
        "title": title,
        "soLuotTrongNuoc": domestic,
        "soLuotQuocTe": international,
    }


def make_raw_dir(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir()
    visitors = [
        _visit("1", "Di tích A ", "1000", "500"),
        _visit("2", "Bảo tàng Cổ vật Cung đình Huế", "10", "5"),
        _visit("3", "Không có tọa độ", "1", "1"),
    ]
    (raw / "Du-lieu-ve-luot-khach-tham-quan-cac-diem-Di-tich-x_1.json").write_text(
        json.dumps(visitors, ensure_ascii=False), encoding="utf-8"
    )
    relics = {
        "data": [
            _relic("7", "Di tích A (Tên khác)", "16.4", "107.5", "07: 00", "17:00"),
            _relic("8", "Bảo tàng Mỹ thuật Cung đình Huế", "16.5", "107.6", "Cả ngày"),
            _relic("9", "Đình nhỏ", "16.6", "107.7"),
        ]
    }
    (raw / "Danh-sach-dia-diem-di-tich-van-hoa-x_1.json").write_text(
        json.dumps(relics, ensure_ascii=False), encoding="utf-8"
    )
    tickets = [
        {"name": "Di tích A", "customerTypeName": "Người lớn", "price": "200000"},
        {"name": "Tuyến 2 điểm Di tích A - B", "customerTypeName": "Người lớn", "price": "300000"},
    ]
    (raw / "Danh-muc-loai-ve_1.json").write_text(
        json.dumps(tickets, ensure_ascii=False), encoding="utf-8"
    )
    _docx(
        raw / "DANH_MUC_DI_TICH_CAP_QUOC_GIA_x_1.docx",
        [
            ["Stt", "Tên di tích", "Địa điểm", "Loại hình", "Quyết định xếp hạng", "Đơn vị"],
            [
                "",
                "Di tích A",
                "Phường X",
                "KT",
                "54/QĐ ngày 1/1/1979; 1272/QĐ-TTg ngày 12/8/2009",
                "",
            ],
            ["", "Lăng B", "Phường Y", "KT", "1272/QĐ-TTg ngày 12/8/2009", ""],
            ["", "Đình nhỏ", "Phường Z", "LS", "100/QĐ ngày 1/1/2000", ""],
        ],
    )
    return raw


def osm_place(pid: str, name: str, lat: float, lon: float) -> Place:
    return Place(
        id=pid,
        name=name,
        category=Category.HISTORIC,
        coords=Coordinates(lat=lat, lon=lon),
        opening_hours_raw="Mo-Su 07:00-17:00",
        source="osm",
        source_place_id=pid,
        license="ODbL-1.0",
        collected_at=NOW,
    )


LANG_B_OSM = [osm_place("osm:way/1", "Lăng B", 16.43, 107.56)]


def test_selects_only_visitor_and_special_national_sites(tmp_path: Path) -> None:
    result = build_major_sights(make_raw_dir(tmp_path), NOW, LANG_B_OSM)
    names = sorted(place.name for place in result.places)
    assert names == ["Bảo tàng Mỹ thuật Cung đình Huế", "Di tích A (Tên khác)", "Lăng B"]
    assert result.missing == ["Không có tọa độ"]


def test_attributes_keep_source_facts_without_guessing_hours(tmp_path: Path) -> None:
    places = {p.id: p for p in build_major_sights(make_raw_dir(tmp_path), NOW).places}
    site = places["hueod:di-tich-a"]
    assert site.opening_hours_raw is None
    assert site.attributes["Giờ mở cửa (theo nguồn, không ghi ngày)"] == "07:00 – 17:00"
    assert site.attributes["Giá tham khảo (theo nguồn)"] == "Miễn phí"
    assert site.attributes["Giá vé"] == "Người lớn: 200.000đ"
    assert site.attributes["Lượt khách trong nước"] == "1.000"
    assert site.attributes["Xếp hạng"] == "Di tích quốc gia đặc biệt (1272/QĐ-TTg ngày 12/8/2009)"
    assert site.source == "data.hue.gov.vn"
    assert site.coords == Coordinates(lat=16.4, lon=107.5)


def test_renamed_museum_uses_alias_and_museum_category(tmp_path: Path) -> None:
    places = {p.id: p for p in build_major_sights(make_raw_dir(tmp_path), NOW).places}
    museum = places["hueod:bao-tang-co-vat-cung-dinh-hue"]
    assert museum.category is Category.MUSEUM
    assert museum.attributes["Giờ mở cửa (theo nguồn, không ghi ngày)"] == "Cả ngày"


def test_osm_coordinates_are_labelled_when_official_missing(tmp_path: Path) -> None:
    places = {p.id: p for p in build_major_sights(make_raw_dir(tmp_path), NOW, LANG_B_OSM).places}
    lang_b = places["hueod:lang-b"]
    assert lang_b.coords == Coordinates(lat=16.43, lon=107.56)
    assert lang_b.attributes["Nguồn tọa độ"] == "OpenStreetMap osm:way/1 (ODbL-1.0)"
    assert lang_b.attributes["Đối chiếu OSM"] == "osm:way/1, cách 0 m"
    assert lang_b.attributes["Giờ mở cửa (OSM)"] == "Mo-Su 07:00-17:00"


def test_name_helpers() -> None:
    assert normalize_name("Lăng vua  Tự Đức (Khiêm Lăng) ") == "lăng tự đức"
    assert slugify("Lăng Tự Đức") == "lang-tu-duc"
