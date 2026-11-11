"""Test importer huetripo.hue.gov.vn bằng file giả nhỏ (không phải dữ liệu thật)."""

import datetime as dt
import json
from pathlib import Path
from typing import Any

from travel_agent.data.huetripo import LICENSE, SOURCE, load_huetripo, place_from_detail
from travel_agent.domain.models import Category

NOW = dt.datetime(2026, 11, 4, tzinfo=dt.UTC)


def detail(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "diaDiemID": "guid-1",
        "slugID": "100001",
        "tenDiaDiem": "Di tích A",
        "diaChi": " Phường X ",
        "tomTat": "<p>Di t&iacute;ch <b>A</b>.</p>",
        "noiDung": "<p>Bài dài</p>",
        "tenLinhVuc": "Di tích",
        "tenLoaiDoiTuong": "Điểm du lịch, tài nguyên",
        "loaiDoiTuongID": 4,
        "anhDaiDien": "/uploads/DiaDiem/a.jpg",
        "thoiGianTraiNghiemTB": 150,
        "giaTu": 200000,
        "giaDen": 200000,
        "giaVe": [],
        "gioMoCua": "07:30:00",
        "gioDongCua": "17:30:00",
        "coMienPhi": False,
        "latitude": 16.4,
        "longitude": 107.5,
        "lienHe": [],
        "danhGia": {"diemTBDanhGia": 4.7, "soLuongDanhGia": 17, "nguonDanhGia": "Google"},
    }
    base.update(overrides)
    return base


def test_attraction_maps_to_place_with_provenance() -> None:
    place = place_from_detail(detail(), NOW)
    assert place is not None
    assert place.id == "huetripo:100001"
    assert place.name == "Di tích A"
    assert place.category is Category.HISTORIC
    assert (place.coords.lat, place.coords.lon) == (16.4, 107.5)
    assert place.source == SOURCE
    assert place.source_place_id == "guid-1"
    assert place.license == LICENSE
    assert place.collected_at == NOW


def test_hours_without_weekdays_stay_in_attributes() -> None:
    place = place_from_detail(detail(), NOW)
    assert place is not None
    assert place.opening_hours_raw is None
    assert place.attributes["Giờ mở cửa (theo nguồn, không ghi ngày)"] == "07:30 – 17:30"


def test_only_one_hour_bound_is_labelled() -> None:
    place = place_from_detail(detail(gioDongCua=None), NOW)
    assert place is not None
    assert place.attributes["Giờ mở cửa (theo nguồn, không ghi ngày)"] == "mở 07:30"


def test_missing_hours_and_duration_add_no_attribute() -> None:
    place = place_from_detail(
        detail(gioMoCua=None, gioDongCua=None, thoiGianTraiNghiemTB=None), NOW
    )
    assert place is not None
    assert "Giờ mở cửa (theo nguồn, không ghi ngày)" not in place.attributes
    assert "Thời gian trải nghiệm TB (phút)" not in place.attributes


def test_visit_duration_price_rating_and_summary() -> None:
    place = place_from_detail(detail(), NOW)
    assert place is not None
    attrs = place.attributes
    assert attrs["Thời gian trải nghiệm TB (phút)"] == "150"
    assert attrs["Giá tham khảo (theo nguồn)"] == "200.000đ"
    assert attrs["Đánh giá"] == "4.7/5 (17 lượt, Google)"
    assert attrs["Tóm tắt"] == "Di tích A."
    assert attrs["Địa chỉ"] == "Phường X"
    assert attrs["Loại hình (theo nguồn)"] == "Điểm du lịch, tài nguyên / Di tích"
    assert attrs["Ảnh đại diện"] == "https://huetripo.hue.gov.vn/uploads/DiaDiem/a.jpg"


def test_price_range_ticket_list_and_free_flag() -> None:
    tickets = [
        {"doiTuong": "Người lớn", "giaVe": 200000.0, "loaiVe": "Vé vào cửa"},
        {"doiTuong": "Trẻ em", "giaVe": 40000.0, "loaiVe": "Vé vào cửa"},
    ]
    place = place_from_detail(detail(giaTu=50000, giaDen=120000, giaVe=tickets), NOW)
    assert place is not None
    assert place.attributes["Giá tham khảo (theo nguồn)"] == "50.000đ – 120.000đ"
    assert place.attributes["Giá vé"] == (
        "Vé vào cửa, Người lớn: 200.000đ; Vé vào cửa, Trẻ em: 40.000đ"
    )
    free = place_from_detail(detail(coMienPhi=True, giaTu=None, giaDen=None), NOW)
    assert free is not None
    assert free.attributes["Miễn phí"] == "có"
    assert "Giá tham khảo (theo nguồn)" not in free.attributes


