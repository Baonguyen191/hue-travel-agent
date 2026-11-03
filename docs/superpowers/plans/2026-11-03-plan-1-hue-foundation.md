# Plan 1: Dữ liệu Huế và Validator (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng nền tảng kiểm chứng cho lịch trình do LLM sinh ra:
- POI Huế từ OpenStreetMap, lưu trong SQLite, có provenance.
- Hàm `validate_itinerary()` trả về các issue có vị trí cụ thể, để vòng repair biết chỗ cần sửa.

**Architecture:**
- **Python package `travel_agent`, chia module theo trách nhiệm:**
  - `domain`: model và parser giờ mở cửa.
  - `data`: OSM và repository.
  - `routing`: travel time.
  - `validation`: validator.
  - `cli`.
- **Cách module dùng nhau:** validator chỉ phụ thuộc hai Protocol là `PlaceLookup` và `TravelTimeProvider`. Nhờ vậy test dùng được stub, và sau này thay được bằng OSRM hoặc PostgreSQL mà không sửa domain logic.
- **Nguyên tắc xử lý dữ liệu thiếu:** dữ liệu thiếu hoặc không hiểu được thì trả `unknown` hoặc `estimated`. Không bao giờ đoán.

**Tech Stack:**
- Python 3.11.
- pydantic v2.
- stdlib: `sqlite3`, `urllib`, `argparse`.
- Công cụ dev: pytest, ruff, mypy (strict).

**Spec:**
- [TRAVEL_AI_AGENT_CLAUDE_BRIEF.md](../../../TRAVEL_AI_AGENT_CLAUDE_BRIEF.md)
- [2026-11-03-hue-planner-roadmap.md](2026-11-03-hue-planner-roadmap.md) (các quyết định bổ sung)

## Global Constraints

- **Python:** dùng `py -3.11` (máy có sẵn 3.11; mặc định 3.14 chưa chắc có wheel cho các thư viện ML/OR-Tools ở plan sau). Virtualenv ở `.venv`.
- **Dependency runtime:** chỉ `pydantic>=2.7`. Thêm dependency mới phải ghi lý do trong commit message.
- **Không bịa dữ liệu:**
  - `opening_hours` không parse được thì là `None` (unknown).
  - Travel time từ haversine luôn có `estimated=True`.
- **Provenance:** mọi `Place` có `source`, `source_place_id`, `license`, `collected_at`.
- **OSM:** license `ODbL-1.0`, attribution `© OpenStreetMap contributors`.
- **Overpass:** tải một lần, lưu file raw. Test không được gọi mạng.
- **Không commit:** `data/raw/`, `*.sqlite`, `.env`, `*.gguf`.
- **Ngôn ngữ:** message cho user và LLM bằng tiếng Việt; identifier trong code bằng tiếng Anh.
- **Trước mỗi commit:** chạy pass cả `ruff format src tests`, `ruff check --fix src tests`, `mypy src`, `pytest`.
- **Lệnh:** mọi lệnh chạy trong PowerShell ở thư mục gốc project.

## File Structure

```text
TravelAgent/
  pyproject.toml
  .gitignore
  README.md
  examples/hue_request.json
  src/travel_agent/
    __init__.py
    cli.py                        # argparse: fetch-osm, ingest-osm, places, validate
    domain/
      __init__.py
      models.py                   # Coordinates, Category, TravelMode, Pace, Place,
                                  # PlanRequest, PlannedStop, PlannedDay, Itinerary
      opening_hours.py            # parse_opening_hours -> WeeklyHours | None
    data/
      __init__.py
      osm.py                      # category_from_tags, build_overpass_query, places_from_overpass
      place_repository.py         # PlaceLookup, InMemoryPlaceRepository, SqlitePlaceRepository
    routing/
      __init__.py
      travel_time.py              # TravelLeg, TravelTimeProvider, haversine_m, HaversineEstimator
    validation/
      __init__.py
      report.py                   # Severity, IssueCode, Issue, ValidationReport
      validator.py                # validate_itinerary
  tests/
    __init__.py
    test_smoke.py
    test_cli.py
    fixtures/overpass_sample.json # dữ liệu giả cho test, KHÔNG phải dữ liệu thật
    domain/__init__.py
    domain/test_models.py
    domain/test_opening_hours.py
    routing/__init__.py
    routing/test_travel_time.py
    data/__init__.py
    data/test_osm.py
    data/test_place_repository.py
    validation/__init__.py
    validation/factories.py
    validation/test_validator_structure.py
    validation/test_validator_timing.py
```

---

