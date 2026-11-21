# IMPLEMENTATION PLAN — HỆ THỐNG AI MULTI-AGENT DU LỊCH HUẾ (DATA-FIRST)

> **Phiên bản:** 2.0 — 21/11/2026  
> **Căn cứ:** kiểm tra trực tiếp file người dùng cung cấp `hue.sqlite`, không giả định cấu trúc của database.  
> **Mục tiêu:** hướng dẫn thực hiện theo từng phase, có thể đưa trực tiếp cho Codex/AI coding assistant.  
> **Phạm vi MVP:** tìm kiếm điểm tham quan + ăn uống ở **Huế** bằng dữ liệu thực đã có; lên kế hoạch và dự toán; vé xe/khách sạn dùng mock hoặc API hợp lệ khi có; booking mô phỏng trước, **không tự nhận đã đặt thật**.

---

## 0. THAY ĐỔI QUAN TRỌNG SO VỚI KẾ HOẠCH CŨ

1. **Không tạo bộ dữ liệu địa điểm mẫu mới**: sử dụng **1.587 POI trong `hue.sqlite`** làm nguồn chính cho quán ăn, cà phê, di tích, tham quan, chợ, địa điểm tôn giáo, công viên và bảo tàng.
2. **Không ép chuyển `hue.sqlite` sang PostgreSQL ngay**: SQLite được truy cập **read-only** với một `HuePlacesRepository`; PostgreSQL chỉ lưu user, chuyến đi, các phiên bản plan, approval, booking, agent run và checkpoint. Giữ nguyên nguồn dữ liệu.
3. **MVP chỉ lập lịch trình tại Huế**. Người dùng có thể khởi hành từ tỉnh/thành khác, nhưng dữ liệu các điểm ghé thăm chỉ phủ Huế. Yêu cầu điểm đến ngoài Huế phải được thông báo chưa hỗ trợ, không trả nhầm điểm Huế.
4. **Dữ liệu KHÔNG chứa khách sạn, vé xe, giờ xe, tồn chỗ, API đặt bàn, mã booking**. Search Agent phải chia hai nguồn: `SQLitePlacesProvider` (POI) và `Mock/ExternalTravelProvider` (xe, phòng). Không tạo “đặt thật” từ một dòng POI.
5. **Không mặc định có giá cho mọi nơi**: `Giá tham khảo (theo nguồn)` chỉ có một phần, còn dạng chuỗi; `Miễn phí=có` chỉ là thông tin mô tả theo nguồn, không suy rộng thành mọi chi phí bằng 0. Phải trả `KNOWN`, `ESTIMATED` hoặc `UNKNOWN`.
6. **MVP tối ưu nhẹ**: 1.587 hàng không cần vector DB, Elasticsearch, Kafka hay microservices. Dùng SQLite query + chuẩn hóa tiếng Việt + RapidFuzz; geographic filtering bằng Haversine, lịch trình ban đầu bằng greedy + kiểm tra thời gian. Nâng cấp FTS5/OR-Tools khi có lý do đo được.
7. **Đúng 5 Agent**: Search, Budget, Itinerary, Booking, Orchestrator. Các bước `parse/validate/check_approval/revalidate/persist` là node/hàm kỹ thuật, **không phải Agent thứ 6**.
8. **Đảm bảo provenance và quyền sử dụng**: nguồn của 1.587 bản ghi là `huetripo.hue.gov.vn`; trường `license` ghi tình trạng **chưa rõ giấy phép**. Cần xác minh quyền tái sử dụng/hình ảnh khi công khai hoặc thương mại hóa, không coi ghi nguồn là đủ quyền pháp lý.

**Definition of Done của MVP:** nhập “Tôi đi Huế 3 ngày 2 đêm, xuất phát Hà Nội, 2 người, ngân sách 6 triệu, thích di tích và đặc sản” → lập phương án có **ID POI từ SQLite**, lịch theo giờ và nguồn → tính tiền không giả số liệu thực → UI xem/sửa/duyệt → booking **mock** cho xe/phòng và hiển thị rõ nhãn **MÔ PHỎNG**. Không có luồng bỏ qua phê duyệt.

---

## 1. DATA AUDIT — KẾT QUẢ XÁC NHẬN TỪ `hue.sqlite`

### 1.1. Cấu trúc thật của database

- Định dạng: SQLite 3, kích thước khoảng 1,93 MB; `PRAGMA quick_check` trả `ok` khi kiểm tra.
- **Chỉ có 1 bảng nghiệp vụ:** `places`; index `idx_places_category`; khóa chính `id`.
- **Tổng 1.587 bản ghi**. Dữ liệu có cùng thời điểm thu thập `2026-11-04T01:12:52+07:00`.
- Nguồn đồng nhất: `huetripo.hue.gov.vn`.

SQL của bảng **đúng theo file**:

```sql
CREATE TABLE places (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    opening_hours_raw TEXT,
    source TEXT NOT NULL,
    source_place_id TEXT NOT NULL,
    license TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    attributes_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_places_category ON places (category);
```

**Bảng thống kê theo `category`**:

| category thật | Số lượng | Sử dụng trong sản phẩm |
|---|---:|---|
| `restaurant` | 826 | ăn uống, đặc sản (kiểm tra mô tả) |
| `cafe` | 285 | cà phê, đồ uống, nghỉ giữa lịch |
| `historic` | 251 | di tích, kiến trúc, lịch sử |
| `attraction` | 87 | điểm tham quan / thiên nhiên |
| `market` | 58 | chợ, trải nghiệm địa phương |
| `religious` | 57 | điểm tôn giáo |
| `park` | 15 | dạo chơi, thư giãn |
| `museum` | 8 | bảo tàng |
| **Tổng** | **1.587** | **8 nhóm** |

**Mức độ đầy đủ của một số trường** (trong `attributes_json`, trừ nơi đã chú thích):

| Thông tin | Số bản ghi có | Hệ quả kỹ thuật |
|---|---:|---|
| `Đánh giá` | 1.576 | chuỗi, cần parse rating và số lượt |
| `Địa chỉ` | 1.497 | fallback sang tọa độ khi thiếu |
| `Ảnh đại diện` | 1.390 | phải kiểm tra quyền dùng ảnh, URL có thể hết hiệu lực |
| `Thời gian trải nghiệm TB (phút)` | 1.000 | còn thiếu, không được coi 0 phút |
| `Giá tham khảo (theo nguồn)` | 503 | chuỗi giá, **không xác định chắc đơn vị** |
| `Điện thoại` | 459 | dữ liệu liên hệ, không đồng nghĩa API đặt chỗ |
| `Miễn phí` = có | 399 | chỉ coi là một tín hiệu, kiểm tra ngữ cảnh hạng mục |
| `Tóm tắt` | 373 | sử dụng khi giải thích đề xuất |
| `opening_hours_raw` khác NULL | 1.447 | còn **140** nơi thiếu giờ chuẩn hóa |
| `Giờ mở cửa (theo nguồn, không ghi ngày)` | 1.542 | thông tin lịch có độ tin cậy hạn chế; không suy ra mở đủ 7 ngày |

**Dải tọa độ dữ liệu:** latitude từ **16.110201 đến 16.7154**, longitude từ **107.1058 đến 108.131294**. Một số điểm có thể xa trung tâm, vì vậy **không mặc định tất cả nằm gần nhau hoặc có thể đi trong cùng một buổi**.

### 1.2. Schema của `attributes_json` (key tiếng Việt cần giữ nguyên khi đọc)

Các key thực tế gồm:

```text
Loại hình (theo nguồn)
Trang nguồn
Đánh giá
Giờ mở cửa (theo nguồn, không ghi ngày)
Địa chỉ
Giờ mở cửa: giả định
Ảnh đại diện
Thời gian trải nghiệm TB (phút)
Giá tham khảo (theo nguồn)
Điện thoại
Miễn phí
Tóm tắt
Website
Giá vé
```

Ví dụ bản ghi nhận diện bằng `id='huetripo:192068'` là **Đồi Thiên An** thuộc `category='attraction'`; các thuộc tính có thể gồm tên, thời gian trải nghiệm, đánh giá, mô tả, giờ và trang nguồn. `source_place_id` **không giống** hậu tố số trong `id`, nên không thay thế lẫn nhau.

### 1.3. Database CÓ và KHÔNG có gì

