# Travel Agent: Huế

Dữ liệu địa điểm và công cụ duyệt tay cho LLM lập lịch du lịch chạy offline.
Lộ trình: `docs/superpowers/plans/2026-11-03-hue-planner-roadmap.md`.

## Cài đặt (Windows, Python 3.11)

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

**Lưu ý đường dẫn có dấu:** khi project nằm trong thư mục có ký tự tiếng Việt (ví dụ
`OneDrive\Máy tính`), Python 3.11 đọc sai file `.pth` của editable install, nên lệnh
`travel-agent` báo `ModuleNotFoundError`. Có hai cách xử lý:
- Chuyển project sang đường dẫn không dấu, ví dụ `C:\dev\TravelAgent` (khuyến nghị).
- Hoặc đặt `$env:PYTHONPATH="src"` rồi chạy `.venv\Scripts\python -m travel_agent <lệnh>`.

## Dữ liệu

Dữ liệu địa điểm © OpenStreetMap contributors, giấy phép ODbL-1.0.
Chỉ tải một lần, theo nguyên tắc fair-use của Overpass API:

```powershell
travel-agent fetch-osm --out data\raw\osm_hue.json
travel-agent ingest-osm data\raw\osm_hue.json --db data\hue.sqlite
```

## Duyệt tay

```powershell
travel-agent review --db data\hue.sqlite
```

Mở http://127.0.0.1:8765. Server chỉ nghe trên máy này.

**Thao tác:**
- Mỗi địa điểm chọn một trong ba trạng thái: Duyệt (A), Cần sửa (F), Loại (R). Bỏ đánh giá: U.
- Chuyển địa điểm: J/K hoặc ↓/↑.

**Chỉnh sửa:**
- Sửa tên, loại, giờ mở cửa được lưu dưới dạng override. Dữ liệu OSM gốc giữ nguyên.
- Sửa giờ mở cửa phải dùng cú pháp OSM (ví dụ `Mo-Su 07:00-17:30`) và phải ghi nguồn kiểm chứng.

Xuất các địa điểm đã duyệt (đã áp override):

```powershell
travel-agent export-approved --db data\hue.sqlite --out data\hue_places_approved.jsonl
```

## Độ phủ dữ liệu Huế (OSM, 2026-11-03T16:31:11Z)

| Mục | Số lượng |
|---|---|
| Tổng địa điểm | 785 |
| Có `opening_hours` | 159 |
| restaurant | 309 |
| cafe | 219 |
| religious | 107 |
| historic | 70 |
| attraction | 36 |
| market | 16 |
| park | 16 |
| museum | 12 |

## Kiểm thử

```powershell
.venv\Scripts\ruff format src tests
.venv\Scripts\ruff check src tests
.venv\Scripts\mypy src
.venv\Scripts\python -m pytest
```