### Task 1: Tạo project và repo riêng

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/travel_agent/__init__.py`
- Create: `tests/__init__.py`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Consumes: không có.
- Produces: package `travel_agent` có `__version__ = "0.1.0"`, lệnh console `travel-agent` trỏ tới `travel_agent.cli:main` (hàm này được tạo ở Task 8).

- [ ] **Step 1: (Khuyến nghị) chuyển project ra khỏi OneDrive**

  Lý do: OneDrive sẽ đồng bộ `.venv` và file model, và đường dẫn có dấu có thể làm hỏng tool ở plan sau. Nếu chuyển, làm thủ công ngoài agent: đóng VS Code, rồi chép thư mục `TravelAgent` sang `C:\dev\TravelAgent`. Mọi bước tiếp theo chạy tại thư mục gốc mới.

- [ ] **Step 2: Khởi tạo git repo riêng**

  Thư mục hiện nằm trong git repo của `C:\Users\baoba`. Tạo repo riêng:

  ```powershell
  git init -b main
  git rev-parse --show-toplevel
  ```

  Expected: lệnh thứ hai in ra đường dẫn của chính thư mục `TravelAgent`.

- [ ] **Step 3: Tạo `pyproject.toml`**

  ```toml
  [project]
  name = "travel-agent"
  version = "0.1.0"
  requires-python = ">=3.11"
  dependencies = ["pydantic>=2.7"]

  [project.optional-dependencies]
  dev = ["pytest>=8.0", "ruff>=0.6", "mypy>=1.10"]

  [project.scripts]
  travel-agent = "travel_agent.cli:main"

  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"

  [tool.hatch.build.targets.wheel]
  packages = ["src/travel_agent"]

  [tool.pytest.ini_options]
  testpaths = ["tests"]
  pythonpath = ["src", "."]

  [tool.ruff]
  line-length = 100
  target-version = "py311"
  src = ["src", "."]

  [tool.ruff.lint]
  select = ["E", "F", "I", "UP", "B"]

  [tool.mypy]
  strict = true
  plugins = ["pydantic.mypy"]
  ```

- [ ] **Step 4: Tạo `.gitignore`**

  ```gitignore
  .venv/
  __pycache__/
  *.pyc
  .pytest_cache/
  .mypy_cache/
  .ruff_cache/
  data/raw/
  data/*.sqlite
  *.gguf
  .env
  ```

- [ ] **Step 5: Viết test smoke và tạo package**

  Tạo file rỗng `tests/__init__.py`.

  Tạo `tests/test_smoke.py`:

  ```python
  import travel_agent


  def test_package_version() -> None:
      assert travel_agent.__version__ == "0.1.0"
  ```

  Tạo `src/travel_agent/__init__.py`:

  ```python
  __version__ = "0.1.0"
  ```

- [ ] **Step 6: Tạo venv và cài package**

  ```powershell
  py -3.11 -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -e ".[dev]"
  ```

  Expected: `Successfully installed ... travel-agent-0.1.0`.

- [ ] **Step 7: Chạy test**

  Run: `.venv\Scripts\python -m pytest -v`

  Expected: `test_package_version PASSED`.

- [ ] **Step 8: Commit**

  ```powershell
  .venv\Scripts\ruff format src tests
  .venv\Scripts\ruff check --fix src tests
  .venv\Scripts\mypy src
  git add pyproject.toml .gitignore src tests TRAVEL_AI_AGENT_CLAUDE_BRIEF.md docs
  git commit -m "chore: scaffold travel_agent package"
  ```

---

### Task 2: Domain models

**Files:**
- Create: `src/travel_agent/domain/__init__.py` (rỗng)
- Create: `src/travel_agent/domain/models.py`
- Create: `tests/domain/__init__.py` (rỗng)
- Test: `tests/domain/test_models.py`

**Interfaces:**
- Consumes: không có.
- Produces (mọi task sau dùng):
  - `Coordinates(lat: float, lon: float)`, frozen.
  - `Category`, một `StrEnum`: `attraction`, `museum`, `historic`, `viewpoint`, `restaurant`, `cafe`, `market`, `park`, `religious`.
  - `TravelMode`, một `StrEnum`: `walk`, `motorbike`, `car`.
  - `Pace`, một `StrEnum`: `relaxed`, `moderate`, `packed`.
  - `Place(id, name, category, coords, opening_hours_raw: str | None, source, source_place_id, license, collected_at: datetime)`, frozen.
  - `PlanRequest(city="hue", start_date, num_days: 1..7, day_start=08:00, day_end=21:00, travel_mode=motorbike, pace=moderate, interests: list[str])`.
  - `PlannedStop(place_id, arrive: time, depart: time, note: str | None)`.
  - `PlannedDay(date, stops: list[PlannedStop])`, cần ít nhất 1 stop.
  - `Itinerary(days: list[PlannedDay])`, cần ít nhất 1 ngày.

**Lưu ý thiết kế:** schema của `Itinerary` cố ý chỉ kiểm tra cấu trúc. Lỗi logic, ví dụ `depart <= arrive`, do validator báo kèm vị trí, nhờ vậy LLM sửa được. Nếu để pydantic từ chối, cả JSON sẽ hỏng mà không chỉ ra chỗ sai.

- [ ] **Step 1: Viết test (sẽ fail)**

  Tạo `tests/domain/__init__.py` rỗng. Tạo `tests/domain/test_models.py`:

  ```python
  import datetime as dt

  import pytest
  from pydantic import ValidationError

  from travel_agent.domain.models import Coordinates, Itinerary, PlanRequest


  def test_coordinates_reject_out_of_range_latitude() -> None:
      with pytest.raises(ValidationError):
          Coordinates(lat=91, lon=107.58)


  def test_plan_request_rejects_inverted_day_window() -> None:
      with pytest.raises(ValidationError, match="day_end must be after day_start"):
          PlanRequest(
              start_date=dt.date(2026, 11, 4),
              num_days=1,
              day_start=dt.time(18, 0),
              day_end=dt.time(8, 0),
          )


  def test_plan_request_rejects_more_than_seven_days() -> None:
      with pytest.raises(ValidationError):
          PlanRequest(start_date=dt.date(2026, 11, 4), num_days=8)


  def test_itinerary_parses_llm_json() -> None:
      raw = """
      {"days": [{"date": "2026-11-04",
                 "stops": [{"place_id": "osm:node/1", "arrive": "08:30", "depart": "10:00",
                            "note": "Phù hợp sở thích lịch sử"}]}]}
      """
      itinerary = Itinerary.model_validate_json(raw)
      assert itinerary.days[0].stops[0].arrive == dt.time(8, 30)
      assert itinerary.days[0].date == dt.date(2026, 11, 4)


  def test_itinerary_requires_at_least_one_day() -> None:
      with pytest.raises(ValidationError):
          Itinerary.model_validate({"days": []})
  ```

- [ ] **Step 2: Chạy test, xác nhận fail**

  Run: `.venv\Scripts\python -m pytest tests/domain/test_models.py -v`

  Expected: FAIL với `ModuleNotFoundError: No module named 'travel_agent.domain'`.

- [ ] **Step 3: Implement**

  Tạo `src/travel_agent/domain/__init__.py` rỗng. Tạo `src/travel_agent/domain/models.py`:

  ```python
  """Domain models cho lịch trình.

  Schema Itinerary cố ý chỉ kiểm tra cấu trúc. Lỗi logic (thời gian, giờ mở cửa...)
  do validator báo kèm vị trí để LLM sửa được.
  """

  from __future__ import annotations

  import datetime as dt
  from enum import StrEnum

  from pydantic import BaseModel, ConfigDict, Field, model_validator


  class Coordinates(BaseModel):
      model_config = ConfigDict(frozen=True)

      lat: float = Field(ge=-90, le=90)
      lon: float = Field(ge=-180, le=180)


  class Category(StrEnum):
      ATTRACTION = "attraction"
      MUSEUM = "museum"
      HISTORIC = "historic"
      VIEWPOINT = "viewpoint"
      RESTAURANT = "restaurant"
      CAFE = "cafe"
      MARKET = "market"
      PARK = "park"
      RELIGIOUS = "religious"


  class TravelMode(StrEnum):
      WALK = "walk"
      MOTORBIKE = "motorbike"
      CAR = "car"


  class Pace(StrEnum):
      RELAXED = "relaxed"
      MODERATE = "moderate"
      PACKED = "packed"


  class Place(BaseModel):
      model_config = ConfigDict(frozen=True)

      id: str = Field(min_length=1)
      name: str = Field(min_length=1)
      category: Category
      coords: Coordinates
      opening_hours_raw: str | None = None
      source: str = Field(min_length=1)
      source_place_id: str = Field(min_length=1)
      license: str = Field(min_length=1)
      collected_at: dt.datetime


  class PlanRequest(BaseModel):
      city: str = "hue"
      start_date: dt.date
      num_days: int = Field(ge=1, le=7)
      day_start: dt.time = dt.time(8, 0)
      day_end: dt.time = dt.time(21, 0)
      travel_mode: TravelMode = TravelMode.MOTORBIKE
      pace: Pace = Pace.MODERATE
      interests: list[str] = Field(default_factory=list)

      @model_validator(mode="after")
      def _day_window_is_positive(self) -> PlanRequest:
          if self.day_end <= self.day_start:
              raise ValueError("day_end must be after day_start")
          return self


  class PlannedStop(BaseModel):
      place_id: str = Field(min_length=1)
      arrive: dt.time
      depart: dt.time
      note: str | None = None


  class PlannedDay(BaseModel):
      date: dt.date
      stops: list[PlannedStop] = Field(min_length=1)


  class Itinerary(BaseModel):
      days: list[PlannedDay] = Field(min_length=1)
  ```

- [ ] **Step 4: Chạy test, xác nhận pass**

  Run: `.venv\Scripts\python -m pytest tests/domain/test_models.py -v`

  Expected: 5 passed.

- [ ] **Step 5: Commit**

  ```powershell
  .venv\Scripts\ruff format src tests
  .venv\Scripts\ruff check --fix src tests
  .venv\Scripts\mypy src
  .venv\Scripts\python -m pytest
  git add src/travel_agent/domain tests/domain
  git commit -m "feat: add itinerary domain models"
  ```

---

### Task 3: Parser `opening_hours` (tập con OSM)

**Files:**
- Create: `src/travel_agent/domain/opening_hours.py`
- Test: `tests/domain/test_opening_hours.py`

**Interfaces:**
- Consumes: không có.
- Produces:
  - `parse_opening_hours(raw: str | None) -> WeeklyHours | None`. Giá trị `None` nghĩa là unknown.
  - `WeeklyHours.covers(weekday: int, start: time, end: time) -> bool`. `weekday` dùng quy ước `date.weekday()`: 0 = thứ Hai.

**Quy tắc:**
- **Hỗ trợ:**
  - `24/7`
  - `Mo-Fr 08:00-17:00`
  - `Sa,Su 08:00-11:30,13:30-17:00`
  - `We off`
  - `06:00-22:00` (không ghi ngày = mọi ngày)
  - Nhiều rule nối bằng `;`. Rule sau ghi đè rule trước cho cùng ngày.
  - Ngày không được nhắc tới = đóng cửa (đúng ngữ nghĩa OSM).
- **Trả `None` (unknown) khi gặp:**
  - `PH`, `SH` (ngày lễ, ngày nghỉ học).
  - Khung giờ qua nửa đêm.
  - Tháng, tuần.
  - Comment trong ngoặc kép.
  - Giờ chỉ có 1 chữ số.

  Không hiểu chắc chắn thì không đoán.

- [ ] **Step 1: Viết test (sẽ fail)**

  `tests/domain/test_opening_hours.py`:

  ```python
  import datetime as dt

  import pytest

  from travel_agent.domain.opening_hours import parse_opening_hours

  MON, WED, SAT, SUN = 0, 2, 5, 6


  def t(text: str) -> dt.time:
      return dt.time.fromisoformat(text)


  @pytest.mark.parametrize(
      "raw",
      [
          None,
          "",
          "   ",
          "PH off",
          "Mo-Su 07:00-17:00; PH off",
          "Mo-Fr 18:00-02:00",
          "sunrise-sunset",
          'Mo-Su 07:00-17:00 "theo mùa"',
          "Jan-Mar 08:00-17:00",
          "Mo-Su 7:00-17:00",
      ],
  )
  def test_unsupported_or_missing_is_unknown(raw: str | None) -> None:
      assert parse_opening_hours(raw) is None


  def test_every_day_range() -> None:
      hours = parse_opening_hours("Mo-Su 07:00-17:30")
      assert hours is not None
      assert hours.covers(WED, t("08:00"), t("17:30"))
      assert not hours.covers(WED, t("06:30"), t("08:00"))
      assert not hours.covers(WED, t("17:00"), t("18:00"))


  def test_split_ranges_and_weekend_rule() -> None:
      hours = parse_opening_hours("Mo-Fr 08:00-11:30,13:30-17:00; Sa,Su 08:00-12:00")
      assert hours is not None
      assert hours.covers(WED, t("09:00"), t("11:00"))
      assert not hours.covers(WED, t("11:00"), t("14:00"))  # vắt qua giờ nghỉ trưa
      assert hours.covers(SAT, t("08:00"), t("12:00"))
      assert not hours.covers(SUN, t("13:00"), t("14:00"))


  def test_later_rule_overrides_with_day_off() -> None:
      hours = parse_opening_hours("Mo-Su 08:00-17:00; We off")
      assert hours is not None
      assert not hours.covers(WED, t("09:00"), t("10:00"))
      assert hours.covers(SAT, t("09:00"), t("10:00"))


  def test_unmentioned_day_is_closed() -> None:
      hours = parse_opening_hours("Mo-Fr 08:00-17:00")
      assert hours is not None
      assert not hours.covers(SAT, t("09:00"), t("10:00"))


  def test_times_without_days_apply_every_day() -> None:
      hours = parse_opening_hours("06:00-22:00")
      assert hours is not None
      assert all(hours.covers(day, t("06:00"), t("22:00")) for day in range(7))


  def test_wraparound_day_range() -> None:
      hours = parse_opening_hours("Sa-Mo 09:00-12:00")
      assert hours is not None
      assert hours.covers(SUN, t("09:00"), t("10:00"))
      assert hours.covers(MON, t("09:00"), t("10:00"))
      assert not hours.covers(WED, t("09:00"), t("10:00"))


  def test_always_open() -> None:
      hours = parse_opening_hours("24/7")
      assert hours is not None
      assert hours.covers(SUN, t("00:00"), t("23:59"))


  def test_closing_at_midnight() -> None:
      hours = parse_opening_hours("Mo-Su 18:00-24:00")
      assert hours is not None
      assert hours.covers(WED, t("22:00"), t("23:59"))
  ```

- [ ] **Step 2: Chạy test, xác nhận fail**

  Run: `.venv\Scripts\python -m pytest tests/domain/test_opening_hours.py -v`

  Expected: FAIL với `ModuleNotFoundError: No module named 'travel_agent.domain.opening_hours'`.

- [ ] **Step 3: Implement**

  `src/travel_agent/domain/opening_hours.py`:

  ```python
  """Parser cho một tập con cú pháp OSM `opening_hours`.

  Nguyên tắc: không hiểu chắc chắn thì trả None (unknown). Không bao giờ đoán giờ mở cửa.
  Hỗ trợ: "24/7", "Mo-Fr 08:00-17:00", "Sa,Su 08:00-11:30,13:30-17:00", "We off",
  "06:00-22:00" (mọi ngày), nhiều rule nối bằng ";" (rule sau ghi đè rule trước).
  Không hỗ trợ (trả None): ngày lễ PH/SH, khung giờ qua nửa đêm, tháng/tuần, comment.
  """

  from __future__ import annotations

  import datetime as dt
  import re
  from dataclasses import dataclass

  WEEKDAY_CODES = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
  _ALL_DAYS = tuple(range(7))
  _RANGE_RE = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")


  @dataclass(frozen=True)
  class TimeRange:
      start: dt.time
      end: dt.time


  @dataclass(frozen=True)
  class WeeklyHours:
      """Key = weekday (0 = thứ Hai, như `date.weekday()`). Ngày không có key = đóng cửa."""

      by_weekday: dict[int, tuple[TimeRange, ...]]

      def covers(self, weekday: int, start: dt.time, end: dt.time) -> bool:
          ranges = self.by_weekday.get(weekday, ())
          return any(r.start <= start and end <= r.end for r in ranges)


  def parse_opening_hours(raw: str | None) -> WeeklyHours | None:
      if raw is None:
          return None
      text = raw.strip()
      if not text:
          return None
      if text == "24/7":
          always = (TimeRange(dt.time(0, 0), dt.time.max),)
          return WeeklyHours({day: always for day in _ALL_DAYS})
      by_weekday: dict[int, tuple[TimeRange, ...]] = {}
      for rule in text.split(";"):
          rule_text = rule.strip()
          if not rule_text:
              continue
          parsed = _parse_rule(rule_text)
          if parsed is None:
              return None
          days, ranges = parsed
          for day in days:
              by_weekday[day] = ranges
      if not by_weekday:
          return None
      return WeeklyHours(by_weekday)


  def _parse_rule(rule: str) -> tuple[tuple[int, ...], tuple[TimeRange, ...]] | None:
      days: tuple[int, ...] | None
      if rule[0].isdigit():
          days, times_text = _ALL_DAYS, rule
      else:
          day_spec, _, rest = rule.partition(" ")
          days, times_text = _parse_days(day_spec), rest.strip()
      if days is None or not times_text:
          return None
      if times_text in ("off", "closed"):
          return days, ()
      ranges: list[TimeRange] = []
      for chunk in times_text.split(","):
          time_range = _parse_range(chunk.strip())
          if time_range is None:
              return None
          ranges.append(time_range)
      return days, tuple(ranges)


  def _parse_days(spec: str) -> tuple[int, ...] | None:
      days: list[int] = []
      for part in spec.split(","):
          first, sep, last = part.partition("-")
          if first not in WEEKDAY_CODES or (sep and last not in WEEKDAY_CODES):
              return None
          start = WEEKDAY_CODES.index(first)
          if not sep:
              days.append(start)
              continue
          end = WEEKDAY_CODES.index(last)
          if start <= end:
              days.extend(range(start, end + 1))
          else:  # vòng qua cuối tuần, ví dụ "Sa-Mo"
              days.extend([*range(start, 7), *range(0, end + 1)])
      return tuple(days)


  def _parse_range(text: str) -> TimeRange | None:
      match = _RANGE_RE.match(text)
      if match is None:
          return None
      h1, m1, h2, m2 = (int(group) for group in match.groups())
      if h1 > 23 or m1 > 59 or h2 > 24 or m2 > 59:
          return None
      start = dt.time(h1, m1)
      if h2 == 24:
          if m2 != 0:
              return None
          end = dt.time.max
      else:
          end = dt.time(h2, m2)
      if end <= start:
          return None  # khung qua nửa đêm: chưa hỗ trợ -> unknown
      return TimeRange(start, end)
  ```

- [ ] **Step 4: Chạy test, xác nhận pass**

  Run: `.venv\Scripts\python -m pytest tests/domain/test_opening_hours.py -v`

  Expected: 18 passed (10 case tham số hóa + 8 test).

- [ ] **Step 5: Commit**

  ```powershell
  .venv\Scripts\ruff format src tests
  .venv\Scripts\ruff check --fix src tests
  .venv\Scripts\mypy src
  .venv\Scripts\python -m pytest
  git add src/travel_agent/domain/opening_hours.py tests/domain/test_opening_hours.py
  git commit -m "feat: parse safe subset of OSM opening_hours"
  ```

---

### Task 4: Travel time (interface và ước tính haversine)

**Files:**
- Create: `src/travel_agent/routing/__init__.py` (rỗng)
- Create: `src/travel_agent/routing/travel_time.py`
- Create: `tests/routing/__init__.py` (rỗng)
- Test: `tests/routing/test_travel_time.py`

**Interfaces:**
- Consumes: `Coordinates`, `TravelMode` (Task 2).
- Produces:
  - `TravelLeg(distance_m: float, minutes: float, estimated: bool, source: str)`, frozen.
  - `TravelTimeProvider`, một Protocol: `travel_leg(origin: Coordinates, destination: Coordinates, mode: TravelMode) -> TravelLeg`.
  - `haversine_m(a: Coordinates, b: Coordinates) -> float`.
  - `HaversineEstimator`: hiện thực `TravelTimeProvider`, `source="haversine_estimate"`, luôn `estimated=True`.

**Về các hằng số:** tốc độ (đi bộ 4,5 km/h, xe máy 22 km/h, ô tô 20 km/h), hệ số đường vòng 1,3 và thời gian khởi hành (xe máy 5 phút, ô tô 8 phút) là **giả định chưa đo**. Docstring phải ghi rõ điều này. OSRM thật sẽ thay ở plan sau.

- [ ] **Step 1: Viết test (sẽ fail)**

  Tạo `tests/routing/__init__.py` rỗng. Tạo `tests/routing/test_travel_time.py`:

  ```python
  import pytest

  from travel_agent.domain.models import Coordinates, TravelMode
  from travel_agent.routing.travel_time import HaversineEstimator, haversine_m

  A = Coordinates(lat=16.47, lon=107.58)
  B = Coordinates(lat=16.48, lon=107.58)


  def test_one_degree_latitude_is_about_111_km() -> None:
      distance = haversine_m(Coordinates(lat=0, lon=0), Coordinates(lat=1, lon=0))
      assert distance == pytest.approx(111_195, abs=1)


  def test_same_point_takes_no_time() -> None:
      leg = HaversineEstimator().travel_leg(A, A, TravelMode.MOTORBIKE)
      assert leg.minutes == 0
      assert leg.estimated


  def test_walking_leg_uses_detour_factor_and_speed() -> None:
      leg = HaversineEstimator().travel_leg(A, B, TravelMode.WALK)
      road = haversine_m(A, B) * 1.3
      assert leg.distance_m == pytest.approx(road)
      assert leg.minutes == pytest.approx(road / 1000 / 4.5 * 60)
      assert leg.estimated
      assert leg.source == "haversine_estimate"


  def test_motorbike_adds_start_overhead() -> None:
      leg = HaversineEstimator().travel_leg(A, B, TravelMode.MOTORBIKE)
      road = haversine_m(A, B) * 1.3
      assert leg.minutes == pytest.approx(road / 1000 / 22.0 * 60 + 5.0)
  ```

- [ ] **Step 2: Chạy test, xác nhận fail**

  Run: `.venv\Scripts\python -m pytest tests/routing -v`

  Expected: FAIL với `ModuleNotFoundError: No module named 'travel_agent.routing'`.

- [ ] **Step 3: Implement**

  Tạo `src/travel_agent/routing/__init__.py` rỗng. Tạo `src/travel_agent/routing/travel_time.py`:

  ```python
  """Travel time providers. Domain logic chỉ phụ thuộc `TravelTimeProvider`."""

  from __future__ import annotations

  import math
  from typing import Protocol

  from pydantic import BaseModel, ConfigDict

  from travel_agent.domain.models import Coordinates, TravelMode

  EARTH_RADIUS_M = 6_371_000.0


  class TravelLeg(BaseModel):
      model_config = ConfigDict(frozen=True)

      distance_m: float
      minutes: float
      estimated: bool
      source: str


  class TravelTimeProvider(Protocol):
      def travel_leg(
          self, origin: Coordinates, destination: Coordinates, mode: TravelMode
      ) -> TravelLeg: ...


  def haversine_m(a: Coordinates, b: Coordinates) -> float:
      phi1, phi2 = math.radians(a.lat), math.radians(b.lat)
      d_phi = phi2 - phi1
      d_lambda = math.radians(b.lon - a.lon)
      h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
      return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


  class HaversineEstimator:
      """Ước tính thô từ khoảng cách đường chim bay. KHÔNG phải dữ liệu routing.

      Tốc độ, hệ số đường vòng và thời gian khởi hành là giả định nội bộ cho đô thị Huế,
      chưa được đo. Kết quả luôn có `estimated=True` để validator và UI gắn nhãn ước tính.
      """

      SOURCE = "haversine_estimate"
      DETOUR_FACTOR = 1.3
      SPEED_KMH: dict[TravelMode, float] = {
          TravelMode.WALK: 4.5,
          TravelMode.MOTORBIKE: 22.0,
          TravelMode.CAR: 20.0,
      }
      START_OVERHEAD_MIN: dict[TravelMode, float] = {
          TravelMode.WALK: 0.0,
          TravelMode.MOTORBIKE: 5.0,
          TravelMode.CAR: 8.0,
      }

      def travel_leg(
          self, origin: Coordinates, destination: Coordinates, mode: TravelMode
      ) -> TravelLeg:
          road_m = haversine_m(origin, destination) * self.DETOUR_FACTOR
          if road_m == 0:
              return TravelLeg(distance_m=0.0, minutes=0.0, estimated=True, source=self.SOURCE)
          minutes = road_m / 1000 / self.SPEED_KMH[mode] * 60 + self.START_OVERHEAD_MIN[mode]
          return TravelLeg(distance_m=road_m, minutes=minutes, estimated=True, source=self.SOURCE)
  ```

- [ ] **Step 4: Chạy test, xác nhận pass**

  Run: `.venv\Scripts\python -m pytest tests/routing -v`

  Expected: 4 passed.

- [ ] **Step 5: Commit**

  ```powershell
  .venv\Scripts\ruff format src tests
  .venv\Scripts\ruff check --fix src tests
  .venv\Scripts\mypy src
  .venv\Scripts\python -m pytest
  git add src/travel_agent/routing tests/routing
  git commit -m "feat: add travel time provider interface and haversine estimate"
  ```

---

### Task 5: Chuyển dữ liệu OSM thành Place và lưu SQLite

**Files:**
- Create: `src/travel_agent/data/__init__.py` (rỗng)
- Create: `src/travel_agent/data/osm.py`
- Create: `src/travel_agent/data/place_repository.py`
- Create: `tests/data/__init__.py` (rỗng)
- Create: `tests/fixtures/overpass_sample.json`
- Test: `tests/data/test_osm.py`
- Test: `tests/data/test_place_repository.py`

**Interfaces:**
- Consumes: `Place`, `Category`, `Coordinates` (Task 2).
- Produces:
  - `OSM_LICENSE = "ODbL-1.0"`, `OSM_ATTRIBUTION = "© OpenStreetMap contributors"`.
  - `category_from_tags(tags: Mapping[str, str]) -> Category | None`.
  - `build_overpass_query(bbox: tuple[float, float, float, float]) -> str`. Thứ tự bbox: (south, west, north, east).
  - `places_from_overpass(payload: Mapping[str, Any], collected_at: datetime) -> list[Place]`. Id có dạng `osm:{type}/{id}`, ví dụ `osm:node/123`.
  - `PlaceLookup`, một Protocol: `get(place_id: str) -> Place | None`.
  - `InMemoryPlaceRepository(places: Iterable[Place])`.
  - `SqlitePlaceRepository(path)` với các method:
    - `upsert_many(places) -> int`
    - `get(place_id) -> Place | None`
    - `list_places(category: Category | None = None, limit: int = 50) -> list[Place]` (sắp theo tên)
    - `count_by_category() -> dict[Category, int]`
    - `close()`

**Thứ tự ưu tiên khi gán category:**
1. Theo `amenity`:
   - `restaurant`, `fast_food` → `restaurant`
   - `cafe` → `cafe`
   - `marketplace` → `market`
   - `place_of_worship` → `religious`
2. Theo `tourism`: `museum` → `museum`, `viewpoint` → `viewpoint`.
3. Có tag `historic` → `historic`.
4. `leisure=park` → `park`.
5. `tourism=attraction` → `attraction`.
6. Không khớp rule nào → bỏ qua phần tử.

Phần tử không có tên, hoặc không có tọa độ (way/relation thiếu `center`), cũng bị bỏ qua.

- [ ] **Step 1: Tạo fixture (dữ liệu giả, chỉ dùng cho test)**

  `tests/fixtures/overpass_sample.json`:

  ```json
  {
    "osm3s": {"timestamp_osm_base": "2026-11-03T08:00:00Z"},
    "elements": [
      {"type": "node", "id": 1, "lat": 16.47, "lon": 107.58,
       "tags": {"name": "Bảo tàng Mẫu", "tourism": "museum", "opening_hours": "Mo-Su 07:00-17:00"}},
      {"type": "way", "id": 2, "center": {"lat": 16.46, "lon": 107.59},
       "tags": {"name": "Cafe Mẫu", "amenity": "cafe"}},
      {"type": "node", "id": 3, "lat": 16.45, "lon": 107.57,
       "tags": {"tourism": "attraction"}},
      {"type": "node", "id": 4, "lat": 16.44, "lon": 107.56,
       "tags": {"name": "Tạp hóa Mẫu", "shop": "convenience"}},
      {"type": "relation", "id": 5,
       "tags": {"name": "Lăng Mẫu", "historic": "tomb"}},
      {"type": "node", "id": 6, "lat": 16.43, "lon": 107.55,
       "tags": {"name": " Quán Mẫu ", "amenity": "restaurant"}}
    ]
  }
  ```

- [ ] **Step 2: Viết test OSM (sẽ fail)**

  Tạo `tests/data/__init__.py` rỗng. Tạo `tests/data/test_osm.py`:

  ```python
  import datetime as dt
  import json
  from pathlib import Path

  from travel_agent.data.osm import build_overpass_query, category_from_tags, places_from_overpass
  from travel_agent.domain.models import Category, Place

  FIXTURE = Path(__file__).parent.parent / "fixtures" / "overpass_sample.json"
  COLLECTED = dt.datetime(2026, 11, 3, tzinfo=dt.UTC)


  def load_places() -> list[Place]:
      payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
      return places_from_overpass(payload, COLLECTED)


  def test_keeps_only_named_categorised_elements_with_position() -> None:
      assert sorted(p.id for p in load_places()) == ["osm:node/1", "osm:node/6", "osm:way/2"]


  def test_maps_fields_and_provenance() -> None:
      museum = next(p for p in load_places() if p.id == "osm:node/1")
      assert museum.category is Category.MUSEUM
      assert museum.opening_hours_raw == "Mo-Su 07:00-17:00"
      assert museum.source == "osm"
      assert museum.source_place_id == "node/1"
      assert museum.license == "ODbL-1.0"
      assert museum.collected_at == COLLECTED


  def test_way_uses_center_and_name_is_trimmed() -> None:
      places = {p.id: p for p in load_places()}
      assert places["osm:way/2"].coords.lat == 16.46
      assert places["osm:node/6"].name == "Quán Mẫu"
      assert places["osm:node/6"].opening_hours_raw is None


  def test_category_priority() -> None:
      religious = category_from_tags({"amenity": "place_of_worship", "historic": "yes"})
      assert religious is Category.RELIGIOUS
      assert category_from_tags({"tourism": "attraction", "historic": "tomb"}) is Category.HISTORIC
      assert category_from_tags({"shop": "convenience"}) is None


  def test_query_contains_bbox_and_center_output() -> None:
      query = build_overpass_query((16.36, 107.5, 16.58, 107.7))
      assert "(16.36,107.5,16.58,107.7)" in query
      assert "out center tags;" in query
  ```

- [ ] **Step 3: Viết test repository (sẽ fail)**

  `tests/data/test_place_repository.py`:

  ```python
  import datetime as dt
  from pathlib import Path

  from travel_agent.data.place_repository import SqlitePlaceRepository
  from travel_agent.domain.models import Category, Coordinates, Place

  COLLECTED = dt.datetime(2026, 11, 3, 8, 0, tzinfo=dt.UTC)


  def make_place(pid: str, category: Category, name: str = "Mẫu", hours: str | None = None) -> Place:
      return Place(
          id=pid,
          name=name,
          category=category,
          coords=Coordinates(lat=16.47, lon=107.58),
          opening_hours_raw=hours,
          source="osm",
          source_place_id=pid.removeprefix("osm:"),
          license="ODbL-1.0",
          collected_at=COLLECTED,
      )


  def test_roundtrip(tmp_path: Path) -> None:
      repo = SqlitePlaceRepository(tmp_path / "places.sqlite")
      original = make_place("osm:node/1", Category.MUSEUM, hours="Mo-Su 07:00-17:00")
      repo.upsert_many([original])
      assert repo.get("osm:node/1") == original
      assert repo.get("osm:node/404") is None
      repo.close()


  def test_upsert_updates_existing(tmp_path: Path) -> None:
      repo = SqlitePlaceRepository(tmp_path / "places.sqlite")
      repo.upsert_many([make_place("osm:node/1", Category.MUSEUM, name="Cũ")])
      repo.upsert_many([make_place("osm:node/1", Category.MUSEUM, name="Mới")])
      place = repo.get("osm:node/1")
      assert place is not None
      assert place.name == "Mới"
      repo.close()


  def test_list_filters_by_category_sorted_by_name_and_counts(tmp_path: Path) -> None:
      repo = SqlitePlaceRepository(tmp_path / "places.sqlite")
      repo.upsert_many(
          [
              make_place("osm:node/1", Category.CAFE, name="B"),
              make_place("osm:node/2", Category.CAFE, name="A"),
              make_place("osm:node/3", Category.MUSEUM),
          ]
      )
      assert [p.id for p in repo.list_places(Category.CAFE)] == ["osm:node/2", "osm:node/1"]
      assert repo.count_by_category() == {Category.CAFE: 2, Category.MUSEUM: 1}
      repo.close()
  ```

- [ ] **Step 4: Chạy test, xác nhận fail**

  Run: `.venv\Scripts\python -m pytest tests/data -v`

  Expected: FAIL với `ModuleNotFoundError: No module named 'travel_agent.data'`.

- [ ] **Step 5: Implement `osm.py`**

  Tạo `src/travel_agent/data/__init__.py` rỗng. Tạo `src/travel_agent/data/osm.py`:

  ```python
  """Chuyển dữ liệu OpenStreetMap (Overpass JSON) thành `Place`.

  Dữ liệu OSM theo giấy phép ODbL-1.0: khi hiển thị phải ghi "© OpenStreetMap contributors".
  """

  from __future__ import annotations

  import datetime as dt
  from collections.abc import Mapping
  from typing import Any

  from travel_agent.domain.models import Category, Coordinates, Place

  OSM_LICENSE = "ODbL-1.0"
  OSM_ATTRIBUTION = "© OpenStreetMap contributors"

  _AMENITY_CATEGORIES: dict[str, Category] = {
      "restaurant": Category.RESTAURANT,
      "fast_food": Category.RESTAURANT,
      "cafe": Category.CAFE,
      "marketplace": Category.MARKET,
      "place_of_worship": Category.RELIGIOUS,
  }


  def category_from_tags(tags: Mapping[str, str]) -> Category | None:
      amenity = _AMENITY_CATEGORIES.get(tags.get("amenity", ""))
      if amenity is not None:
          return amenity
      tourism = tags.get("tourism")
      if tourism == "museum":
          return Category.MUSEUM
      if tourism == "viewpoint":
          return Category.VIEWPOINT
      if "historic" in tags:
          return Category.HISTORIC
      if tags.get("leisure") == "park":
          return Category.PARK
      if tourism == "attraction":
          return Category.ATTRACTION
      return None


  def build_overpass_query(bbox: tuple[float, float, float, float]) -> str:
      """bbox = (south, west, north, east), đúng thứ tự Overpass."""
      south, west, north, east = bbox
      box = f"{south},{west},{north},{east}"
      return (
          "[out:json][timeout:180];\n"
          "(\n"
          f'  nwr["tourism"~"^(attraction|museum|viewpoint)$"]({box});\n'
          f'  nwr["historic"]({box});\n'
          f'  nwr["amenity"~"^(restaurant|fast_food|cafe|marketplace|place_of_worship)$"]({box});\n'
          f'  nwr["leisure"="park"]({box});\n'
          ");\n"
          "out center tags;\n"
      )


  def places_from_overpass(payload: Mapping[str, Any], collected_at: dt.datetime) -> list[Place]:
      places: dict[str, Place] = {}
      for element in payload.get("elements", []):
          place = _place_from_element(element, collected_at)
          if place is not None:
              places[place.id] = place
      return list(places.values())


  def _place_from_element(element: Mapping[str, Any], collected_at: dt.datetime) -> Place | None:
      tags: Mapping[str, str] = element.get("tags") or {}
      name = (tags.get("name") or "").strip()
      category = category_from_tags(tags)
      if not name or category is None:
          return None
      position: Mapping[str, Any] = (
          element if element.get("type") == "node" else (element.get("center") or {})
      )
      lat, lon = position.get("lat"), position.get("lon")
      if lat is None or lon is None:
          return None
      source_place_id = f"{element['type']}/{element['id']}"
      opening_hours = (tags.get("opening_hours") or "").strip() or None
      return Place(
          id=f"osm:{source_place_id}",
          name=name,
          category=category,
          coords=Coordinates(lat=lat, lon=lon),
          opening_hours_raw=opening_hours,
          source="osm",
          source_place_id=source_place_id,
          license=OSM_LICENSE,
          collected_at=collected_at,
      )
  ```

- [ ] **Step 6: Implement `place_repository.py`**

  `src/travel_agent/data/place_repository.py`:

  ```python
  """Lưu trữ Place. Validator chỉ phụ thuộc Protocol `PlaceLookup`."""

  from __future__ import annotations

  import datetime as dt
  import sqlite3
  from collections.abc import Iterable
  from pathlib import Path
  from typing import Any, Protocol

  from travel_agent.domain.models import Category, Coordinates, Place

  _SCHEMA = """
  CREATE TABLE IF NOT EXISTS places (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      category TEXT NOT NULL,
      lat REAL NOT NULL,
      lon REAL NOT NULL,
      opening_hours_raw TEXT,
      source TEXT NOT NULL,
      source_place_id TEXT NOT NULL,
      license TEXT NOT NULL,
      collected_at TEXT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_places_category ON places (category);
  """

  _COLUMNS = (
      "id, name, category, lat, lon, opening_hours_raw, "
      "source, source_place_id, license, collected_at"
  )

  _UPSERT = (
      f"INSERT INTO places ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
      "ON CONFLICT(id) DO UPDATE SET name=excluded.name, category=excluded.category, "
      "lat=excluded.lat, lon=excluded.lon, opening_hours_raw=excluded.opening_hours_raw, "
      "source=excluded.source, source_place_id=excluded.source_place_id, "
      "license=excluded.license, collected_at=excluded.collected_at"
  )


  class PlaceLookup(Protocol):
      def get(self, place_id: str) -> Place | None: ...


  class InMemoryPlaceRepository:
      def __init__(self, places: Iterable[Place]) -> None:
          self._by_id = {place.id: place for place in places}

      def get(self, place_id: str) -> Place | None:
          return self._by_id.get(place_id)


  class SqlitePlaceRepository:
      def __init__(self, path: str | Path) -> None:
          self._conn = sqlite3.connect(str(path))
          self._conn.executescript(_SCHEMA)

      def close(self) -> None:
          self._conn.close()

      def upsert_many(self, places: Iterable[Place]) -> int:
          rows = [_to_row(place) for place in places]
          with self._conn:
              self._conn.executemany(_UPSERT, rows)
          return len(rows)

      def get(self, place_id: str) -> Place | None:
          row = self._conn.execute(
              f"SELECT {_COLUMNS} FROM places WHERE id = ?", (place_id,)
          ).fetchone()
          return None if row is None else _from_row(row)

      def list_places(self, category: Category | None = None, limit: int = 50) -> list[Place]:
          if category is None:
              cursor = self._conn.execute(
                  f"SELECT {_COLUMNS} FROM places ORDER BY name LIMIT ?", (limit,)
              )
          else:
              cursor = self._conn.execute(
                  f"SELECT {_COLUMNS} FROM places WHERE category = ? ORDER BY name LIMIT ?",
                  (category.value, limit),
              )
          return [_from_row(row) for row in cursor.fetchall()]

      def count_by_category(self) -> dict[Category, int]:
          rows = self._conn.execute(
              "SELECT category, COUNT(*) FROM places GROUP BY category"
          ).fetchall()
          return {Category(category): count for category, count in rows}


  def _to_row(place: Place) -> tuple[Any, ...]:
      return (
          place.id,
          place.name,
          place.category.value,
          place.coords.lat,
          place.coords.lon,
          place.opening_hours_raw,
          place.source,
          place.source_place_id,
          place.license,
          place.collected_at.isoformat(),
      )


  def _from_row(row: tuple[Any, ...]) -> Place:
      (pid, name, category, lat, lon, hours, source, source_place_id, license_, collected) = row
      return Place(
          id=pid,
          name=name,
          category=Category(category),
          coords=Coordinates(lat=lat, lon=lon),
          opening_hours_raw=hours,
          source=source,
          source_place_id=source_place_id,
          license=license_,
          collected_at=dt.datetime.fromisoformat(collected),
      )
  ```

- [ ] **Step 7: Chạy test, xác nhận pass**

  Run: `.venv\Scripts\python -m pytest tests/data -v`

  Expected: 8 passed.

- [ ] **Step 8: Commit**

  ```powershell
  .venv\Scripts\ruff format src tests
  .venv\Scripts\ruff check --fix src tests
  .venv\Scripts\mypy src
  .venv\Scripts\python -m pytest
  git add src/travel_agent/data tests/data tests/fixtures
  git commit -m "feat: ingest OSM places with provenance into SQLite"
  ```

---

### Task 6: Validator, phần cấu trúc

**Files:**
- Create: `src/travel_agent/validation/__init__.py` (rỗng)
- Create: `src/travel_agent/validation/report.py`
- Create: `src/travel_agent/validation/validator.py`
- Create: `tests/validation/__init__.py` (rỗng)
- Create: `tests/validation/factories.py`
- Test: `tests/validation/test_validator_structure.py`

**Interfaces:**
- Consumes:
  - `PlanRequest`, `Itinerary`, `PlannedStop`, `Place` (Task 2).
  - `PlaceLookup`, `InMemoryPlaceRepository` (Task 5).
  - `TravelTimeProvider`, `TravelLeg` (Task 4).
- Produces:
  - `Severity`, một `StrEnum`: `error` (không được trả plan cho user), `warning` (dùng được nhưng phải hiển thị cảnh báo).
  - `IssueCode`, một `StrEnum`: `unknown_place`, `duplicate_place`, `day_count_mismatch`, `date_mismatch`, `stop_time_order`, `outside_day_window`, `stop_overlap`, `travel_time_insufficient`, `closed_during_visit`, `opening_hours_unknown`, `overloaded_day`, `missing_meal`.
  - `Issue(code, severity, message, day_index: int | None, stop_index: int | None, place_id: str | None)`.
  - `ValidationReport(issues: list[Issue], estimated_legs: int)`, có property `is_valid` và method `errors()`.
  - `validate_itinerary(request: PlanRequest, itinerary: Itinerary, places: PlaceLookup, travel: TravelTimeProvider) -> ValidationReport`.

  Ở task này `travel` chưa được dùng; Task 7 dùng. Signature cố định ngay từ đầu để các plan sau không phải sửa.

- [ ] **Step 1: Tạo test factories**

  Tạo `tests/validation/__init__.py` rỗng. Tạo `tests/validation/factories.py`:

  ```python
  """Dữ liệu giả cho test validator. Không phải dữ liệu thật của Huế."""

  import datetime as dt

  from travel_agent.data.place_repository import InMemoryPlaceRepository
  from travel_agent.domain.models import (
      Category,
      Coordinates,
      Itinerary,
      Pace,
      Place,
      PlannedDay,
      PlannedStop,
      PlanRequest,
      TravelMode,
  )
  from travel_agent.routing.travel_time import TravelLeg

  DAY1 = dt.date(2026, 11, 4)
  COLLECTED = dt.datetime(2026, 11, 3, tzinfo=dt.UTC)

  StopSpec = tuple[str, str, str]  # (place_id, arrive "HH:MM", depart "HH:MM")

  VALID_DAY: list[StopSpec] = [
      ("t:museum", "08:30", "10:30"),
      ("t:cafe", "10:45", "11:15"),
      ("t:lunch", "11:30", "12:30"),
      ("t:dinner", "18:00", "19:00"),
  ]


  def _place(pid: str, category: Category, lat: float, lon: float, hours: str | None) -> Place:
      return Place(
          id=pid,
          name=pid,
          category=category,
          coords=Coordinates(lat=lat, lon=lon),
          opening_hours_raw=hours,
          source="test",
          source_place_id=pid,
          license="test-only",
          collected_at=COLLECTED,
      )


  def sample_places() -> InMemoryPlaceRepository:
      return InMemoryPlaceRepository(
          [
              _place("t:museum", Category.MUSEUM, 16.4700, 107.5800, "Mo-Su 07:00-17:00"),
              _place("t:cafe", Category.CAFE, 16.4710, 107.5810, None),
              _place("t:lunch", Category.RESTAURANT, 16.4720, 107.5790, "Mo-Su 10:00-22:00"),
              _place("t:dinner", Category.RESTAURANT, 16.4690, 107.5820, "Mo-Su 16:00-22:00"),
              _place("t:viewpoint", Category.VIEWPOINT, 16.4680, 107.5830, "24/7"),
          ]
      )


  def make_request(num_days: int = 1, pace: Pace = Pace.MODERATE) -> PlanRequest:
      return PlanRequest(
          start_date=DAY1, num_days=num_days, pace=pace, travel_mode=TravelMode.MOTORBIKE
      )


  def make_day(stops: list[StopSpec], date: dt.date = DAY1) -> PlannedDay:
      return PlannedDay(
          date=date,
          stops=[
              PlannedStop(
                  place_id=pid,
                  arrive=dt.time.fromisoformat(arrive),
                  depart=dt.time.fromisoformat(depart),
              )
              for pid, arrive, depart in stops
          ],
      )


  def make_itinerary(*days: PlannedDay) -> Itinerary:
      return Itinerary(days=list(days))


  class FixedTravelTime:
      """Stub: mọi chặng tốn đúng `minutes` phút."""

      def __init__(self, minutes: float = 10.0, estimated: bool = False) -> None:
          self.minutes = minutes
          self.estimated = estimated

      def travel_leg(
          self, origin: Coordinates, destination: Coordinates, mode: TravelMode
      ) -> TravelLeg:
          return TravelLeg(
              distance_m=1000.0, minutes=self.minutes, estimated=self.estimated, source="fixed_test"
          )
  ```

- [ ] **Step 2: Viết test (sẽ fail)**

  `tests/validation/test_validator_structure.py`:

  ```python
  import datetime as dt

  from tests.validation.factories import (
      DAY1,
      VALID_DAY,
      FixedTravelTime,
      make_day,
      make_itinerary,
      make_request,
      sample_places,
  )
  from travel_agent.domain.models import Itinerary, PlanRequest
  from travel_agent.validation.report import IssueCode, ValidationReport
  from travel_agent.validation.validator import validate_itinerary


  def run(itinerary: Itinerary, request: PlanRequest | None = None) -> ValidationReport:
      return validate_itinerary(
          request or make_request(), itinerary, sample_places(), FixedTravelTime()
      )


  def error_codes(report: ValidationReport) -> list[IssueCode]:
      return [issue.code for issue in report.errors()]


  def test_valid_itinerary_has_no_errors() -> None:
      report = run(make_itinerary(make_day(VALID_DAY)))
      assert report.is_valid
      assert report.errors() == []


  def test_unknown_place_is_error_with_position() -> None:
      stops = [*VALID_DAY]
      stops[1] = ("osm:node/999", "10:45", "11:15")
      report = run(make_itinerary(make_day(stops)))
      assert not report.is_valid
      [issue] = report.errors()
      assert issue.code is IssueCode.UNKNOWN_PLACE
      assert (issue.day_index, issue.stop_index, issue.place_id) == (0, 1, "osm:node/999")


  def test_duplicate_place_across_days() -> None:
      day2 = make_day(VALID_DAY, date=DAY1 + dt.timedelta(days=1))
      report = run(make_itinerary(make_day(VALID_DAY), day2), make_request(num_days=2))
      assert error_codes(report) == [IssueCode.DUPLICATE_PLACE] * 4


  def test_day_count_mismatch() -> None:
      report = run(make_itinerary(make_day(VALID_DAY)), make_request(num_days=2))
      assert error_codes(report) == [IssueCode.DAY_COUNT_MISMATCH]


  def test_date_mismatch() -> None:
      report = run(make_itinerary(make_day(VALID_DAY, date=DAY1 + dt.timedelta(days=1))))
      assert error_codes(report) == [IssueCode.DATE_MISMATCH]


  def test_depart_not_after_arrive() -> None:
      stops = [*VALID_DAY]
      stops[0] = ("t:museum", "10:30", "10:30")
      report = run(make_itinerary(make_day(stops)))
      assert error_codes(report) == [IssueCode.STOP_TIME_ORDER]


  def test_stop_outside_day_window() -> None:
      stops = [*VALID_DAY]
      stops[0] = ("t:museum", "07:00", "08:00")
      report = run(make_itinerary(make_day(stops)))
      assert error_codes(report) == [IssueCode.OUTSIDE_DAY_WINDOW]
  ```

- [ ] **Step 3: Chạy test, xác nhận fail**

  Run: `.venv\Scripts\python -m pytest tests/validation -v`

  Expected: FAIL với `ModuleNotFoundError: No module named 'travel_agent.validation'`.

- [ ] **Step 4: Implement `report.py`**

  Tạo `src/travel_agent/validation/__init__.py` rỗng. Tạo `src/travel_agent/validation/report.py`:

  ```python
  from __future__ import annotations

  from enum import StrEnum

  from pydantic import BaseModel


  class Severity(StrEnum):
      ERROR = "error"  # plan không được trả cho user
      WARNING = "warning"  # plan dùng được nhưng phải hiển thị cảnh báo


  class IssueCode(StrEnum):
      UNKNOWN_PLACE = "unknown_place"
      DUPLICATE_PLACE = "duplicate_place"
      DAY_COUNT_MISMATCH = "day_count_mismatch"
      DATE_MISMATCH = "date_mismatch"
      STOP_TIME_ORDER = "stop_time_order"
      OUTSIDE_DAY_WINDOW = "outside_day_window"
      STOP_OVERLAP = "stop_overlap"
      TRAVEL_TIME_INSUFFICIENT = "travel_time_insufficient"
      CLOSED_DURING_VISIT = "closed_during_visit"
      OPENING_HOURS_UNKNOWN = "opening_hours_unknown"
      OVERLOADED_DAY = "overloaded_day"
      MISSING_MEAL = "missing_meal"


  class Issue(BaseModel):
      code: IssueCode
      severity: Severity
      message: str
      day_index: int | None = None
      stop_index: int | None = None
      place_id: str | None = None


  class ValidationReport(BaseModel):
      issues: list[Issue]
      estimated_legs: int = 0

      @property
      def is_valid(self) -> bool:
          return not self.errors()

      def errors(self) -> list[Issue]:
          return [issue for issue in self.issues if issue.severity is Severity.ERROR]
  ```

- [ ] **Step 5: Implement `validator.py` (phần cấu trúc)**

  `src/travel_agent/validation/validator.py`:

  ```python
  """Validator: cổng kiểm chứng bắt buộc cho lịch trình do LLM sinh.

  Mỗi Issue có vị trí (day_index, stop_index) để vòng repair chỉ đúng chỗ sai cho LLM.
  """

  from __future__ import annotations

  import datetime as dt

  from travel_agent.data.place_repository import PlaceLookup
  from travel_agent.domain.models import Itinerary, PlannedStop, PlanRequest
  from travel_agent.routing.travel_time import TravelTimeProvider
  from travel_agent.validation.report import Issue, IssueCode, Severity, ValidationReport


  def validate_itinerary(
      request: PlanRequest,
      itinerary: Itinerary,
      places: PlaceLookup,
      travel: TravelTimeProvider,
  ) -> ValidationReport:
      issues: list[Issue] = []
      _check_days(request, itinerary, issues)
      seen: set[str] = set()
      for d_idx, day in enumerate(itinerary.days):
          resolved = [places.get(stop.place_id) for stop in day.stops]
          for s_idx, (stop, place) in enumerate(zip(day.stops, resolved, strict=True)):
              if place is None:
                  issues.append(
                      _issue(
                          Severity.ERROR,
                          IssueCode.UNKNOWN_PLACE,
                          f"place_id {stop.place_id} không có trong danh sách địa điểm",
                          d_idx,
                          s_idx,
                          stop.place_id,
                      )
                  )
              if stop.place_id in seen:
                  issues.append(
                      _issue(
                          Severity.ERROR,
                          IssueCode.DUPLICATE_PLACE,
                          f"Địa điểm {stop.place_id} đã xuất hiện trước đó trong lịch trình",
                          d_idx,
                          s_idx,
                          stop.place_id,
                      )
                  )
              seen.add(stop.place_id)
              _check_stop_times(request, stop, d_idx, s_idx, issues)
      return ValidationReport(issues=issues)


  def _issue(
      severity: Severity,
      code: IssueCode,
      message: str,
      day_index: int | None = None,
      stop_index: int | None = None,
      place_id: str | None = None,
  ) -> Issue:
      return Issue(
          code=code,
          severity=severity,
          message=message,
          day_index=day_index,
          stop_index=stop_index,
          place_id=place_id,
      )


  def _check_days(request: PlanRequest, itinerary: Itinerary, issues: list[Issue]) -> None:
      if len(itinerary.days) != request.num_days:
          issues.append(
              _issue(
                  Severity.ERROR,
                  IssueCode.DAY_COUNT_MISMATCH,
                  f"Cần {request.num_days} ngày, lịch trình có {len(itinerary.days)} ngày",
              )
          )
      for d_idx, day in enumerate(itinerary.days):
          expected = request.start_date + dt.timedelta(days=d_idx)
          if day.date != expected:
              issues.append(
                  _issue(
                      Severity.ERROR,
                      IssueCode.DATE_MISMATCH,
                      f"Ngày thứ {d_idx + 1} ghi {day.date.isoformat()}, "
                      f"phải là {expected.isoformat()}",
                      d_idx,
                  )
              )


  def _check_stop_times(
      request: PlanRequest, stop: PlannedStop, d_idx: int, s_idx: int, issues: list[Issue]
  ) -> None:
      if stop.depart <= stop.arrive:
          issues.append(
              _issue(
                  Severity.ERROR,
                  IssueCode.STOP_TIME_ORDER,
                  f"Giờ rời ({stop.depart:%H:%M}) phải sau giờ đến ({stop.arrive:%H:%M})",
                  d_idx,
                  s_idx,
                  stop.place_id,
              )
          )
      if stop.arrive < request.day_start or stop.depart > request.day_end:
          issues.append(
              _issue(
                  Severity.ERROR,
                  IssueCode.OUTSIDE_DAY_WINDOW,
                  f"Điểm dừng {stop.arrive:%H:%M}-{stop.depart:%H:%M} nằm ngoài khung ngày "
                  f"{request.day_start:%H:%M}-{request.day_end:%H:%M}",
                  d_idx,
                  s_idx,
                  stop.place_id,
              )
          )
  ```

- [ ] **Step 6: Chạy test, xác nhận pass**

  Run: `.venv\Scripts\python -m pytest tests/validation -v`

  Expected: 7 passed.

- [ ] **Step 7: Commit**

  ```powershell
  .venv\Scripts\ruff format src tests
  .venv\Scripts\ruff check --fix src tests
  .venv\Scripts\mypy src
  .venv\Scripts\python -m pytest
  git add src/travel_agent/validation tests/validation
  git commit -m "feat: add structural itinerary validation with positioned issues"
  ```

---

### Task 7: Validator, phần thời gian, giờ mở cửa, nhịp độ, bữa ăn

**Files:**
- Modify: `src/travel_agent/validation/validator.py` (thay `validate_itinerary`, thêm hằng số và helper)
- Test: `tests/validation/test_validator_timing.py`

**Interfaces:**
- Consumes:
  - `parse_opening_hours` (Task 3).
  - `TravelTimeProvider.travel_leg` (Task 4).
  - `Category`, `Pace`, `Place` (Task 2).
  - Factories (Task 6).
- Produces: `validate_itinerary`, giữ nguyên signature, bổ sung các kiểm tra sau.

  | Code | Severity | Điều kiện |
  |---|---|---|
  | `stop_overlap` | ERROR | `arrive` của điểm sau sớm hơn `depart` của điểm trước |
  | `travel_time_insufficient` | ERROR | Khoảng trống giữa hai điểm ít hơn `TravelLeg.minutes` |
  | `closed_during_visit` | ERROR | Giờ mở cửa đã biết và không bao trọn khung `arrive`–`depart` |
  | `opening_hours_unknown` | WARNING | Không parse được giờ mở cửa |
  | `overloaded_day` | WARNING | Số stop vượt mức: relaxed 4, moderate 6, packed 8 (heuristic sản phẩm, chưa kiểm chứng) |
  | `missing_meal` | WARNING | Khung ngày bao trọn 11:00–13:30 hoặc 17:30–20:00 nhưng không có stop `restaurant` nào giao với khung đó |

  `ValidationReport.estimated_legs` = số chặng có `estimated=True`.

- [ ] **Step 1: Viết test (sẽ fail)**

  `tests/validation/test_validator_timing.py`:

  ```python
  from tests.validation.factories import (
      VALID_DAY,
      FixedTravelTime,
      make_day,
      make_itinerary,
      make_request,
      sample_places,
  )
  from travel_agent.domain.models import Itinerary, Pace, PlanRequest
  from travel_agent.routing.travel_time import HaversineEstimator, TravelTimeProvider
  from travel_agent.validation.report import Issue, IssueCode, ValidationReport
  from travel_agent.validation.validator import validate_itinerary


  def run(
      itinerary: Itinerary,
      request: PlanRequest | None = None,
      travel: TravelTimeProvider | None = None,
  ) -> ValidationReport:
      return validate_itinerary(
          request or make_request(), itinerary, sample_places(), travel or FixedTravelTime()
      )


  def codes(issues: list[Issue]) -> list[IssueCode]:
      return [issue.code for issue in issues]


  def test_valid_day_only_warns_about_unknown_hours() -> None:
      report = run(make_itinerary(make_day(VALID_DAY)))
      assert report.is_valid
      assert codes(report.issues) == [IssueCode.OPENING_HOURS_UNKNOWN]
      assert report.issues[0].place_id == "t:cafe"
      assert report.estimated_legs == 0


  def test_travel_time_insufficient() -> None:
      report = run(make_itinerary(make_day(VALID_DAY)), travel=FixedTravelTime(minutes=30))
      errors = report.errors()
      assert codes(errors) == [IssueCode.TRAVEL_TIME_INSUFFICIENT] * 2
      assert [error.stop_index for error in errors] == [1, 2]


  def test_overlapping_stops() -> None:
      stops = [*VALID_DAY]
      stops[1] = ("t:cafe", "10:00", "11:15")
      report = run(make_itinerary(make_day(stops)))
      assert codes(report.errors()) == [IssueCode.STOP_OVERLAP]


  def test_closed_during_visit() -> None:
      stops = [
          ("t:lunch", "11:30", "12:30"),
          ("t:museum", "16:00", "17:30"),
          ("t:dinner", "18:00", "19:00"),
      ]
      report = run(make_itinerary(make_day(stops)))
      [error] = report.errors()
      assert error.code is IssueCode.CLOSED_DURING_VISIT
      assert error.stop_index == 1
      assert "Mo-Su 07:00-17:00" in error.message


  def test_estimated_legs_are_counted() -> None:
      report = run(
          make_itinerary(make_day(VALID_DAY)), travel=FixedTravelTime(minutes=10, estimated=True)
      )
      assert report.is_valid
      assert report.estimated_legs == 3


  def test_haversine_estimator_marks_all_legs_estimated() -> None:
      report = run(make_itinerary(make_day(VALID_DAY)), travel=HaversineEstimator())
      assert report.is_valid
      assert report.estimated_legs == 3


  def test_overloaded_relaxed_day_is_warning_only() -> None:
      stops = [*VALID_DAY, ("t:viewpoint", "19:15", "20:00")]
      report = run(make_itinerary(make_day(stops)), make_request(pace=Pace.RELAXED))
      assert report.is_valid
      assert IssueCode.OVERLOADED_DAY in codes(report.issues)


  def test_missing_lunch_is_warning() -> None:
      stops = [
          ("t:museum", "08:30", "10:30"),
          ("t:cafe", "10:45", "11:15"),
          ("t:dinner", "18:00", "19:00"),
      ]
      report = run(make_itinerary(make_day(stops)))
      assert report.is_valid
      meal_warnings = [i for i in report.issues if i.code is IssueCode.MISSING_MEAL]
      assert len(meal_warnings) == 1
      assert "bữa trưa" in meal_warnings[0].message
  ```

- [ ] **Step 2: Chạy test, xác nhận fail**

  Run: `.venv\Scripts\python -m pytest tests/validation/test_validator_timing.py -v`

  Expected: FAIL. Ví dụ `test_valid_day_only_warns_about_unknown_hours` báo `assert [] == [<IssueCode.OPENING_HOURS_UNKNOWN...>]`.

- [ ] **Step 3: Sửa import và thêm hằng số trong `validator.py`**

  Thay khối import hiện có bằng:

  ```python
  from __future__ import annotations

  import datetime as dt

  from travel_agent.data.place_repository import PlaceLookup
  from travel_agent.domain.models import Category, Itinerary, Pace, Place, PlannedStop, PlanRequest
  from travel_agent.domain.opening_hours import parse_opening_hours
  from travel_agent.routing.travel_time import TravelTimeProvider
  from travel_agent.validation.report import Issue, IssueCode, Severity, ValidationReport

  # Heuristic sản phẩm, chưa kiểm chứng; tinh chỉnh bằng phản hồi người dùng ở plan sau.
  MAX_STOPS_PER_DAY: dict[Pace, int] = {Pace.RELAXED: 4, Pace.MODERATE: 6, Pace.PACKED: 8}
  MEAL_WINDOWS: tuple[tuple[str, dt.time, dt.time], ...] = (
      ("bữa trưa", dt.time(11, 0), dt.time(13, 30)),
      ("bữa tối", dt.time(17, 30), dt.time(20, 0)),
  )
  MEAL_CATEGORIES = frozenset({Category.RESTAURANT})
  ```

- [ ] **Step 4: Thay toàn bộ hàm `validate_itinerary`**

  ```python
  def validate_itinerary(
      request: PlanRequest,
      itinerary: Itinerary,
      places: PlaceLookup,
      travel: TravelTimeProvider,
  ) -> ValidationReport:
      issues: list[Issue] = []
      _check_days(request, itinerary, issues)
      seen: set[str] = set()
      estimated_legs = 0
      for d_idx, day in enumerate(itinerary.days):
          resolved = [places.get(stop.place_id) for stop in day.stops]
          for s_idx, (stop, place) in enumerate(zip(day.stops, resolved, strict=True)):
              if place is None:
                  issues.append(
                      _issue(
                          Severity.ERROR,
                          IssueCode.UNKNOWN_PLACE,
                          f"place_id {stop.place_id} không có trong danh sách địa điểm",
                          d_idx,
                          s_idx,
                          stop.place_id,
                      )
                  )
              else:
                  _check_opening_hours(day.date, stop, place, d_idx, s_idx, issues)
              if stop.place_id in seen:
                  issues.append(
                      _issue(
                          Severity.ERROR,
                          IssueCode.DUPLICATE_PLACE,
                          f"Địa điểm {stop.place_id} đã xuất hiện trước đó trong lịch trình",
                          d_idx,
                          s_idx,
                          stop.place_id,
                      )
                  )
              seen.add(stop.place_id)
              _check_stop_times(request, stop, d_idx, s_idx, issues)
          estimated_legs += _check_travel(request, day.stops, resolved, d_idx, travel, issues)
          _check_load(request, day.stops, d_idx, issues)
          _check_meals(request, day.stops, resolved, d_idx, issues)
      return ValidationReport(issues=issues, estimated_legs=estimated_legs)
  ```

- [ ] **Step 5: Thêm các helper vào cuối `validator.py`**

  ```python
  def _check_opening_hours(
      day_date: dt.date,
      stop: PlannedStop,
      place: Place,
      d_idx: int,
      s_idx: int,
      issues: list[Issue],
  ) -> None:
      hours = parse_opening_hours(place.opening_hours_raw)
      if hours is None:
          issues.append(
              _issue(
                  Severity.WARNING,
                  IssueCode.OPENING_HOURS_UNKNOWN,
                  f"Chưa có giờ mở cửa đã xác minh cho {place.name}",
                  d_idx,
                  s_idx,
                  place.id,
              )
          )
          return
      if not hours.covers(day_date.weekday(), stop.arrive, stop.depart):
          issues.append(
              _issue(
                  Severity.ERROR,
                  IssueCode.CLOSED_DURING_VISIT,
                  f"{place.name} không mở cửa trong {stop.arrive:%H:%M}-{stop.depart:%H:%M} "
                  f"(giờ mở cửa theo {place.source}: {place.opening_hours_raw})",
                  d_idx,
                  s_idx,
                  place.id,
              )
          )


  def _minutes_between(start: dt.time, end: dt.time) -> float:
      anchor = dt.date(2000, 1, 1)
      delta = dt.datetime.combine(anchor, end) - dt.datetime.combine(anchor, start)
      return delta.total_seconds() / 60


  def _check_travel(
      request: PlanRequest,
      stops: list[PlannedStop],
      resolved: list[Place | None],
      d_idx: int,
      travel: TravelTimeProvider,
      issues: list[Issue],
  ) -> int:
      estimated = 0
      for s_idx in range(1, len(stops)):
          prev, cur = stops[s_idx - 1], stops[s_idx]
          gap = _minutes_between(prev.depart, cur.arrive)
          if gap < 0:
              issues.append(
                  _issue(
                      Severity.ERROR,
                      IssueCode.STOP_OVERLAP,
                      f"Đến lúc {cur.arrive:%H:%M} nhưng điểm trước rời lúc {prev.depart:%H:%M}",
                      d_idx,
                      s_idx,
                      cur.place_id,
                  )
              )
              continue
          origin, destination = resolved[s_idx - 1], resolved[s_idx]
          if origin is None or destination is None:
              continue  # đã báo UNKNOWN_PLACE
          leg = travel.travel_leg(origin.coords, destination.coords, request.travel_mode)
          if leg.estimated:
              estimated += 1
          if gap < leg.minutes:
              label = "ước tính" if leg.estimated else "theo routing"
              issues.append(
                  _issue(
                      Severity.ERROR,
                      IssueCode.TRAVEL_TIME_INSUFFICIENT,
                      f"Chỉ có {gap:.0f} phút để đi từ {origin.name}, cần khoảng "
                      f"{leg.minutes:.0f} phút ({label}, nguồn {leg.source})",
                      d_idx,
                      s_idx,
                      cur.place_id,
                  )
              )
      return estimated


  def _check_load(
      request: PlanRequest, stops: list[PlannedStop], d_idx: int, issues: list[Issue]
  ) -> None:
      limit = MAX_STOPS_PER_DAY[request.pace]
      if len(stops) > limit:
          issues.append(
              _issue(
                  Severity.WARNING,
                  IssueCode.OVERLOADED_DAY,
                  f"Ngày {d_idx + 1} có {len(stops)} điểm, vượt mức {limit} "
                  f"cho nhịp độ {request.pace.value}",
                  d_idx,
              )
          )


  def _check_meals(
      request: PlanRequest,
      stops: list[PlannedStop],
      resolved: list[Place | None],
      d_idx: int,
      issues: list[Issue],
  ) -> None:
      for meal, window_start, window_end in MEAL_WINDOWS:
          if request.day_start > window_start or request.day_end < window_end:
              continue  # khung ngày không bao trọn bữa này
          has_meal = any(
              place is not None
              and place.category in MEAL_CATEGORIES
              and stop.arrive < window_end
              and stop.depart > window_start
              for stop, place in zip(stops, resolved, strict=True)
          )
          if not has_meal:
              issues.append(
                  _issue(
                      Severity.WARNING,
                      IssueCode.MISSING_MEAL,
                      f"Ngày {d_idx + 1} chưa có điểm ăn cho {meal} "
                      f"({window_start:%H:%M}-{window_end:%H:%M})",
                      d_idx,
                  )
              )
  ```

- [ ] **Step 6: Chạy toàn bộ test validator**

  Run: `.venv\Scripts\python -m pytest tests/validation -v`

  Expected: 15 passed (7 test cấu trúc của Task 6 vẫn pass + 8 test mới).

- [ ] **Step 7: Commit**

  ```powershell
  .venv\Scripts\ruff format src tests
  .venv\Scripts\ruff check --fix src tests
  .venv\Scripts\mypy src
  .venv\Scripts\python -m pytest
  git add src/travel_agent/validation/validator.py tests/validation/test_validator_timing.py
  git commit -m "feat: validate travel time, opening hours, pace and meals"
  ```

---

### Task 8: CLI, nạp dữ liệu Huế thật, README

**Files:**
- Create: `src/travel_agent/cli.py`
- Create: `README.md`
- Create: `examples/hue_request.json`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes:
  - `build_overpass_query`, `places_from_overpass`, `OSM_ATTRIBUTION` (Task 5).
  - `SqlitePlaceRepository` (Task 5).
  - `PlanRequest`, `Itinerary`, `Category` (Task 2).
  - `HaversineEstimator` (Task 4).
  - `validate_itinerary` (Task 7).
- Produces: `main(argv: Sequence[str] | None = None) -> int` với các lệnh:
  - `fetch-osm --out PATH [--bbox S,W,N,E]`
  - `ingest-osm RAW --db PATH`
  - `places --db PATH [--category C] [--limit N]`
  - `validate --db PATH --request PATH --itinerary PATH`: exit code 0 nếu hợp lệ, 1 nếu có ERROR, 2 nếu DB không tồn tại.

- [ ] **Step 1: Viết test (sẽ fail)**

  `tests/test_cli.py`:

  ```python
  import json
  from pathlib import Path

  import pytest

  from travel_agent.cli import main

  FIXTURE = Path(__file__).parent / "fixtures" / "overpass_sample.json"


  def test_ingest_then_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
      db = tmp_path / "hue.sqlite"
      assert main(["ingest-osm", str(FIXTURE), "--db", str(db)]) == 0
      ingest_out = capsys.readouterr().out
      assert "Đã nạp 3 địa điểm" in ingest_out
      assert "2026-11-03T08:00:00+00:00" in ingest_out
      assert main(["places", "--db", str(db), "--category", "museum"]) == 0
      listed = capsys.readouterr().out
      assert "osm:node/1" in listed
      assert "osm:way/2" not in listed


  def test_validate_exit_codes(tmp_path: Path) -> None:
      db = tmp_path / "hue.sqlite"
      assert main(["ingest-osm", str(FIXTURE), "--db", str(db)]) == 0
      request = tmp_path / "request.json"
      request.write_text(json.dumps({"start_date": "2026-11-04", "num_days": 1}), encoding="utf-8")
      good = tmp_path / "good.json"
      good.write_text(
          json.dumps(
              {
                  "days": [
                      {
                          "date": "2026-11-04",
                          "stops": [
                              {"place_id": "osm:node/1", "arrive": "09:00", "depart": "10:30"},
                              {"place_id": "osm:node/6", "arrive": "11:30", "depart": "12:30"},
                          ],
                      }
                  ]
              }
          ),
          encoding="utf-8",
      )
      bad = tmp_path / "bad.json"
      bad.write_text(
          json.dumps(
              {
                  "days": [
                      {
                          "date": "2026-11-04",
                          "stops": [
                              {"place_id": "osm:node/404", "arrive": "09:00", "depart": "10:30"}
                          ],
                      }
                  ]
              }
          ),
          encoding="utf-8",
      )
      args = ["validate", "--db", str(db), "--request", str(request), "--itinerary"]
      assert main([*args, str(good)]) == 0
      assert main([*args, str(bad)]) == 1


  def test_validate_refuses_missing_db(tmp_path: Path) -> None:
      missing = tmp_path / "missing.sqlite"
      args = ["validate", "--db", str(missing), "--request", "r.json", "--itinerary", "i.json"]
      assert main(args) == 2
      assert not missing.exists()
  ```

- [ ] **Step 2: Chạy test, xác nhận fail**

  Run: `.venv\Scripts\python -m pytest tests/test_cli.py -v`

  Expected: FAIL với `ModuleNotFoundError: No module named 'travel_agent.cli'`.

- [ ] **Step 3: Implement `cli.py`**

  ```python
  """CLI: travel-agent fetch-osm | ingest-osm | places | validate."""

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
  from travel_agent.domain.models import Category, Itinerary, PlanRequest
  from travel_agent.routing.travel_time import HaversineEstimator
  from travel_agent.validation.validator import validate_itinerary

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

      validate = sub.add_parser("validate", help="Kiểm tra một lịch trình JSON")
      validate.add_argument("--db", type=Path, required=True)
      validate.add_argument("--request", type=Path, required=True)
      validate.add_argument("--itinerary", type=Path, required=True)
      validate.set_defaults(func=_cmd_validate)
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


  def _open_existing(db: Path) -> SqlitePlaceRepository | None:
      if not db.exists():
          print(f"Không tìm thấy DB {db}. Chạy ingest-osm trước.", file=sys.stderr)
          return None
      return SqlitePlaceRepository(db)


  def _cmd_places(args: argparse.Namespace) -> int:
      repo = _open_existing(args.db)
      if repo is None:
          return 2
      try:
          for place in repo.list_places(args.category, args.limit):
              hours = place.opening_hours_raw or "giờ mở cửa: unknown"
              print(f"{place.id}\t{place.category.value}\t{place.name}\t{hours}")
      finally:
          repo.close()
      return 0


  def _cmd_validate(args: argparse.Namespace) -> int:
      repo = _open_existing(args.db)
      if repo is None:
          return 2
      try:
          request = PlanRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
          itinerary = Itinerary.model_validate_json(args.itinerary.read_text(encoding="utf-8"))
          report = validate_itinerary(request, itinerary, repo, HaversineEstimator())
      finally:
          repo.close()
      output = {"is_valid": report.is_valid, **report.model_dump(mode="json")}
      print(json.dumps(output, ensure_ascii=False, indent=2))
      return 0 if report.is_valid else 1
  ```

- [ ] **Step 4: Chạy test, xác nhận pass**

  Run: `.venv\Scripts\python -m pytest -v`

  Expected: 54 passed (toàn bộ test, gồm 3 test CLI).

- [ ] **Step 5: Tải và nạp dữ liệu Huế thật (chạy thủ công một lần, cần mạng)**

  Trước khi tải, mở bbox `16.36,107.50,16.58,107.70` trên openstreetmap.org để chắc vùng bao phủ đúng ý.

  ```powershell
  .venv\Scripts\travel-agent fetch-osm --out data\raw\osm_hue.json
  .venv\Scripts\travel-agent ingest-osm data\raw\osm_hue.json --db data\hue.sqlite
  ```

  Expected:
  - Lệnh ingest in tổng số địa điểm, mốc thời gian OSM, tỉ lệ có `opening_hours` và số lượng theo từng category.
  - Ghi lại các con số này cho Step 8.
  - Nếu Overpass trả lỗi 429 hoặc 504: chờ vài phút rồi chạy lại **một lần**. Không chạy lặp liên tục.

- [ ] **Step 6: Tạo request mẫu và lịch trình viết tay**

  `examples/hue_request.json`:

  ```json
  {
    "city": "hue",
    "start_date": "2026-11-04",
    "num_days": 1,
    "day_start": "08:00",
    "day_end": "21:00",
    "travel_mode": "motorbike",
    "pace": "moderate",
    "interests": ["lịch sử", "ẩm thực", "chụp ảnh"]
  }
  ```

  Liệt kê id thật:

  ```powershell
  .venv\Scripts\travel-agent places --db data\hue.sqlite --category historic --limit 20
  .venv\Scripts\travel-agent places --db data\hue.sqlite --category restaurant --limit 20
  ```

  Tạo file `examples/hue_itinerary_draft.json` theo cấu trúc dưới đây:
  - Chọn 2 id `historic` và 2 id `restaurant` từ output trên.
  - Xếp một id `restaurant` vào khung trưa, id còn lại vào khung tối.
  - Thay 4 giá trị `REPLACE_WITH_...` bằng các id đã chọn.

  File này do người viết tay để thử validator; lịch trình trong đó không phải gợi ý đã kiểm chứng.

  ```json
  {"days": [{"date": "2026-11-04", "stops": [
    {"place_id": "REPLACE_WITH_HISTORIC_ID_1", "arrive": "08:30", "depart": "10:30"},
    {"place_id": "REPLACE_WITH_RESTAURANT_ID_1", "arrive": "11:30", "depart": "12:30"},
    {"place_id": "REPLACE_WITH_HISTORIC_ID_2", "arrive": "14:00", "depart": "16:00"},
    {"place_id": "REPLACE_WITH_RESTAURANT_ID_2", "arrive": "18:00", "depart": "19:00"}
  ]}]}
  ```

  Chạy:

  ```powershell
  .venv\Scripts\travel-agent validate --db data\hue.sqlite --request examples\hue_request.json --itinerary examples\hue_itinerary_draft.json
  ```

  Expected:
  - Output là JSON có `is_valid`.
  - `estimated_legs` bằng 3.
  - Có thể xuất hiện `opening_hours_unknown` ở những điểm OSM chưa có giờ mở cửa.
  - Thử sửa một giờ đến cho trùng với điểm trước. Validator phải báo `stop_overlap` và trả exit code 1.

- [ ] **Step 7: Viết `README.md`**

  ````markdown
  # Travel Agent: Huế

  Nền tảng kiểm chứng lịch trình cho LLM lập lịch du lịch chạy offline.
  Lộ trình: `docs/superpowers/plans/2026-11-03-hue-planner-roadmap.md`.

  ## Cài đặt (Windows, Python 3.11)

  ```powershell
  py -3.11 -m venv .venv
  .venv\Scripts\python -m pip install -e ".[dev]"
  ```

  ## Dữ liệu

  Dữ liệu địa điểm © OpenStreetMap contributors, giấy phép ODbL-1.0.
  Chỉ tải một lần (fair-use Overpass API):

  ```powershell
  .venv\Scripts\travel-agent fetch-osm --out data\raw\osm_hue.json
  .venv\Scripts\travel-agent ingest-osm data\raw\osm_hue.json --db data\hue.sqlite
  ```

  ## Kiểm tra lịch trình

  ```powershell
  .venv\Scripts\travel-agent validate --db data\hue.sqlite --request examples\hue_request.json --itinerary <file>.json
  ```

  - Exit code 0: hợp lệ (có thể còn cảnh báo).
  - Exit code 1: có lỗi, không được trả cho người dùng.

  Thời gian di chuyển hiện là **ước tính** từ khoảng cách đường chim bay (`estimated_legs`),
  không phải dữ liệu routing thật.

  ## Kiểm thử

  ```powershell
  .venv\Scripts\ruff format src tests
  .venv\Scripts\ruff check src tests
  .venv\Scripts\mypy src
  .venv\Scripts\python -m pytest
  ```
  ````

- [ ] **Step 8: Ghi số liệu độ phủ vào README**

  Thêm vào cuối `README.md` một mục `## Độ phủ dữ liệu Huế (OSM, <mốc thời gian OSM từ Step 5>)`. Nội dung lấy từ output Step 5:
  - Tổng số địa điểm.
  - Số địa điểm có `opening_hours`.
  - Số lượng theo từng category.

  Chỉ chép đúng các con số đã in ra, không làm tròn hay suy diễn.

- [ ] **Step 9: Commit**

  ```powershell
  .venv\Scripts\ruff format src tests
  .venv\Scripts\ruff check --fix src tests
  .venv\Scripts\mypy src
  .venv\Scripts\python -m pytest
  git add src/travel_agent/cli.py tests/test_cli.py README.md examples
  git commit -m "feat: add CLI for OSM ingest and itinerary validation"
  ```

  Không add `data/`; file đó đã nằm trong `.gitignore`.

---

## Nghiệm thu Plan 1

- `ruff check`, `mypy src` và `pytest` pass, tổng 54 test.
- File `data\hue.sqlite` có POI Huế. Mỗi POI có `source=osm`, `license=ODbL-1.0` và `collected_at` lấy từ mốc thời gian OSM.
- Lệnh `validate` trên lịch trình viết tay dùng id thật cho kết quả đúng: lịch hợp lệ trả exit 0, lịch có chồng giờ trả exit 1 kèm `stop_overlap`.
- README có số liệu độ phủ thật. Số liệu này là đầu vào để quyết định cách lọc candidate ở Plan 2.

**Bước tiếp:** viết chi tiết Plan 2 (baseline sinh, kiểm, sửa với Ollama và Qwen3.5-9B, kèm bộ eval) dựa trên interface và số liệu độ phủ thật của Plan 1.