| Chức năng | Đã có trong `hue.sqlite`? | Cách làm |
|---|---|---|
| Tìm địa điểm Huế theo tên/loại | **Có** | Query SQLite |
| Đánh giá và xếp hạng POI | **Một phần** | Parse `Đánh giá`, xử lý thiếu |
| Tìm theo vị trí/khoảng cách | **Có tọa độ** | Haversine sơ bộ, Routes API về sau |
| Giờ mở cửa | **Một phần, không ghi ngày** | Parse thận trọng + warning |
| Thời lượng tham quan | **Một phần** | Ưu tiên giá trị nguồn, còn thiếu hỏi/ước tính gắn nhãn |
| Giá quán ăn | **Một phần** | Price range mô tả, **không chắc giá mỗi người** |
| Vé tham quan chính xác | **Hầu như không** (`Giá vé` chỉ 1 bản ghi) | Kiểm chứng ở provider hoặc đưa về `UNKNOWN` |
| Giá phòng, phòng còn trống | **Không** | Hotel provider mock/API |
| Vé xe, giờ xe, ghế trống | **Không** | Transport provider mock/API |
| Đặt dịch vụ thực | **Không** | Chỉ qua API provider có quyền truy cập |
| Thời gian di chuyển đường bộ | **Không** | Haversine estimate → Routes API |

**Chú ý nguồn:** trường `license` của file đang ghi: `Chưa rõ: huetripo.hue.gov.vn không công bố giấy phép dữ liệu (ghi nguồn khi dùng)`. Đây là ghi chú trong dữ liệu, **không phải văn bản cấp phép**. Trước khi public repo/chạy kinh doanh/hiển thị ảnh, phải xác minh điều khoản và quyền sử dụng với bên sở hữu dữ liệu.

### 1.4. Các lệnh kiểm tra dữ liệu (chạy lại bất cứ lúc nào)

Đặt `hue.sqlite` trong thư mục `backend/data/`, chạy Python từ `backend`:

```python
import sqlite3, json
from collections import Counter

con = sqlite3.connect("file:data/hue.sqlite?mode=ro", uri=True)
con.row_factory = sqlite3.Row
print("Integrity:", con.execute("PRAGMA quick_check").fetchone()[0])
print("Rows:", con.execute("SELECT COUNT(*) FROM places").fetchone()[0])
print("Categories:", [tuple(r) for r in con.execute(
    "SELECT category, COUNT(*) FROM places GROUP BY category ORDER BY COUNT(*) DESC"
)])
row = con.execute("SELECT * FROM places LIMIT 1").fetchone()
print("Columns:", list(row.keys()))
print("Attribute keys:", list(json.loads(row["attributes_json"]).keys()))
print("Missing hours:", con.execute(
    "SELECT COUNT(*) FROM places WHERE opening_hours_raw IS NULL"
).fetchone()[0])
con.close()
```

**Done:** ra đúng 1.587 bản ghi và 8 category; không tự ghi/sửa file nguồn.

---

## 2. CHỐT KIẾN TRÚC TỐI ƯU: TWO-DATABASE, FIVE-AGENT

```mermaid
flowchart TD
    UI[React + TypeScript UI] --> API[FastAPI /api/v1]
    API --> G[LangGraph: Orchestrator Agent]
    G --> S[Search Agent]
    G --> B[Budget Agent]
    G --> I[Itinerary Agent]
    G --> A{Plan hợp lệ và được người dùng duyệt?}
    A -- Không --> UI
    A -- Có --> K[Booking Agent]

    S --> P[HuePlacesRepository READ ONLY]
    P --> SQLITE[(hue.sqlite: 1.587 places)]
    S --> T[TransportProvider: Mock -> API]
    S --> H[HotelProvider: Mock -> API]
    I --> R[RouteEstimator: Haversine -> Routes API]
    B --> PG[(PostgreSQL: giao dịch và plan)]
    G --> PG
    K --> BOOK[BookingProvider: MOCK -> authorized API]
    K --> PG
    API --> PG
```

**Quy tắc dữ liệu:**

- `hue.sqlite` là **nguồn dữ liệu POI** và chỉ đọc; `id` gốc `huetripo:...` là `poi_id` được giữ xuyên suốt qua search → itinerary → UI → lưu kế hoạch.
- PostgreSQL là **nguồn sự thật của nghiệp vụ**: trips, selected offers, plan_versions, approvals, bookings, idempotency keys, agent_runs, checkpoint.
- Mọi `POI` có `origin=sqlite_hue`, `source`, `source_url`, `collected_at` và `confidence`/`data_freshness` nếu hiển thị. Giá/giờ không đủ rõ cần warning.
- **Không tạo FK giữa PostgreSQL và SQLite**; lưu `poi_id` dạng string và xác thực qua repository trước khi ghi plan.
- Chỉ một Backend FastAPI. Không cần microservice, message broker, vector DB hay migrate POI vào Postgres ở MVP.

### 2.1. Công nghệ

| Thành phần | Chọn | Lý do |
|---|---|---|
| Frontend | React + TypeScript + Vite + Tailwind | chat, cards, map, timeline |
| Backend | Python 3.11+ + FastAPI + Pydantic v2 | typed API, validate |
| 5 Agent | LangGraph `StateGraph` + OpenAI API | orchestration, state, LLM ở bước cần suy luận |
| Đọc POI | `sqlite3` chuẩn Python | đọc file ngay, không migration |
| Tìm tên tiếng Việt | `unicodedata` + RapidFuzz | nhẹ với 1.587 địa điểm, xử lý dấu |
| Geospatial MVP | Haversine + geo filter | không cần API key, **chỉ là khoảng cách thẳng** |
| Route thật (nâng cấp) | Google Routes API / provider tương đương | ETA theo đường, phương tiện |
| Optimizer | integer arithmetic + enumeration | dễ test, sau này OR-Tools CP-SAT |
| Business DB | PostgreSQL + SQLAlchemy + Alembic | checkpoint/booking/versioning |
| External HTTP | HTTPX, provider adapters | dễ thay mock bằng API |
| Testing | pytest + httpx + Playwright | unit, integration, E2E |

**LLM không phải “nguồn dữ liệu”**. Nó giúp hiểu câu hỏi và chọn tiêu chí/sở thích; mọi địa điểm được gợi ý phải có `poi_id` thực hoặc được phân biệt rõ là chưa có trong kho dữ liệu.

### 2.2. Phân chia trách nhiệm (đúng 5 Agent)

| Agent | Nguồn dữ liệu | Thuật toán | Output chuẩn |
|---|---|---|---|
| **1 — Search** | `hue.sqlite` + hotel/bus provider | category filter → text matching → distance → weighted rank | `PoiCandidate[]`, `TransportOffer[]`, `HotelOffer[]` |
| **2 — Budget** | offer xe/phòng + POI price hints + user budget | deterministic cost + enumeration, optional CP-SAT | `CostBreakdown`, `SelectedOffers`, `BudgetStatus` |
| **3 — Itinerary** | POI SQLite đã chọn + route times + lịch provider | score POI → geo grouping → greedy/2-opt → time windows | `ItineraryDay[]`, warnings/conflicts |
| **4 — Booking** | plan đã duyệt + provider API | state machine, saga, idempotency, reconciliation | `BookingResult[]` (mock/real phân biệt) |
| **5 — Orchestrator** | request + state + results 4 agent | LangGraph routing, validation, limited retry, interrupt | `TravelState`, `PlanVersion`, action |

---

## 3. CẤU TRÚC THƯ MỤC ĐỀ XUẤT

```text
travel-multi-agent/
├── IMPLEMENTATION_PLAN.md               # sao chép file hướng dẫn này
├── .gitignore
├── docker-compose.yml
├── backend/
│   ├── .env.example
│   ├── requirements.txt (hoặc pyproject.toml)
│   ├── data/
│   │   └── hue.sqlite                  # copy từ file người dùng, source read-only
│   ├── scripts/
│   │   ├── audit_hue.py
│   │   └── benchmark_search.py
│   ├── app/
│   │   ├── main.py
│   │   ├── core/{config.py,security.py,logging.py}
│   │   ├── api/{router.py,places.py,trips.py,plans.py,bookings.py}
│   │   ├── repositories/
│   │   │   └── hue_places.py            # đọc SQLite read-only
│   │   ├── schemas/
│   │   │   ├── place.py                 # raw → normalized POI
│   │   │   ├── request.py
│   │   │   ├── offer.py
│   │   │   ├── itinerary.py
│   │   │   └── booking.py
│   │   ├── providers/
│   │   │   ├── base.py
│   │   │   ├── transport_mock.py
│   │   │   ├── hotel_mock.py
│   │   │   ├── booking_mock.py
│   │   │   └── routes_estimator.py
│   │   ├── services/
│   │   │   ├── normalize_hue.py
│   │   │   ├── poi_search.py
│   │   │   ├── ranking.py
│   │   │   ├── budget_optimizer.py
│   │   │   ├── itinerary_optimizer.py
│   │   │   ├── itinerary_validator.py
│   │   │   ├── approval_service.py
│   │   │   └── booking_service.py
│   │   ├── agents/
│   │   │   ├── state.py
│   │   │   ├── orchestrator.py
│   │   │   ├── search.py
│   │   │   ├── budget.py
│   │   │   ├── itinerary.py
│   │   │   └── booking.py
│   │   └── db/
│   │       ├── base.py
│   │       ├── session.py
│   │       └── models.py
│   ├── alembic/
│   └── tests/
│       ├── test_hue_repository.py
│       ├── test_normalization.py
│       ├── test_poi_search.py
│       ├── test_budget.py
│       ├── test_itinerary.py
│       ├── test_orchestrator.py
│       └── test_booking.py
└── frontend/
    └── src/
        ├── pages/{HomePage,PlannerPage,PlanPage,BookingPage}.tsx
        ├── components/{TripForm,PlaceCard,PlaceMap,Timeline,BudgetCard}.tsx
        ├── services/api.ts
        └── App.tsx
```