def test_contacts_keep_phone_and_website() -> None:
    contacts = [
        {"loaiThongTin": "Điện thoại", "giaTri": "0234 111"},
        {"loaiThongTin": "Website", "giaTri": "https://a.vn"},
        {"loaiThongTin": "Điện thoại", "giaTri": "0234 222"},
    ]
    place = place_from_detail(detail(lienHe=contacts), NOW)
    assert place is not None
    assert place.attributes["Điện thoại"] == "0234 111; 0234 222"
    assert place.attributes["Website"] == "https://a.vn"


def test_category_mapping_by_type_and_field() -> None:
    cases = [
        ({"tenLinhVuc": "Tâm linh"}, Category.RELIGIOUS),
        ({"tenLinhVuc": "Thiên nhiên"}, Category.ATTRACTION),
        ({"tenLinhVuc": "Không gian công cộng"}, Category.PARK),
        ({"tenLinhVuc": "Văn hoá", "tenDiaDiem": "Bảo tàng B"}, Category.MUSEUM),
        ({"tenLinhVuc": "Di tích", "tenDiaDiem": "Chùa C"}, Category.RELIGIOUS),
        ({"tenLinhVuc": "Di tích", "tenDiaDiem": "Nhà thờ D"}, Category.RELIGIOUS),
        ({"tenLinhVuc": "Di tích", "tenDiaDiem": "Chợ E"}, Category.MARKET),
        ({"loaiDoiTuongID": 2, "tenLinhVuc": "Quán ăn"}, Category.RESTAURANT),
        ({"loaiDoiTuongID": 2, "tenLinhVuc": "Quán cà phê/trà"}, Category.CAFE),
        ({"loaiDoiTuongID": 2, "tenLinhVuc": "Tiệm bánh"}, Category.CAFE),
        ({"loaiDoiTuongID": 3, "tenLinhVuc": "Chợ "}, Category.MARKET),
        ({"loaiDoiTuongID": 3, "tenLinhVuc": "Cửa hàng đặc sản và quà tặng"}, Category.MARKET),
    ]
    for overrides, expected in cases:
        place = place_from_detail(detail(**overrides), NOW)
        assert place is not None, overrides
        assert place.category is expected, overrides


def test_non_itinerary_types_are_skipped() -> None:
    for overrides in (
        {"loaiDoiTuongID": 1, "tenLinhVuc": "Khách sạn"},
        {"loaiDoiTuongID": 5, "tenLinhVuc": "Lữ hành nội địa"},
        {"loaiDoiTuongID": 12, "tenLinhVuc": "Taxi và xe công nghệ"},
        {"loaiDoiTuongID": 3, "tenLinhVuc": "Điểm vệ sinh công cộng"},
    ):
        assert place_from_detail(detail(**overrides), NOW) is None, overrides


def test_missing_coordinates_are_skipped() -> None:
    assert place_from_detail(detail(latitude=None), NOW) is None
    assert place_from_detail(detail(latitude=0, longitude=0), NOW) is None


def make_raw_dir(tmp_path: Path) -> Path:
    raw = tmp_path / "huetripo"
    details = raw / "details" / "dia_diem"
    details.mkdir(parents=True)
    rows = [
        detail(),
        detail(
            diaDiemID="guid-2",
            slugID="100002",
            loaiDoiTuongID=1,
            tenLoaiDoiTuong="Cơ sở lưu trú du lịch",
            tenLinhVuc="Khách sạn",
        ),
        detail(diaDiemID="guid-3", slugID="100003", latitude=None),
    ]
    for row in rows:
        (details / f"{row['diaDiemID']}.json").write_text(
            json.dumps({"isSuccess": True, "value": row}, ensure_ascii=False), encoding="utf-8"
        )
    (raw / "lists").mkdir()
    (raw / "lists" / "diem_tham_quan.json").write_text(
        json.dumps([{"diaDiemID": "guid-1", "urlDetail": "/diem-tham-quan/di-tich/a-100001"}]),
        encoding="utf-8",
    )
    (raw / "manifest.json").write_text(
        json.dumps({"started": "2026-11-04T01:00:00", "finished": "2026-11-04T01:12:52"}),
        encoding="utf-8",
    )
    return raw


def test_load_reads_details_lists_and_manifest(tmp_path: Path) -> None:
    result = load_huetripo(make_raw_dir(tmp_path))
    assert [place.id for place in result.places] == ["huetripo:100001"]
    place = result.places[0]
    assert place.attributes["Trang nguồn"] == (
        "https://huetripo.hue.gov.vn/diem-tham-quan/di-tich/a-100001"
    )
    assert place.collected_at.tzinfo is not None
    assert place.collected_at.replace(tzinfo=None) == dt.datetime(2026, 11, 4, 1, 12, 52)
    assert result.skipped == {"Cơ sở lưu trú du lịch / Khách sạn": 1, "thiếu tọa độ": 1}