**Dependency:** `api → agents/services → repositories/providers/db`; repository không tự gọi LLM; backend và UI **không truy cập trực tiếp file SQLite của người dùng từ browser**.

---

## 4. CHẠY MÔI TRƯỜNG LOCAL TRÊN WINDOWS/POWERSHELL

### 4.1. Tạo project và copy database

```powershell
mkdir travel-multi-agent
cd travel-multi-agent
mkdir backend
mkdir backend\data
mkdir backend\scripts

# Đặt file hue.sqlite được cung cấp cạnh README/plan trong thư mục gốc,
# rồi copy vào backend/data (điều chỉnh đường dẫn nguồn cho đúng máy):
Copy-Item .\hue.sqlite .\backend\data\hue.sqlite

npm create vite@latest frontend -- --template react-ts
cd backend
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install fastapi "uvicorn[standard]" pydantic pydantic-settings `
  langgraph langgraph-checkpoint-postgres openai "psycopg[binary]" `
  sqlalchemy alembic httpx python-dotenv pytest pytest-asyncio `
  rapidfuzz ortools
pip freeze > requirements.txt
cd ..
cd frontend
npm install
npm install axios react-router-dom lucide-react
npm install tailwindcss @tailwindcss/vite
cd ..
```

> Nếu máy không có `py -3`, dùng `python -m venv .venv`. Nếu PowerShell chặn venv, thực thi `Set-ExecutionPolicy -Scope Process Bypass` trong phiên terminal hiện tại rồi kích hoạt lại.

### 4.2. File `.env.example`

```dotenv
APP_ENV=development
HUE_SQLITE_PATH=./data/hue.sqlite
DATABASE_URL=postgresql+psycopg://travel:local_password@localhost:5432/travel_db
OPENAI_API_KEY=
OPENAI_MODEL=choose_supported_model
DESTINATION_SCOPE=Hue
TRANSPORT_PROVIDER=mock
HOTEL_PROVIDER=mock
BOOKING_PROVIDER=mock
ROUTES_PROVIDER=haversine_estimate
MAX_OPTIMIZATION_ROUNDS=3
FRONTEND_ORIGIN=http://localhost:5173
```

Bí mật chỉ đặt trong `.env`, **không commit**. `hue.sqlite` có tình trạng giấy phép chưa rõ: đưa `backend/data/*.sqlite` vào `.gitignore` nếu repo sẽ công khai, không commit file nguồn cho tới khi xác minh quyền phân phối.

### 4.3. PostgreSQL phục vụ dữ liệu nghiệp vụ

`docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:17
    environment:
      POSTGRES_USER: travel
      POSTGRES_PASSWORD: local_password
      POSTGRES_DB: travel_db
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - pg_data:/var/lib/postgresql/data
volumes:
  pg_data:
```

Chạy `docker compose up -d` và dùng Alembic tạo bảng ở phase nghiệp vụ. **Không chạy migration trên file `hue.sqlite` nguồn.**

---

## 5. PHASE DỮ LIỆU — REPOSITORY VÀ NORMALIZATION

### 5.1. `HuePlacesRepository`: chỉ đọc bằng SQL tham số hóa

Tạo `backend/app/repositories/hue_places.py`:

```python
from __future__ import annotations
import json
import sqlite3
from pathlib import Path

class HuePlacesRepository:
    def __init__(self, db_path: str):
        self.path = Path(db_path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError(f"Không thấy hue.sqlite: {self.path}")

    def connect(self):
        # as_uri() hoạt động với cả đường dẫn Windows.
        con = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con

    def get_by_id(self, place_id: str) -> dict | None:
        con = self.connect()
        try:
            row = con.execute(
                "SELECT * FROM places WHERE id = ?", (place_id,)
            ).fetchone()
            if row is None:
                return None
            item = dict(row)
            item["attributes"] = json.loads(item.pop("attributes_json"))
            return item
        finally:
            con.close()

    def list_by_category(self, category: str, limit: int = 100) -> list[dict]:
        if category not in {
            "restaurant", "cafe", "historic", "attraction",
            "market", "religious", "park", "museum"
        }:
            return []
        con = self.connect()
        try:
            rows = con.execute(
                "SELECT * FROM places WHERE category = ? ORDER BY name LIMIT ?",
                (category, max(1, min(limit, 500)))
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["attributes"] = json.loads(item.pop("attributes_json"))
                result.append(item)
            return result
        finally:
            con.close()
```

**Tại sao không dùng ORM cho file nguồn ngay?** Chỉ có 1 bảng, 1.587 hàng, không có yêu cầu ghi. `sqlite3` giúp đọc đúng schema, ít dependency, dễ audit; SQLAlchemy vẫn dùng cho PostgreSQL nghiệp vụ.

### 5.2. Normalized POI contract — không mất trường nguồn

Tạo Pydantic model `Place` với trường:

```text
id: str                      # e.g. huetripo:192068
name: str
category: Literal[restaurant,cafe,historic,attraction,market,religious,park,museum]
lat: float
lon: float
address: str | None
rating_value: float | None        # 0..5
rating_count: int | None
rating_source: str | None
opening_hours_raw: str | None
opening_hours_confidence: Literal[UNVERIFIED,PARTIAL,UNKNOWN]
visit_minutes: int | None
price_min_vnd: int | None
price_max_vnd: int | None
price_unit: str | None             # UNKNOWN nếu nguồn không nêu
price_status: Literal[REFERENCE_RANGE,FREE_CLAIM,UNKNOWN]
is_free_claim: bool               # không tự đồng nghĩa miễn mọi chi phí
summary: str | None
photo_url: str | None
source: str
source_url: str | None
source_place_id: str
collected_at: datetime
raw_attributes: dict                # giữ để truy vết
```

**Mapping chính xác từ `attributes_json`**:

```text
"Địa chỉ"                             -> address
"Đánh giá"                            -> parse_rating(...)
"Thời gian trải nghiệm TB (phút)"    -> parse_visit_minutes(...)
"Giá tham khảo (theo nguồn)"         -> parse_reference_price_range(...)
"Miễn phí"                           -> is_free_claim
"Tóm tắt"                             -> summary
"Ảnh đại diện"                        -> photo_url
"Trang nguồn"                         -> source_url
"Giờ mở cửa (theo nguồn, không ghi ngày)" -> preserved_raw_hours
```

**Dữ liệu nhạy cảm theo ngữ nghĩa:**

- `"4.9/5 (132 lượt, Không xác định)"` là rating parse được, nhưng `Không xác định` là thông tin nguồn rating, không phải bằng chứng được Google xác nhận.
- `"100.000đ – 200.000đ"` là **khoảng giá tham khảo**; không biết chắc theo món, bữa, người hay hóa đơn. Không lấy trung bình và tự gọi là `price_per_person`.
- `opening_hours_raw='07:30-17:30'` **không có ngày trong tuần**; không kết luận “chắc chắn mở vào Chủ nhật”. Khi lập lịch phải gắn cảnh báo giờ cần xác minh.
- `visit_minutes` nếu thiếu -> `None`. Có thể sử dụng default ước lượng theo loại điểm để lên lịch **nhưng phải gắn nhãn ASSUMED**, không gán lại vào dữ liệu nguồn.
- `Giá vé` rất ít; hầu hết vé tham quan phải đánh dấu chưa xác minh.

### 5.3. Các hàm parse cần viết và test

```text
normalize_vietnamese(text) -> str       # Unicode NFKD, bỏ combining marks,
                                         # xử lý "đ"/"Đ", lower, whitespace
parse_rating(text) -> value/count/source|None
parse_visit_minutes(text) -> int|None
parse_reference_price_range(text) -> min/max/status
parse_open_hours(text) -> structured_hours|None
haversine_km(lat1,lon1,lat2,lon2) -> float
```

**Giờ mở cửa**: chỉ parse khi rõ định dạng, ví dụ `HH:MM-HH:MM`. Các trường hợp `mở 16:00`, giờ qua đêm, ngày nghỉ, khoảng mơ hồ phải giữ `UNKNOWN/PARTIAL`; không tự suy thành 24 giờ.

**Test normalization:** tên có/không dấu (`đại nội` ↔ `Dai Noi`); khoảng giá `100.000đ – 200.000đ`; rating `4.8/5 (55 lượt, Google)`; duration `90`; raw hours `07:30-17:30`; unknown/malformed không crash; toàn bộ 1.587 JSON parse không lỗi.

### 5.4. Chiến lược tìm kiếm giai đoạn đầu

Với chỉ 1.587 bản ghi:

1. Load và normalize bản ghi cần thiết khi khởi động (hoặc cache theo category).
2. Hard filter `category`, phạm vi Huế, tọa độ hợp lệ và điều kiện bắt buộc.
3. So khớp `name`, `summary`, `Loại hình (theo nguồn)` và `address` bằng RapidFuzz trên text đã chuẩn hóa tiếng Việt.
4. Nếu có tâm chuyến đi/khách sạn, tính Haversine để lọc vùng và chấm điểm gần.
5. Phân biệt rating cao ít lượt vs rating nhiều lượt; nên có confidence factor/weighted Bayesian rating.
6. Chọn Top-K đa dạng khu vực và loại địa điểm; tránh dồn 10 quán cà phê cạnh nhau.

**Không cần vector database**. Nếu truy vấn đo được chậm hoặc mở rộng lên hàng chục nghìn bản ghi: tạo **search index riêng** (không sửa source SQLite) bằng FTS5 `unicode61` hoặc hệ tìm kiếm khác; benchmark thực tế trước khi thêm.

---

## 6. AGENT 1 — SEARCH AGENT (SQLITE-FIRST)

### 6.1. Input và output

Input `TripRequest`: `origin`, **`destination='Huế'`**, `start_date/end_date`, `people`, `budget_vnd`, `preferences`, `transport_mode`, `lodging_preferences`, `must_visit_place_ids`.

Output:

```json
{
  "poi_candidates": [
    {
      "poi_id": "huetripo:192068",
      "name": "Đồi Thiên An",
      "category": "attraction",
      "source": "huetripo.hue.gov.vn",
      "price_status": "FREE_CLAIM",
      "opening_hours_confidence": "UNVERIFIED",
      "score": null
    }
  ],
  "transport_offers": [],
  "hotel_offers": [],
  "warnings": ["Hotel/transport providers in MOCK mode"]
}
```

`price_status=FREE_CLAIM` trong ví dụ xuất phát từ thuộc tính `Miễn phí=có` ở bản ghi này, **không phải giá vé đã được xác minh**; `score` phải được thuật toán tính khi search (ví dụ để `null`). Các trạng thái chỉ là ví dụ schema, không hardcode cho mọi POI.

### 6.2. Tool contracts

```python
async def search_hue_places(query, categories, limit) -> list[Place]: ...
async def get_hue_place(poi_id) -> Place | None: ...
async def nearby_hue_places(lat, lon, radius_km, categories) -> list[Place]: ...
async def search_transport(request) -> list[TransportOffer]: ...  # mock/API
async def search_hotels(request) -> list[HotelOffer]: ...        # mock/API
```

**Chạy song song:** `asyncio.gather()` cho transport/hotel/place discovery nếu API bất đồng bộ. **Không chạy truy vấn SQLite blocking kéo dài trong async event loop**; với dataset nhỏ có thể dùng endpoint sync hoặc threadpool cho query. Không chia nhỏ thành 4 Agent tìm kiếm: vẫn là **một Search Agent** có nhiều tool/provider.

### 6.3. Thuật toán xếp hạng

Dùng hard constraints trước, weighted score sau:

\[
S_{poi}=0.35S_{interest}+0.25S_{rating}+0.25S_{distance}+0.15S_{dataquality}
\]

- `S_interest`: độ khớp sở thích với tên/mô tả/loại hình.
- `S_rating`: rating chuẩn hóa + mức tin cậy theo số lượt.
- `S_distance`: điểm gần khách sạn/khu vực ưu tiên, **chưa có ETA đường bộ**.
- `S_dataquality`: điểm hiện hữu của giờ, địa chỉ, thời lượng, ảnh; dữ liệu thiếu -> phạt confidence nhẹ, **không mặc định rating=0**.
- Tất cả điểm [0,1]; trọng số ban đầu là giả thiết cần đánh giá qua test và người dùng.
- Enforce `must_visit_place_ids` khi có; không xóa điểm bắt buộc chỉ vì điểm thấp.

**Done:** `/api/v1/places?category=historic` tìm được POI từ file; endpoint search trả `poi_id` hợp lệ và truy xuất nguồn, không phát sinh tên/giá không có thật.

---

## 7. AGENT 2 — BUDGET AGENT (COST PROVENANCE)

### 7.1. Tách 3 loại tiền

| Nhãn | Ý nghĩa | Ví dụ |
|---|---|---|
| `QUOTED` | giá thực của provider có thời gian hiệu lực và đơn vị | hotel offer có quote hợp lệ |
| `ESTIMATED` | ước lượng/suất chi theo giả định công khai | budget 120.000đ/người/bữa **do user cấu hình** |
| `UNKNOWN` | dữ liệu không đủ kết luận | vé tham quan không có giá |

**Không cho `UNKNOWN = 0`**. Tính riêng `known_total`, `estimated_total`, `unknown_items`; `display_total` chỉ là **tổng dự kiến có điều kiện**, không phải giá chốt toàn chuyến.

### 7.2. Chi phí và đơn vị

\[
C_{planned}=C_{transport}+C_{rooms}+C_{meals}+C_{entry}+C_{local}+C_{fees}+C_{reserve}
\]

- Xe: giá mỗi người cho **đúng chặng** × số người; chiều đi và chiều về khác nhau.
- Phòng: giá `room_night` × số đêm × số phòng + thuế/phí.
- Ăn uống: dùng ngân sách/giả định người dùng (nếu POI giá tham khảo thiếu đơn vị).
- Vé tham quan: nếu `UNKNOWN` phải tạo cảnh báo, cho user nhập budget hoặc kết nối nguồn xác minh, không âm thầm thêm 0.
- Chi phí đi lại nội thành: chỉ là ước lượng khi chưa có provider báo giá.
- Reserve: 5–15% (mặc định 10%) trên các khoản có thể dự toán, **không thay thế chi phí chưa biết**.
- Số nguyên VND hoặc `Decimal`; mọi phép nhân đơn vị và quantity có test.

### 7.3. Thuật toán lựa chọn

**MVP enumeration**:

1. Lấy các offer transport đi/về và hotel từ provider, loại offer không đáp ứng ràng buộc cứng.
2. Sinh tổ hợp xe đi × xe về × khách sạn; nếu không có offer, không chế giá, trả trạng thái thiếu dữ liệu.
3. Tính chi phí breakdown, cộng budget ăn/uống/tham quan/di chuyển do user cấu hình.
4. Loại phương án vượt ngân sách khi đây là ràng buộc cứng, giữ vài phương án thay thế có giải thích.
5. Trong tập hợp hợp lệ, tối đa utility (chất lượng/tiện nghi) sau đó xét chi phí.
6. Nếu dữ liệu UNKNOWN quan trọng: `BUDGET_INCOMPLETE` thay vì `WITHIN_BUDGET` tuyệt đối.

**Nâng cấp CP-SAT:** `x_offer ∈ {0,1}`, chọn chính xác một phương án cho mỗi dịch vụ bắt buộc, số phòng đủ sức chứa, thời gian chặng phù hợp, giới hạn tổng chi phí có dữ liệu rõ. Chỉ áp dụng khi enumeration trở nên đắt.

**Done:** với cùng offer + quantity, tổng chi phí luôn nhất quán; trả `unknown_items`, không tạo giá từ LLM, không tính nhầm giá tham khảo quán thành suất ăn/người.

---

## 8. AGENT 3 — ITINERARY AGENT (HUE-LOCAL ROUTE)

### 8.1. Input

- Danh sách POI `poi_id` có `lat/lon`, `category`, `visit_minutes` và giờ mở cửa.
- Các mốc cứng: giờ đến Huế, giờ rời Huế, check-in/out nếu **có quote/booking đáng tin cậy**.
- Lựa chọn sở thích, cường độ lịch trình, người lớn/trẻ em, thời gian nghỉ và budget.

### 8.2. Thuật toán MVP (ít POI/ngày)

1. Từ Search Agent chọn top POI đa dạng, ưu tiên `must_visit`.
2. Gán POI vào ngày theo cụm gần nhau dựa trên Haversine; tránh ghép điểm xa ở ngoài trung tâm vào lịch nội thành quá dày.
3. Với mỗi ngày, chạy `nearest_neighbor` từ điểm xuất phát (khách sạn nếu biết); có thể dùng `2-opt` để giảm tổng km thẳng sau khi xây dựng lộ trình.
4. Tính thời gian di chuyển: **ESTIMATED** từ distance/estimated-speed có buffer; **không gọi là Google Maps ETA** nếu chưa dùng Routes API.
5. Lấy `visit_minutes` từ dữ liệu; khi thiếu dùng giả định config và gắn cờ `ASSUMED_DURATION`.
6. Parse giờ từ `opening_hours_raw` khi rõ định dạng; nếu dữ liệu không có ngày trong tuần: cảnh báo `HOURS_NEED_VERIFICATION`.
7. Chèn giờ ăn (restaurant POI), giờ nghỉ, check-in/out và buffer.
8. Validator kiểm tra trùng lịch, giờ đóng/mở đã biết, khả năng đi lại, thời gian hành trình, di chuyển xa, giá chưa rõ.
9. Trả kế hoạch, warnings và `route_confidence`; nếu không khả thi, bỏ bớt POI tùy chọn hoặc yêu cầu chọn lại.

### 8.3. Mục tiêu tối ưu

\[
\min(\alpha T_{travel}+\beta C_{local}+\gamma T_{idle}-\delta U_{interest})
\]

**Hard constraints:** giờ đi/đến của vé đã được provider xác nhận; check-in/out; địa điểm có giờ mở rõ; thời lượng tham quan tối thiểu; không trùng giờ. **Soft constraints:** ngắn đường, phù hợp sở thích, đa dạng, nghỉ hợp lý. Tham quan 2–4 POI chính/ngày là **tham số đề xuất**, không phải dữ kiện nguồn.

### 8.4. Route provider upgrade

- Mặc định `HaversineRouteEstimator` → trả `distance_straight_km`, `estimated_minutes`, `confidence=LOW`, không gán là road distance.
- Bản nâng cấp `GoogleRoutesAdapter`/provider khác → ma trận thời gian theo đường, có nguồn và thời điểm truy xuất.
- Nếu chặng di chuyển từ ngoài Huế (Hà Nội → Huế), **không dùng Haversine nội thành để suy ra giờ xe thật**.

**Done:** người dùng thấy bản đồ POI, timeline theo ngày, không có POI giả; plan có cảnh báo khi giờ/giá/route cần xác minh.

---

## 9. AGENT 4 — BOOKING AGENT (KHÔNG DỰA VÀO SQLITE ĐỂ ĐẶT)

### 9.1. Phạm vi chức năng

- **Trong MVP:** `MockBookingProvider` tạo mã **MÔ PHỎNG** cho xe/phòng đã có offer giả lập, có các nhánh confirmed/failed/timeout/partial.
- **Về sau:** tích hợp nhà xe/khách sạn bằng API hợp lệ có thao tác availability, quote, create, get_status, cancel và webhook theo tài liệu đối tác.
- **Đối với POI nhà hàng/di tích từ `hue.sqlite`:** mặc định `BOOKING_NOT_SUPPORTED_BY_DATASET`; nếu có điện thoại hoặc trang nguồn, chỉ cung cấp thông tin để người dùng liên hệ; không giả định có API đặt bàn.

### 9.2. Trạng thái và workflow

```mermaid
stateDiagram-v2
    [*] --> DRAFT
    DRAFT --> AWAITING_APPROVAL
    AWAITING_APPROVAL --> APPROVED: user approves exact plan version
    APPROVED --> REVALIDATING
    REVALIDATING --> RECONFIRM_REQUIRED: changes in price / terms
    RECONFIRM_REQUIRED --> REVALIDATING: user reconfirms
    REVALIDATING --> SUBMITTING
    SUBMITTING --> CONFIRMED
    SUBMITTING --> PARTIALLY_BOOKED
    SUBMITTING --> FAILED
    SUBMITTING --> UNKNOWN
    UNKNOWN --> CONFIRMED: reconciliation
    UNKNOWN --> FAILED: provider confirms failure
```

**Lớp bảo vệ bắt buộc trong `BookingService` (không phụ thuộc prompt):**

1. User đăng nhập; chủ sở hữu đúng `trip_id`.
2. `plan_version` được duyệt là version hiện tại và hash báo giá/điều khoản được duyệt khớp.
3. Dịch vụ có `booking_supported=True` và provider hợp lệ; nếu không: không gọi API ghi.
4. Revalidate quote/tồn chỗ; giá đổi → quay lại `RECONFIRM_REQUIRED`.
5. Unique `idempotency_key` cho mỗi booking intent; double-click chỉ có 1 yêu cầu; cần lock DB/unique constraint.
6. Provider timeout → `UNKNOWN` và đối soát, **không tự gửi lại POST create** nếu chưa biết trạng thái.
7. Không báo toàn chuyến `COMPLETED` nếu còn vé/phòng bắt buộc chưa xác nhận.
8. Nếu đặt một phần thành công, báo `PARTIALLY_BOOKED`; xử lý thay thế/hủy theo chính sách, không hứa refund tự động.
9. Booking thật chỉ qua API có quyền truy cập. Payment qua cổng được phép, không đưa thông tin thẻ vào LLM/log.

**Done:** không thể booking trước duyệt, không thể booking POI chỉ có trong SQLite, UI hiển thị rõ mô phỏng hay thực.

---

## 10. AGENT 5 — ORCHESTRATOR AGENT (LANGGRAPH)

### 10.1. Flow

```text
START
  → ParseRequest (LLM Structured Outputs hoặc form)
  → ValidateDestinationAndDates
       ├── destination != Hue → UNSUPPORTED_DESTINATION / yêu cầu thay đổi
       ├── thiếu ngày, ngân sách… → ASK_USER
       └── hợp lệ
            → SearchAgent (SQLite POI + mock transport/hotel)
            → BudgetAgent (chi phí có provenance)
            → ItineraryAgent (POI IDs + route)
            → ValidatePlan (budget + opening + schedule + provider warnings)
                 ├── Invalid, attempts<3 → Retry/Search/Revise
                 ├── Invalid, attempts>=3 → RETURN_ALTERNATIVES
                 └── Valid/conditional → SavePlanVersion
                        → HumanApproval (interrupt)
                             ├── Edit/Reject → new plan version, invalidate approval
                             └── Approve exact version
                                  → RevalidateProviders
                                       ├── changed → Reconfirm
                                       └── stable → BookingAgent → FinalResult
```

### 10.2. `TravelState`

```python
from typing import TypedDict, Any

class TravelState(TypedDict, total=False):
    trip_id: str
    request: dict[str, Any]
    destination_scope: str                 # Hue
    poi_candidates: list[dict[str, Any]]
    transport_offers: list[dict[str, Any]]
    hotel_offers: list[dict[str, Any]]
    selected_poi_ids: list[str]
    selected_offers: dict[str, Any]
    budget_result: dict[str, Any]
    itinerary: list[dict[str, Any]]
    validation_issues: list[dict[str, Any]]
    optimization_round: int
    plan_version: int
    approval_status: str
    approved_plan_version: int | None
    booking_result: dict[str, Any]
    status: str
```

**LangGraph:** `StateGraph`, conditional edges, checkpointer, `interrupt()` và `Command(resume=...)`. Cùng `thread_id=trip_id`; bảo đảm có thể khôi phục sau restart khi dùng PostgreSQL checkpoint. Side effect booking phải được tách vào service idempotent vì node có thể bị replay khi resume/retry.

**LLM dùng ở đâu?**

- Parse ý định tiếng Việt, sở thích như “thích lăng tẩm, ăn đặc sản Huế”.
- Search Agent chọn category/query và giải thích đề xuất nhưng **candidate POI phải lấy từ SQLite**.
- Itinerary Agent sắp ưu tiên dựa trên sở thích nhưng validator quyết định tính hợp lệ.
- Budget Agent giải thích đánh đổi, không cộng tiền bằng model.
- Booking Agent giải thích trạng thái, không quyết định giao dịch thành công.

**Done:** chỉ 5 Agent chuyên trách, các node kỹ thuật không tăng số lượng; không loop vô hạn; không bypass approval.

---

## 11. THIẾT KẾ DATABASE NGHIỆP VỤ POSTGRESQL

Không clone 1.587 POI vào PostgreSQL ở MVP. Lưu tham chiếu `poi_id` và optional snapshot của tên/giờ/nguồn nhằm tái hiện plan tại thời điểm tạo.

| Bảng | Cột tối thiểu | Ràng buộc |
|---|---|---|
| `users` | `id`, `email`, `auth_ref` | email unique |
| `trips` | `id`, `user_id`, `request_json`, `destination`, `status`, `current_plan_version`, `created_at` | FK user |
| `plan_versions` | `id`, `trip_id`, `version`, `selected_poi_ids_json`, `selected_offers_json`, `itinerary_json`, `costs_json`, `status`, `created_at` | unique `(trip_id,version)` |
| `offers` | `id`, `trip_id`, `provider`, `type`, `price_json`, `availability`, `retrieved_at`, `expires_at` | unique provider id per scope |
| `approvals` | `id`, `trip_id`, `plan_version`, `approved_quote_hash`, `user_id`, `approved_at` | approval only current plan |
| `bookings` | `id`, `trip_id`, `approval_id`, `offer_id`, `provider`, `mode`, `status`, `idempotency_key`, `provider_reference` | key unique |
| `booking_events` | `id`, `booking_id`, `event_type`, `payload_json`, `occurred_at` | index booking/time |
| `agent_runs` | `id`, `trip_id`, `agent`, `started_at`, `ended_at`, `latency_ms`, `tokens_used`, `error_code` | tracing |

**Chú ý:** Mỗi `itinerary_item` phải chứa `poi_id` từ `hue.sqlite` (hoặc typed reference riêng đối với hotel/bus, **không giả POI ID cho hotel**). Sử dụng UTC để lưu timestamp có timezone, hiển thị bằng `Asia/Ho_Chi_Minh`; ngày tham quan thuộc giờ địa phương.

---

## 12. DATA CONTRACTS VÀ API

### 12.1. Trip request

```json
{
  "origin": "Hà Nội",
  "destination": "Huế",
  "start_date": "2026-12-10",
  "end_date": "2026-12-12",
  "people": 2,
  "budget_vnd": 6000000,
  "transport_mode": "bus",
  "preferences": ["di tích", "ẩm thực Huế"],
  "must_visit_place_ids": ["huetripo:192068"]
}
```

Đây là **request mẫu**; ngày, ngân sách và lịch trình không được ngầm hiểu là dịch vụ thật đang còn chỗ. Nếu user nhập “Đà Nẵng” thì báo dataset POI hiện chỉ hỗ trợ Huế.

### 12.2. Offer contract (xe/phòng, không phải POI)

```json
{
  "offer_id": "mock-hotel-1",
  "offer_type": "hotel",
  "provider": "mock",
  "currency": "VND",
  "unit_price_vnd": 600000,
  "price_unit": "room_night",
  "quantity": 2,
  "taxes_fees_vnd": 0,
  "price_kind": "MOCK",
  "availability": "UNKNOWN",
  "booking_supported": false,
  "retrieved_at": null,
  "expires_at": null
}
```

**Không dùng** `booking_supported=true` đối với dữ liệu mô phỏng để ngầm cho phép giao dịch thật. Có thể dùng `mock_booking_supported=true` trong kiểu riêng nếu cần demo.

### 12.3. API cần thiết

| Method | Endpoint | Chức năng |
|---|---|---|
| `GET` | `/health` | trạng thái API và check đọc POI |
| `GET` | `/api/v1/places` | category/query/limit, danh sách địa điểm Huế |
| `GET` | `/api/v1/places/{poi_id}` | chi tiết + provenance + cảnh báo |
| `GET` | `/api/v1/places/nearby` | POI gần vị trí (định nghĩa route tránh xung đột `/places/{id}`) |
| `POST` | `/api/v1/trips` | tạo trip và khởi chạy graph |
| `GET` | `/api/v1/trips/{trip_id}` | trạng thái |
| `GET` | `/api/v1/trips/{trip_id}/plans/current` | lịch trình/chi phí hiện hành |
| `POST` | `/api/v1/trips/{trip_id}/revisions` | tạo version kế hoạch mới |
| `POST` | `/api/v1/trips/{trip_id}/approvals` | duyệt plan version |
| `POST` | `/api/v1/trips/{trip_id}/booking-intents` | tạo intent sau khi duyệt |
| `GET` | `/api/v1/trips/{trip_id}/bookings` | trạng thái từng booking |
| `GET` | `/api/v1/trips/{trip_id}/events` | SSE hoặc polling để hiện tiến độ |

**Lưu ý route:** khai báo `/api/v1/places/nearby` **trước** `/api/v1/places/{poi_id}`, hoặc dùng `/api/v1/places/search/nearby` để không bị match nhầm chuỗi `nearby` thành `poi_id`.

### 12.4. UI: 5 màn hình tối thiểu

1. **Trip Request / Chat**: chọn Huế, ngày, điểm đi, số người, budget, sở thích.
2. **Explore Huế**: filter 8 category, search có/không dấu, các POI trả từ SQLite; thẻ tên, ảnh nếu có quyền sử dụng, nguồn, rating, cảnh báo giờ/giá.
3. **Itinerary + Map**: timeline ngày/giờ, POI markers, quãng đường là **ước lượng** hay road ETA rõ ràng.
4. **Budget + Approval**: tổng `QUOTED/ESTIMATED`, khoản `UNKNOWN`, version, điều kiện xác nhận; có thể sửa plan.
5. **Booking Dashboard**: trạng thái xe/phòng, mã **MÔ PHỎNG**/mã thật, phần thất bại, liên kết nguồn.

Đừng ẩn cảnh báo chỉ vì thiết kế giao diện đẹp. Giá POI tham khảo không có đơn vị phải hiển thị dưới dạng khoảng tham khảo và chú thích.

---

## 13. WORK BREAKDOWN — 11 PHASE THEO THỨ TỰ TỐI ƯU

> **Quy tắc:** từng phase có checklist, test và commit riêng. Không giao Codex “viết toàn bộ hệ thống” trong một lần. Chỉ làm phase tiếp theo khi `Done` của phase hiện tại đạt.

### PHASE 0 — Khởi tạo dự án và kiểm tra file nguồn (0,5–1 ngày)

**Làm:**
- [ ] Tạo repo, backend, frontend, `.gitignore`.
- [ ] Copy `hue.sqlite` vào `backend/data/hue.sqlite` (không sửa file nguồn).
- [ ] Viết `scripts/audit_hue.py`: `PRAGMA quick_check`, đếm bản ghi, category, tỷ lệ NULL, key JSON, min-max lat/lon, nguồn/license.
- [ ] Viết README chỉ dẫn nơi đặt dữ liệu và giới hạn giấy phép.
- [ ] Tạo FastAPI `/health` báo rõ khi thiếu file.

**Done:** đếm đúng **1.587/8 categories**; SQLite vẫn đọc được sau khi chạy script; `GET /health` hoạt động.

### PHASE 1 — Repository read-only + chuẩn hóa dữ liệu (1–2 ngày)

**Làm:**
- [ ] `HuePlacesRepository`: get_by_id, list_by_category, list_all, search candidates.
- [ ] Pydantic `Place`: đầy đủ source, category, coordinates và `raw_attributes`.
- [ ] Parse rating, review count, address, price range, hours, duration, free claim.
- [ ] Unit test tất cả 1.587 record và parse hỏng/thiếu; đảm bảo không mutate DB.

**Done:** API `GET /api/v1/places` và `GET .../{poi_id}` truy xuất đúng dữ liệu nguồn; không xảy ra 500 khi `attributes_json` thiếu trường.

### PHASE 2 — Local search/ranking trên 1.587 POI (1–2 ngày)

**Làm:**
- [ ] Viết `normalize_vietnamese` và RapidFuzz ranking.
- [ ] Filter category, keyword, radius và sở thích.
- [ ] Haversine + điểm chất lượng/rating confidence + diversity.
- [ ] Endpoint search + nearby (có pagination/limit).
- [ ] Benchmark với tên có dấu/không dấu và trường hợp không có kết quả.

**Done:** trả Top-K POI với `poi_id` thật, source URL, score; không tạo địa điểm bịa; đủ nhanh với dataset hiện tại.

### PHASE 3 — Provider xe, khách sạn, route estimator (1–2 ngày)

**Làm:**
- [ ] Định nghĩa interface cho `TransportProvider`, `HotelProvider`, `RouteProvider`.
- [ ] Tạo **fixture mock** rõ nhãn `MOCK` cho các chặng đi/về và 2 đêm phòng, có giá đúng đơn vị.
- [ ] Một nhánh provider trả rỗng/timeout để thử lỗi.
- [ ] HaversineRouteEstimator trả thông tin `ESTIMATED`, chưa gán road ETA.

**Done:** Search Agent có thể gộp dữ liệu Huế thật + xe/phòng mock mà không đánh đồng loại nguồn.

### PHASE 4 — Search Agent hoàn chỉnh (1–2 ngày)

**Làm:**
- [ ] Nối POI repository và 2 mock providers vào một Search Agent.
- [ ] `asyncio.gather` cho provider calls khi hợp lý.
- [ ] Hard filter và Weighted Ranking; giữ `poi_id` và provenance.
- [ ] Validator kiểm tra chỉ trả địa điểm Huế; scope khác trả trạng thái chưa hỗ trợ.

**Done:** một TripRequest → candidate POI/transport/hotel hợp lệ, nếu provider không có dữ liệu thì cảnh báo và không chế quote.

### PHASE 5 — Budget Agent chính xác và minh bạch (1–2 ngày)

**Làm:**
- [ ] Thiết kế `CostItem` gồm amount, quantity, price_unit, source, price_kind (`QUOTED/ESTIMATED/UNKNOWN`).
- [ ] Cộng xe 2 chiều, room_night × đêm × phòng, ăn uống dự toán cấu hình, vé tham quan chưa rõ.
- [ ] Enumeration lựa chọn tổ hợp xe/phòng; xếp hạng trong budget.
- [ ] Test giá thiếu, chưa rõ đơn vị, phí, quá budget, số người/thời gian.

**Done:** cùng input → cùng tiền; không dùng LLM cộng tiền; chi phí chưa biết luôn được liệt kê, không gán 0 ngầm.

### PHASE 6 — Itinerary Agent thực dùng POI Huế (2–3 ngày)

**Làm:**
- [ ] Chọn POI từ category phù hợp, chia cụm theo ngày.
- [ ] Greedy/Nearest Neighbor (+ 2-opt tùy chọn).
- [ ] Time windows, visit duration, meal slots, nghỉ, buffer.
- [ ] Dùng Haversine estimated minutes, cảnh báo giờ chưa xác minh.
- [ ] Itinerary validator: giờ, ngày, trùng, xa, cân đối hoạt động.

**Done:** lịch 3 ngày 2 đêm chứa `poi_id` thật, không chồng giờ, có cảnh báo hợp lý và có thể hiển thị bản đồ.

### PHASE 7 — Orchestrator + Structured Outputs + HITL (2–3 ngày)

**Làm:**
- [ ] Parse yêu cầu tiếng Việt thành `TripRequest` bằng OpenAI Structured Outputs; fallback form khi thiếu ngày/điểm đi.
- [ ] LangGraph `StateGraph`: Search → Budget → Itinerary → Validate → Approval.
- [ ] Retry tối đa 3 vòng; lưu cảnh báo và options.
- [ ] PostgreSQL + SQLAlchemy + Alembic cho `trips`, `plan_versions`, `approvals`.
- [ ] Durable checkpoint PostgreSQL, human `interrupt()`, resume theo `thread_id`.
- [ ] Người dùng sửa plan → tăng version, duyệt cũ hết hiệu lực.

**Done:** trước khi người dùng duyệt, trạng thái dừng ở `AWAITING_APPROVAL`; restart backend vẫn resume được; không có infinite loop.

### PHASE 8 — Booking Agent mock với Saga + security (2–3 ngày)

**Làm:**
- [ ] Booking Provider interface; mock thành công/thất bại/UNKNOWN.
- [ ] `approvals` version/hash; `booking_intent` + unique idempotency key.
- [ ] Revalidation; mock giá đổi → reconfirm.
- [ ] Saga một phần thành công; không hứa tự hoàn tiền.
- [ ] API booking kiểm tra owner, version, approval.
- [ ] Gắn nhãn `MOCK` ở mọi response liên quan.

**Done:** 0 booking khi chưa duyệt; double-click không tạo hai intent; trạng thái `PARTIALLY_BOOKED` đúng.

### PHASE 9 — Frontend React, trực quan hóa địa điểm Huế (2–4 ngày)

**Làm:**
- [ ] Form/chat yêu cầu; tìm kiếm 8 nhóm POI.
- [ ] Danh sách + chi tiết địa điểm với nguồn và mức tin cậy.
- [ ] Map pin POI thật bằng lat/lon; timeline + budget breakdown.
- [ ] Chỉnh plan/version; nút phê duyệt; booking mock dashboard.
- [ ] Loading/partial/error/stale data và giao diện mobile.

**Done:** flow end-to-end từ nhập yêu cầu đến nhận mã **mô phỏng** và xem nguồn dữ liệu; frontend không gửi booking trước duyệt.

### PHASE 10 — API thật, kiểm thử E2E và chuẩn bị bảo vệ (tùy quyền truy cập)

**Làm:**
- [ ] Nếu được phép: tích hợp API xe, khách sạn có quote/availability; route matrix thực.
- [ ] Review giấy phép dữ liệu và ảnh trước khi public.
- [ ] E2E/contract/integration tests, audit bảo mật, log metrics.
- [ ] Tài liệu sequence diagram, ERD, evaluation, demo lỗi partial/timeout.
- [ ] Docker Compose/deployment có kiểm tra biến môi trường và secrets.

**Done:** MVP ổn định; API nào không có quyền thì để mock và mô tả rõ giới hạn; không tuyên bố booking thật chưa triển khai.

---

## 14. BỘ TEST BẮT BUỘC (ƯU TIÊN DỮ LIỆU THẬT)

| ID | Nhóm | Scenario | Kỳ vọng |
|---|---|---|---|
| D01 | Data | Đọc `hue.sqlite` read-only | `quick_check=ok`, 1.587 hàng, 8 category |
| D02 | Data | Toàn bộ JSON attributes | parse được, không crash khi trường thiếu |
| D03 | Data | `huetripo:192068` | truy xuất được Đồi Thiên An, `category=attraction` |
| D04 | Data | `opening_hours_raw IS NULL` | status unknown; không tự cho mở mọi ngày |
| D05 | Data | “Giá tham khảo” dạng range | không mặc định per-person; phân biệt reference |
| D06 | Data | Rating thiếu/chuỗi lỗi | `None` + cảnh báo, không tự 5.0 |
| S01 | Search | Tìm “quan ca phe” không dấu | trả đúng nhóm `cafe` khi có kết quả |
| S02 | Search | Query di tích | trả POI category phù hợp từ SQLite |
| S03 | Search | Điểm đến Đà Nẵng | `UNSUPPORTED_DESTINATION`, không gợi ý Huế |
| S04 | Search | Provider xe không có offer | báo thiếu option, không bịa giá |
| B01 | Budget | Hai chiều vé + 2 đêm | đúng unit/quantity |
| B02 | Budget | POI giá không rõ | tạo unknown item, không thêm 0 như giá chắc chắn |
| B03 | Budget | Vượt ngân sách | trả alternatives hoặc `OVER_BUDGET` |
| I01 | Itinerary | 1 ngày nhiều điểm xa nhau | validator cảnh báo/tối ưu lại |
| I02 | Itinerary | Thiếu opening day/time | warning `HOURS_NEED_VERIFICATION` |
| I03 | Itinerary | Điểm bắt buộc `poi_id` sai | 422/validation error, không bịa ID |
| O01 | Orchestrator | 3 lượt tối ưu không đạt | stop, trả nguyên nhân |
| O02 | Orchestrator | Thay đổi `plan_version` sau duyệt | approval cũ vô hiệu |
| K01 | Booking | Chưa duyệt | HTTP 403/409, không side effect |
| K02 | Booking | Mock provider timeout | `UNKNOWN`, tra cứu trạng thái trước retry |
| K03 | Booking | Double-click đặt | chỉ 1 idempotency key/intent |
| K04 | Booking | Xe thành công, phòng lỗi | `PARTIALLY_BOOKED` |
| K05 | Booking | POI SQLite không hỗ trợ booking | không tạo booking thật; nêu cách liên hệ |
| R01 | Reliability | Restart server lúc chờ duyệt | Postgres checkpoint resume được |
| A01 | Access | User A lấy trip User B | bị chặn |

**Metrics**: POI coverage từ SQLite, % plan dùng POI IDs hợp lệ (mục tiêu 100%), missing hours/price warning coverage, top-k relevance, duplicate booking rate (=0), approval bypass rate (=0), budget arithmetic error (=0), generation latency, LLM token cost.

---

## 15. CHẠY VÀ DEMO

### 15.1. Lệnh local sau khi đã code từng phase

```powershell
# Terminal 1: thư mục gốc
 docker compose up -d

# Terminal 2: backend
cd backend
.\.venv\Scripts\Activate.ps1
python scripts/audit_hue.py
alembic upgrade head
uvicorn app.main:app --reload

# Terminal 3: frontend
cd frontend
npm run dev

# Terminal 4: tests
cd backend
.\.venv\Scripts\Activate.ps1
pytest -q
```

**Các lệnh `audit_hue.py`, Alembic và tests chỉ chạy sau khi tạo file/migration tương ứng tại phase liên quan.**

### 15.2. Kịch bản demo bảo vệ đồ án

1. Kiểm tra nguồn: show `SELECT COUNT(*)`, 8 category, nguồn và ngày thu thập.
2. Tìm “di tích Huế” → màn hình hiển thị POI ID thật, địa chỉ, rating, thời lượng và cảnh báo nếu thiếu thông tin.
3. Người dùng nhập yêu cầu: đi **Huế** 3N2Đ, 2 người, ngân sách ví dụ 6 triệu, thích di tích và ẩm thực.
4. Search Agent query POI từ SQLite; xe/phòng lấy mock và gắn nhãn rõ ràng.
5. Budget Agent tính breakdown (chi phí ăn và vé chưa rõ sẽ được nhận diện).
6. Itinerary Agent tạo timeline trên bản đồ; hiển thị tuyến `ESTIMATED` nếu chưa có Routes API.
7. Người dùng chỉnh một địa điểm → tạo `plan_version=2`; duyệt version 1 phải bị chặn.
8. Duyệt version 2 → Booking Agent tạo mock reservations; hiển thị trạng thái chứ không gọi là vé thật.
9. Demo lỗi: giả lập khách sạn thất bại sau khi vé xe mock thành công → `PARTIALLY_BOOKED`.
10. Thử double-click, timeout và restart khi chờ approval để chứng minh an toàn.

---

## 16. PROMPTS GIAO VIỆC CHO CODEX — COPY TỪNG PHASE

### 16.1. Prompt bắt đầu (bắt buộc cho lần đầu)

```text
Bạn đang trong repo Travel Multi-Agent. Đọc toàn bộ IMPLEMENTATION_PLAN.md.
Mục tiêu là hệ thống đúng 5 Agent du lịch Huế, DATA-FIRST.
Nguồn POI thật là backend/data/hue.sqlite với bảng places. CẤM tạo fixture
địa điểm nếu đã có dữ liệu trong SQLite. Mở SQLite ở read-only mode.
Không tự nghĩ thêm cột; kiểm tra SQLite schema trước khi code.
Vé xe và khách sạn CHƯA có trong SQLite, dùng mock providers có nhãn MOCK.
Không dùng LLM để tính tiền hoặc xác nhận booking.
Bây giờ CHỈ triển khai PHASE 0. Tạo code, script audit và test tương ứng.
Sau khi chạy, báo danh sách file mới, kết quả test, và các giới hạn còn lại.
Không tự làm PHASE 1 khi PHASE 0 chưa được review.
```

### 16.2. Prompt phase tiếp theo

```text
Đọc IMPLEMENTATION_PLAN.md và code hiện có.
Triển khai PHASE [N] đúng theo checklist / Data Contracts / Done.
Không đổi schema hue.sqlite, không hardcode dữ liệu POI giả.
Giữ 5 Agent và ranh giới giữa SQLite POI và Postgres nghiệp vụ.
Viết unit tests + integration tests cần thiết. Chạy pytest -q.
Nếu dữ liệu thiếu giá/giờ, trả UNKNOWN và warning, không tự tạo thông tin.
Báo thay đổi, output API, các test pass/fail và việc chưa hoàn tất.
```

### 16.3. Prompt kiểm tra chất lượng sau mỗi phase

```text
Review implementation theo IMPLEMENTATION_PLAN.md.
Kiểm tra: đọc hue.sqlite read-only, POI ID thật, JSON parse an toàn,
không chế giá hay giờ mở, budget đúng unit và integer VND,
phân biệt QUOTED/ESTIMATED/UNKNOWN, booking yêu cầu approval,
idempotency, plan_version, xử lý partial/timeout, không leak API key.
Chạy test, liệt kê bug theo mức độ quan trọng và sửa các bug có thể kiểm chứng.
```

### 16.4. Prompt riêng cho Search Agent

```text
Triển khai Search Agent dựa trên 1.587 places trong hue.sqlite.
Tìm tên tiếng Việt có/không dấu, filter 8 category thực tế, cho phép search
các trường name, address, summary, source type. Dùng RapidFuzz và Haversine.
Trả về POI ID thật + source_url + collected_at + confidence.
Khách sạn/vé xe dùng provider adapters tách biệt, mock rõ ràng.
Viết test không bịa địa điểm và không trộn POI với booking offer.
```

### 16.5. Prompt riêng cho Itinerary Agent

```text
Dựa trên các POI lấy qua HuePlacesRepository, xây lịch trình tại Huế
với visit_minutes, opening_hours_raw, lat/lon và meal slots.
Dùng greedy + nearest neighbor, time-window validation và estimated route.
Không suy ra giờ mở chính xác theo từng ngày khi dữ liệu nguồn không ghi ngày.
Không gán thời gian đường bộ thực cho Haversine. Trả timeline, warnings,
route confidence và test xung đột.
```

---

## 17. BÀI TOÁN MỞ RỘNG SAU MVP

- **Thêm tỉnh/thành:** chuẩn hóa `PlaceRepository` interface theo city, thêm dataset/ingestion job; không làm “Huế → cả Việt Nam” chỉ bằng đổi prompt.
- **Refresh dữ liệu Huế:** xây pipeline thu thập *sau khi xác minh quyền sử dụng*, có `snapshot_version`, compare/dedupe và cập nhật nguồn; không ghi thẳng file nguồn trong thời gian serving.
- **FTS5** nếu benchmark cần: chỉ mục riêng hoặc bản sao được phép cập nhật; không làm thay đổi bản gốc.
- **Routing thật:** Routes API; caching theo cặp tọa độ/mode/time bucket; rà soát giá và hạn mức API.
- **Vector search/RAG:** chỉ thêm khi có corpus mô tả lớn, yêu cầu truy vấn ngữ nghĩa, và đã benchmark lợi ích. Không bắt buộc cho 1.587 bản ghi.
- **OR-Tools CP-SAT:** tối ưu chọn dịch vụ khi tổ hợp tăng; VRPTW/time windows khi itinerary phức tạp.
- **Booking thật:** nhà cung cấp phải cấp API và quyền create/modify/cancel; payment theo integration được phép; thêm đối soát webhook và chính sách hoàn/hủy.

---

## 18. TÀI LIỆU THAM KHẢO CHÍNH THỨC

- LangGraph: https://docs.langchain.com/oss/python/langgraph/overview
- LangGraph interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts
- OpenAI Structured Outputs: https://developers.openai.com/api/docs/guides/structured-outputs
- FastAPI & SQL database: https://fastapi.tiangolo.com/tutorial/sql-databases/
- SQLite FTS5: https://www.sqlite.org/fts5.html
- Google OR-Tools Routing: https://developers.google.com/optimization/routing
- Google Routes API: https://developers.google.com/maps/documentation/routes

---

## 19. FINAL CHECKLIST — CHỈ TUYÊN BỐ HOÀN THÀNH KHI

- [ ] Dùng `hue.sqlite` thật, 1.587 POI từ source, không hardcode địa điểm giả.
- [ ] Database SQLite mở read-only, nguồn vẫn nguyên vẹn.
- [ ] Tìm theo tên có/không dấu, 8 category, vị trí, sở thích.
- [ ] Lịch trình dùng `poi_id` hợp lệ và có cảnh báo giờ/ETA thiếu tin cậy.
- [ ] Dự toán tách giá provider, ước lượng và chi phí chưa rõ.
- [ ] Có đúng 5 Agent và LangGraph điều phối.
- [ ] Có lưu/version plan, approval, booking và log vào PostgreSQL.
- [ ] Không thể booking trước duyệt; double click không đặt trùng.
- [ ] Mock booking có nhãn; dữ liệu POI không biến thành API đặt chỗ giả.
- [ ] Đã chạy unit/integration/e2e và demo thất bại một phần.
- [ ] Quyền sử dụng dữ liệu/ảnh được xem xét trước khi public.

**Bước làm ngay:** PHASE 0 → PHASE 1 → PHASE 2. Khi có tìm kiếm địa điểm Huế hoạt động bằng dữ liệu thật, mới tiếp tục 3 Agent lập kế hoạch và Booking Agent. Đây là thay đổi tối ưu quan trọng nhất so với kế hoạch cũ.
