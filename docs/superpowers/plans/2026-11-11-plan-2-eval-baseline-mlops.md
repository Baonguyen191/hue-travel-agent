# Plan 2: Candidates, prompt, bộ eval, baseline 4B, khung MLOps (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Có harness eval chạy được trên bộ 100 request Huế đóng băng, đo baseline của Qwen 4B chưa train qua Ollama, và có khung MLOps (DVC, MLflow, CI) để các plan SFT/RL sau cắm vào.

**Architecture:** Logic thuần nằm trong `travel_agent/planning/` (chọn candidate, dựng prompt) và `travel_agent/training/` (sinh request, parse output, metric, runner). Model được gọi qua Protocol `PlanGenerator`, nên toàn bộ test chạy không cần GPU hay Ollama. DVC nối các bước thành pipeline; MLflow ghi tham số và metric.

**Tech Stack:** Python 3.11, pydantic v2, pytest, ruff, mypy strict, Ollama (HTTP `/api/chat`, gọi bằng `urllib`), DVC, MLflow, GitHub Actions.

**Spec:** [docs/superpowers/specs/2026-11-11-sft-rl-training-design.md](../specs/2026-11-11-sft-rl-training-design.md) (mục 4, 9, 10 và bước 2 của mục 13).

## Global Constraints

- Python `>=3.11`. Ruff `line-length = 100`, rule `E, F, I, UP, B`. Mypy `strict = true`.
- Không thêm phụ thuộc runtime vào `dependencies` của `pyproject.toml`. DVC và MLflow nằm trong extra `mlops`.
- Docstring và comment viết tiếng Việt, theo code hiện có.
- Không bịa dữ liệu du lịch. Test dùng dữ liệu giả có tiền tố id `t:`.
- Thinking tắt khi gọi model.
- Bộ test (30 request) đóng băng: không chạy eval trên `test` trong plan này, không sinh lại file sau khi đã commit.
- Output của model không được sửa hộ: không cắt code fence, không vá JSON.
- Cache DVC, DVC remote và MLflow store đặt ngoài OneDrive (`C:\dev\...`).
- Lệnh test: `.venv\Scripts\python -m pytest`. Lệnh CLI: đặt `$env:PYTHONPATH="src"` rồi `.venv\Scripts\python -m travel_agent <lệnh>` (xem README, lỗi `.pth` với đường dẫn có dấu).

## Điều kiện trước khi bắt đầu

1. **Commit hoặc stash các thay đổi đang dở trên `feat/hue-data`.** Task 6 sửa `src/travel_agent/cli.py`, file này đang có thay đổi chưa commit.
2. Tạo nhánh: `git switch -c feat/eval-baseline`.
3. **Task 1–3 không cần validator.** Task 4 trở đi cần `travel_agent.validation` (Plan 1 Task 6–7 trong [2026-11-03-plan-1-hue-foundation.md](2026-11-03-plan-1-hue-foundation.md)). Làm xong Plan 1 Task 6–7 trước Task 4.

## Lệch so với spec (cần chủ dự án biết)

- **Số candidate.** Spec ghi tối đa 20. Validator cấm lặp `place_id` giữa các ngày, nên request `packed` 3 ngày cần 18–24 điểm khác nhau; 20 candidate không đủ. Plan này dùng `candidate_limit = clamp(số stop tối đa theo pace × num_days + 4, 12, 30)`. Request 1 ngày vẫn chỉ 12 candidate.
- **Chữ ký `select_candidates`.** Spec ghi `(request, repo, seed)`. Plan này nhận `Sequence[Place]` thay cho repo để hàm thuần và dễ test; nơi gọi tự nạp danh sách từ SQLite.
- **`build_messages`.** Plan này chỉ làm nhánh sinh plan. Tham số `issues` cho mẫu repair thêm ở plan dataset (bước 3 của spec).

## File Structure

```text
src/travel_agent/
  planning/
    __init__.py            # rỗng
    candidates.py          # INTEREST_CATEGORIES, candidate_limit, select_candidates
    prompt.py              # SYSTEM_PROMPT, build_messages
  training/
    __init__.py            # rỗng
    requests.py            # sinh PlanRequest, request_key, bộ eval dev/test
    parsing.py             # parse_itinerary (nghiêm ngặt)
    metrics.py             # PlanOutcome, EvalSummary, score_output, summarize, regressions
    generator.py           # PlanGenerator (Protocol), OllamaGenerator
    runner.py              # run_eval
    tracking.py            # log_eval_run (MLflow, import trễ)
    commands.py            # lệnh CLI make-evalset, eval
  cli.py                   # sửa: đăng ký lệnh training
tests/
  planning/  __init__.py, factories.py, test_candidates.py, test_prompt.py, snapshots/
  training/  __init__.py, factories.py, test_requests.py, test_parsing.py, test_metrics.py,
             test_generator.py, test_runner.py, test_tracking.py, test_commands.py,
             test_evalset_file.py
configs/eval.yaml
dvc.yaml
data/eval/hue_eval_v1.jsonl      # sinh một lần, commit vào git, đóng băng
reports/eval/                    # kết quả eval
scripts/check.ps1
.github/workflows/ci.yml
```

---

### Task 1: Chọn candidate

**Files:**
- Create: `src/travel_agent/planning/__init__.py` (rỗng)
- Create: `src/travel_agent/planning/candidates.py`
- Create: `tests/planning/__init__.py` (rỗng)
- Create: `tests/planning/factories.py`
- Test: `tests/planning/test_candidates.py`

**Interfaces:**
- Consumes: `Category`, `Pace`, `Place`, `PlanRequest`, `Coordinates`, `TravelMode` từ `travel_agent.domain.models`.
- Produces:
  - `INTEREST_CATEGORIES: dict[str, tuple[Category, ...]]`.
  - `MAX_STOPS_PER_DAY: dict[Pace, int]`.
  - `candidate_limit(request: PlanRequest) -> int`.
  - `select_candidates(request: PlanRequest, places: Sequence[Place], seed: int) -> list[Place]`.
  - Test factories: `make_place(pid, category, hours=None, name=None, lat=16.47, lon=107.58) -> Place`, `make_pool(per_category=10) -> list[Place]`, `make_request(num_days=1, pace=Pace.MODERATE, interests=()) -> PlanRequest`, hằng `START = dt.date(2026, 12, 1)`.

- [ ] **Step 1: Tạo test factories**

  Tạo `tests/planning/__init__.py` rỗng. Tạo `tests/planning/factories.py`:

  ```python
  """Dữ liệu giả cho test planning. Không phải dữ liệu thật của Huế."""

  import datetime as dt
  from collections.abc import Sequence

  from travel_agent.domain.models import (
      Category,
      Coordinates,
      Pace,
      Place,
      PlanRequest,
      TravelMode,
  )

  COLLECTED = dt.datetime(2026, 11, 3, tzinfo=dt.UTC)
  START = dt.date(2026, 12, 1)  # thứ Ba


  def make_place(
      pid: str,
      category: Category,
      hours: str | None = None,
      name: str | None = None,
      lat: float = 16.47,
      lon: float = 107.58,
  ) -> Place:
      return Place(
          id=pid,
          name=name or pid,
          category=category,
          coords=Coordinates(lat=lat, lon=lon),
          opening_hours_raw=hours,
          source="test",
          source_place_id=pid,
          license="test-only",
          collected_at=COLLECTED,
      )


  def make_pool(per_category: int = 10) -> list[Place]:
      return [
          make_place(f"t:{category.value}/{index}", category)
          for category in Category
          for index in range(per_category)
      ]


  def make_request(
      num_days: int = 1,
      pace: Pace = Pace.MODERATE,
      interests: Sequence[str] = (),
  ) -> PlanRequest:
      return PlanRequest(
          start_date=START,
          num_days=num_days,
          pace=pace,
          travel_mode=TravelMode.MOTORBIKE,
          interests=list(interests),
      )
  ```

- [ ] **Step 2: Viết test (sẽ fail)**

  `tests/planning/test_candidates.py`:

  ```python
  from collections import Counter

  from tests.planning.factories import make_place, make_pool, make_request
  from travel_agent.domain.models import Category, Pace
  from travel_agent.planning.candidates import candidate_limit, select_candidates


  def test_limit_scales_with_pace_and_days() -> None:
      assert candidate_limit(make_request(num_days=1, pace=Pace.RELAXED)) == 12
      assert candidate_limit(make_request(num_days=3, pace=Pace.MODERATE)) == 22
      assert candidate_limit(make_request(num_days=3, pace=Pace.PACKED)) == 28
      assert candidate_limit(make_request(num_days=7, pace=Pace.PACKED)) == 30


  def test_returns_limit_unique_places() -> None:
      request = make_request(num_days=3, pace=Pace.PACKED)
      chosen = select_candidates(request, make_pool(), seed=1)
      assert len(chosen) == 28
      assert len({place.id for place in chosen}) == 28


  def test_same_seed_same_result_regardless_of_input_order() -> None:
      request = make_request()
      pool = make_pool()
      first = select_candidates(request, pool, seed=7)
      second = select_candidates(request, list(reversed(pool)), seed=7)
      assert [place.id for place in first] == [place.id for place in second]


  def test_different_seed_changes_selection() -> None:
      request = make_request()
      pool = make_pool()
      first = {place.id for place in select_candidates(request, pool, seed=1)}
      second = {place.id for place in select_candidates(request, pool, seed=2)}
      assert first != second


  def test_reserves_two_restaurants_per_day() -> None:
      request = make_request(num_days=3, pace=Pace.RELAXED)
      chosen = select_candidates(request, make_pool(), seed=3)
      restaurants = [place for place in chosen if place.category is Category.RESTAURANT]
      assert len(restaurants) >= 6


  def test_no_interests_covers_every_category() -> None:
      chosen = select_candidates(make_request(), make_pool(), seed=4)
      assert {place.category for place in chosen} == set(Category)


  def test_interest_gets_more_slots() -> None:
      chosen = select_candidates(make_request(interests=["coffee"]), make_pool(), seed=5)
      counts = Counter(place.category for place in chosen)
      assert counts[Category.CAFE] > counts[Category.MUSEUM]


  def test_unknown_interest_is_ignored() -> None:
      chosen = select_candidates(make_request(interests=["khong-co"]), make_pool(), seed=6)
      assert len(chosen) == 12


  def test_small_pool_returns_everything() -> None:
      pool = [
          make_place("t:a", Category.MUSEUM),
          make_place("t:b", Category.RESTAURANT),
          make_place("t:c", Category.CAFE),
      ]
      chosen = select_candidates(make_request(), pool, seed=8)
      assert {place.id for place in chosen} == {"t:a", "t:b", "t:c"}
  ```

- [ ] **Step 3: Chạy test, xác nhận fail**

  Run: `.venv\Scripts\python -m pytest tests/planning/test_candidates.py -v`

  Expected: FAIL với `ModuleNotFoundError: No module named 'travel_agent.planning'`.

- [ ] **Step 4: Implement**

  Tạo `src/travel_agent/planning/__init__.py` rỗng. Tạo `src/travel_agent/planning/candidates.py`:

  ```python
  """Chọn candidate POI cho một PlanRequest. Hàm thuần, xác định theo seed.

  Bảng sở thích và các hằng số là heuristic sản phẩm, chưa kiểm chứng bằng dữ liệu người dùng.
  """

  from __future__ import annotations

  import random
  from collections.abc import Sequence

  from travel_agent.domain.models import Category, Pace, Place, PlanRequest

  INTEREST_CATEGORIES: dict[str, tuple[Category, ...]] = {
      "history": (Category.HISTORIC, Category.MUSEUM),
      "culture": (Category.MUSEUM, Category.RELIGIOUS, Category.HISTORIC),
      "spiritual": (Category.RELIGIOUS,),
      "food": (Category.RESTAURANT, Category.MARKET),
      "coffee": (Category.CAFE,),
      "nature": (Category.PARK, Category.VIEWPOINT),
      "photography": (Category.VIEWPOINT, Category.HISTORIC, Category.PARK),
      "shopping": (Category.MARKET,),
      "sightseeing": (Category.ATTRACTION, Category.VIEWPOINT),
  }

  # Khớp ngưỡng `overloaded_day` của validator.
  MAX_STOPS_PER_DAY: dict[Pace, int] = {Pace.RELAXED: 4, Pace.MODERATE: 6, Pace.PACKED: 8}

  MIN_CANDIDATES = 12
  MAX_CANDIDATES = 30
  SPARE_CANDIDATES = 4
  MEALS_PER_DAY = 2
  PREFERRED_PICKS_PER_ROUND = 2


  def candidate_limit(request: PlanRequest) -> int:
      """Đủ điểm cho ngày dày nhất (validator cấm lặp place_id), cộng vài điểm dự phòng."""
      wanted = MAX_STOPS_PER_DAY[request.pace] * request.num_days + SPARE_CANDIDATES
      return max(MIN_CANDIDATES, min(MAX_CANDIDATES, wanted))


  def preferred_categories(interests: Sequence[str]) -> set[Category]:
      found: set[Category] = set()
      for interest in interests:
          found.update(INTEREST_CATEGORIES.get(interest.strip().lower(), ()))
      return found


  def select_candidates(request: PlanRequest, places: Sequence[Place], seed: int) -> list[Place]:
      """Giữ chỗ cho bữa ăn, rồi lấy xoay vòng theo loại; loại khớp sở thích được lấy nhiều hơn."""
      rng = random.Random(seed)
      queues: dict[Category, list[Place]] = {category: [] for category in Category}
      for place in sorted(places, key=lambda item: item.id):
          queues[place.category].append(place)
      for queue in queues.values():
          rng.shuffle(queue)

      limit = candidate_limit(request)
      meals = min(MEALS_PER_DAY * request.num_days, limit // 2)
      restaurants = queues[Category.RESTAURANT]
      chosen = restaurants[:meals]
      del restaurants[:meals]

      preferred = preferred_categories(request.interests)
      while len(chosen) < limit and any(queues.values()):
          for category in Category:
              picks = PREFERRED_PICKS_PER_ROUND if category in preferred else 1
              for _ in range(picks):
                  if queues[category] and len(chosen) < limit:
                      chosen.append(queues[category].pop())
      rng.shuffle(chosen)
      return chosen
  ```

- [ ] **Step 5: Chạy test, xác nhận pass**

  Run: `.venv\Scripts\python -m pytest tests/planning/test_candidates.py -v`

  Expected: 9 passed.

- [ ] **Step 6: Lint, type check, commit**

  ```powershell
  .venv\Scripts\ruff format src tests
  .venv\Scripts\ruff check src tests
  .venv\Scripts\mypy src
  git add src/travel_agent/planning tests/planning
  git commit -m "feat: add deterministic candidate selection for plan requests"
  ```

---

### Task 2: Prompt sinh lịch trình

**Files:**
- Create: `src/travel_agent/planning/prompt.py`
- Create: `tests/planning/snapshots/generation_messages.json` (sinh bằng lệnh ở Step 5)
- Test: `tests/planning/test_prompt.py`

**Interfaces:**
- Consumes: `Place`, `PlanRequest` (domain); `make_place`, `make_request` (Task 1).
- Produces:
  - `SYSTEM_PROMPT: str`.
  - `build_messages(request: PlanRequest, candidates: Sequence[Place]) -> list[dict[str, str]]`. Trả đúng 2 message: `system`, `user`.

- [ ] **Step 1: Viết test (sẽ fail)**

  `tests/planning/test_prompt.py`:

  ```python
  import json
  import os
  from pathlib import Path

  from tests.planning.factories import make_place, make_request
  from travel_agent.domain.models import Category
  from travel_agent.planning.prompt import SYSTEM_PROMPT, build_messages

  SNAPSHOT = Path(__file__).parent / "snapshots" / "generation_messages.json"

  REQUEST = make_request(interests=["food", "history"])
  CANDIDATES = [
      make_place("t:a", Category.MUSEUM, hours="Mo-Su 07:00-17:00", name="Bảo tàng A"),
      make_place("t:b", Category.RESTAURANT, name="Quán B"),
  ]

  EXPECTED_USER = """YÊU CẦU
  city: hue
  start_date: 2026-12-01 (Tu)
  num_days: 1
  day_start: 08:00
  day_end: 21:00
  travel_mode: motorbike
  pace: moderate
  interests: food, history

  ĐỊA ĐIỂM (place_id | tên | loại | lat,lon | giờ mở cửa)
  t:a | Bảo tàng A | museum | 16.4700,107.5800 | Mo-Su 07:00-17:00
  t:b | Quán B | restaurant | 16.4700,107.5800 | unknown"""


  def test_two_messages_system_then_user() -> None:
      messages = build_messages(REQUEST, CANDIDATES)
      assert [message["role"] for message in messages] == ["system", "user"]
      assert messages[0]["content"] == SYSTEM_PROMPT


  def test_user_message_lists_request_and_candidates() -> None:
      assert build_messages(REQUEST, CANDIDATES)[1]["content"] == EXPECTED_USER


  def test_no_interests_is_stated() -> None:
      content = build_messages(make_request(), CANDIDATES)[1]["content"]
      assert "interests: không có" in content


  def test_newline_in_name_does_not_break_the_row() -> None:
      place = make_place("t:c", Category.CAFE, name="Cà phê\nC")
      content = build_messages(REQUEST, [place])[1]["content"]
      assert "t:c | Cà phê C | cafe" in content


  def test_messages_match_snapshot() -> None:
      """Đổi prompt là đổi dữ liệu train. Test này vỡ có chủ đích khi prompt đổi."""
      messages = build_messages(REQUEST, CANDIDATES)
      if os.environ.get("UPDATE_SNAPSHOTS") == "1":
          SNAPSHOT.parent.mkdir(exist_ok=True)
          SNAPSHOT.write_text(
              json.dumps(messages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
          )
      assert messages == json.loads(SNAPSHOT.read_text(encoding="utf-8"))
  ```

  Lưu ý: trong file thật, các dòng của `EXPECTED_USER` nằm sát lề trái (không thụt đầu dòng); khối ở trên bị thụt vì nằm trong danh sách Markdown.

- [ ] **Step 2: Chạy test, xác nhận fail**

  Run: `.venv\Scripts\python -m pytest tests/planning/test_prompt.py -v`

  Expected: FAIL với `ModuleNotFoundError: No module named 'travel_agent.planning.prompt'`.

- [ ] **Step 3: Implement**

  `src/travel_agent/planning/prompt.py`:

  ```python
  """Prompt sinh lịch trình. Nguồn duy nhất cho baseline, SFT, RL và runtime.

  Sửa file này làm lệch dữ liệu đã train. Snapshot test sẽ vỡ để nhắc việc đó.
  """

  from __future__ import annotations

  from collections.abc import Sequence

  from travel_agent.domain.models import Place, PlanRequest

  SYSTEM_PROMPT = """Bạn lập lịch trình du lịch cho thành phố Huế.

  Quy tắc bắt buộc:
  1. Chỉ dùng place_id có trong danh sách ĐỊA ĐIỂM. Không tự tạo place_id.
  2. Mỗi place_id chỉ xuất hiện một lần trong toàn bộ lịch trình.
  3. Số ngày bằng đúng num_days. Ngày đầu là start_date, các ngày sau liên tiếp.
  4. Mọi điểm dừng nằm trong khung day_start đến day_end. depart phải sau arrive.
  5. Điểm dừng trong ngày xếp theo thứ tự thời gian, không chồng giờ, và chừa đủ thời gian \
  di chuyển giữa hai điểm theo travel_mode (ước lượng từ tọa độ).
  6. Nếu địa điểm có giờ mở cửa thì cả khoảng arrive đến depart phải nằm trong giờ mở cửa. \
  "unknown" nghĩa là không rõ giờ.
  7. Số điểm dừng mỗi ngày theo pace: relaxed 3 đến 4, moderate 4 đến 6, packed 6 đến 8.
  8. Nếu khung ngày bao trọn 11:00-13:30 thì có một điểm restaurant trong khung đó. \
  Tương tự với 17:30-20:00.
  9. Ưu tiên địa điểm khớp interests.

  Chỉ trả về JSON đúng dạng sau, không thêm chữ nào khác:
  {"days":[{"date":"YYYY-MM-DD","stops":[{"place_id":"...","arrive":"HH:MM",\
  "depart":"HH:MM","note":null}]}]}"""

  CANDIDATE_HEADER = "ĐỊA ĐIỂM (place_id | tên | loại | lat,lon | giờ mở cửa)"
  WEEKDAY_CODES = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")  # mã ngày của OSM opening_hours


  def format_request(request: PlanRequest) -> str:
      weekday = WEEKDAY_CODES[request.start_date.weekday()]
      interests = ", ".join(request.interests) if request.interests else "không có"
      return "\n".join(
          [
              "YÊU CẦU",
              f"city: {request.city}",
              f"start_date: {request.start_date.isoformat()} ({weekday})",
              f"num_days: {request.num_days}",
              f"day_start: {request.day_start.strftime('%H:%M')}",
              f"day_end: {request.day_end.strftime('%H:%M')}",
              f"travel_mode: {request.travel_mode.value}",
              f"pace: {request.pace.value}",
              f"interests: {interests}",
          ]
      )


  def format_candidate(place: Place) -> str:
      name = " ".join(place.name.split())
      hours = place.opening_hours_raw or "unknown"
      coords = f"{place.coords.lat:.4f},{place.coords.lon:.4f}"
      return f"{place.id} | {name} | {place.category.value} | {coords} | {hours}"


  def build_messages(request: PlanRequest, candidates: Sequence[Place]) -> list[dict[str, str]]:
      rows = "\n".join(format_candidate(place) for place in candidates)
      user = f"{format_request(request)}\n\n{CANDIDATE_HEADER}\n{rows}"
      return [
          {"role": "system", "content": SYSTEM_PROMPT},
          {"role": "user", "content": user},
      ]
  ```

  Lưu ý: trong file thật, nội dung `SYSTEM_PROMPT` nằm sát lề trái. Dấu `\` cuối dòng nối dòng trong chuỗi, không sinh ký tự xuống dòng.

- [ ] **Step 4: Chạy test, xác nhận chỉ còn snapshot fail**

  Run: `.venv\Scripts\python -m pytest tests/planning/test_prompt.py -v`

  Expected: 4 passed, 1 failed (`test_messages_match_snapshot`, `FileNotFoundError`).

- [ ] **Step 5: Sinh snapshot, đọc lại bằng mắt**

  ```powershell
  $env:UPDATE_SNAPSHOTS="1"
  .venv\Scripts\python -m pytest tests/planning/test_prompt.py::test_messages_match_snapshot -v
  Remove-Item Env:UPDATE_SNAPSHOTS
  ```

  Mở `tests/planning/snapshots/generation_messages.json`, đọc system prompt một lượt: đủ 9 quy tắc, không có dòng nào bị dính nhau sai chỗ.

- [ ] **Step 6: Chạy lại toàn bộ, lint, commit**

  ```powershell
  .venv\Scripts\python -m pytest tests/planning -v
  .venv\Scripts\ruff format src tests
  .venv\Scripts\ruff check src tests
  .venv\Scripts\mypy src
  git add src/travel_agent/planning/prompt.py tests/planning
  git commit -m "feat: add single-source generation prompt with snapshot test"
  ```

  Expected: 14 passed.

---

### Task 3: Sinh request và bộ eval

**Files:**
- Create: `src/travel_agent/training/__init__.py` (rỗng)
- Create: `src/travel_agent/training/requests.py`
- Create: `tests/training/__init__.py` (rỗng)
- Test: `tests/training/test_requests.py`

**Interfaces:**
- Consumes: `INTEREST_CATEGORIES` (Task 1); `Pace`, `PlanRequest`, `TravelMode` (domain).
- Produces:
  - `Split(StrEnum)`: `DEV = "dev"`, `TEST = "test"`.
  - `EvalEntry(BaseModel)`: `key: str`, `split: Split`, `request: PlanRequest`.
  - `request_key(request: PlanRequest) -> str`: 16 ký tự hex.
  - `generate_requests(count: int, seed: int) -> list[PlanRequest]`: không trùng key.
  - `build_eval_set(seed: int) -> list[EvalEntry]`: 100 entry, 30 `test`, 70 `dev`.
  - `write_eval_set(entries: Sequence[EvalEntry], path: Path) -> None`.
  - `read_eval_set(path: Path, split: Split | None = None) -> list[EvalEntry]`.
  - Hằng `EVAL_SIZE = 100`, `TEST_SIZE = 30`.

- [ ] **Step 1: Viết test (sẽ fail)**

  Tạo `tests/training/__init__.py` rỗng. Tạo `tests/training/test_requests.py`:

  ```python
  from pathlib import Path

  from tests.planning.factories import make_request
  from travel_agent.domain.models import Pace
  from travel_agent.planning.candidates import INTEREST_CATEGORIES
  from travel_agent.training.requests import (
      EVAL_SIZE,
      TEST_SIZE,
      Split,
      build_eval_set,
      generate_requests,
      read_eval_set,
      request_key,
      write_eval_set,
  )


  def test_key_is_stable_and_sensitive_to_fields() -> None:
      assert request_key(make_request()) == request_key(make_request())
      assert request_key(make_request()) != request_key(make_request(pace=Pace.PACKED))
      assert len(request_key(make_request())) == 16


  def test_generates_unique_requests() -> None:
      requests = generate_requests(200, seed=1)
      assert len(requests) == 200
      assert len({request_key(request) for request in requests}) == 200


  def test_generation_is_deterministic() -> None:
      first = [request_key(request) for request in generate_requests(50, seed=9)]
      second = [request_key(request) for request in generate_requests(50, seed=9)]
      assert first == second


  def test_requests_stay_inside_eval_space() -> None:
      for request in generate_requests(200, seed=2):
          assert 1 <= request.num_days <= 3
          assert 1 <= len(request.interests) <= 3
          assert set(request.interests) <= set(INTEREST_CATEGORIES)
          assert request.interests == sorted(request.interests)


  def test_eval_set_split_sizes_and_no_overlap() -> None:
      entries = build_eval_set(seed=3)
      dev = {entry.key for entry in entries if entry.split is Split.DEV}
      test = {entry.key for entry in entries if entry.split is Split.TEST}
      assert len(entries) == EVAL_SIZE
      assert len(test) == TEST_SIZE
      assert len(dev) == EVAL_SIZE - TEST_SIZE
      assert not dev & test


  def test_entry_key_matches_its_request() -> None:
      for entry in build_eval_set(seed=3):
          assert entry.key == request_key(entry.request)


  def test_write_then_read_roundtrip(tmp_path: Path) -> None:
      entries = build_eval_set(seed=3)
      path = tmp_path / "eval" / "set.jsonl"
      write_eval_set(entries, path)
      assert read_eval_set(path) == entries
      assert len(read_eval_set(path, Split.TEST)) == TEST_SIZE
  ```

- [ ] **Step 2: Chạy test, xác nhận fail**

  Run: `.venv\Scripts\python -m pytest tests/training/test_requests.py -v`

  Expected: FAIL với `ModuleNotFoundError: No module named 'travel_agent.training'`.

- [ ] **Step 3: Implement**

  Tạo `src/travel_agent/training/__init__.py` rỗng. Tạo `src/travel_agent/training/requests.py`:

  ```python
  """Sinh PlanRequest đa dạng và bộ eval đóng băng (dev/test)."""

  from __future__ import annotations

  import datetime as dt
  import hashlib
  import json
  import random
  from collections.abc import Sequence
  from enum import StrEnum
  from pathlib import Path

  from pydantic import BaseModel

  from travel_agent.domain.models import Pace, PlanRequest, TravelMode
  from travel_agent.planning.candidates import INTEREST_CATEGORIES

  EVAL_SIZE = 100
  TEST_SIZE = 30

  BASE_DATE = dt.date(2026, 12, 1)
  DATE_SPAN_DAYS = 28
  NUM_DAYS_CHOICES = (1, 2, 3)
  DAY_STARTS = (dt.time(7, 30), dt.time(8, 0), dt.time(9, 0))
  DAY_ENDS = (dt.time(18, 0), dt.time(20, 0), dt.time(21, 0))
  MAX_INTERESTS = 3


  class Split(StrEnum):
      DEV = "dev"
      TEST = "test"


  class EvalEntry(BaseModel):
      key: str
      split: Split
      request: PlanRequest


  def request_key(request: PlanRequest) -> str:
      canonical = json.dumps(request.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
      return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


  def _random_request(rng: random.Random) -> PlanRequest:
      interest_count = rng.randint(1, MAX_INTERESTS)
      return PlanRequest(
          start_date=BASE_DATE + dt.timedelta(days=rng.randrange(DATE_SPAN_DAYS)),
          num_days=rng.choice(NUM_DAYS_CHOICES),
          day_start=rng.choice(DAY_STARTS),
          day_end=rng.choice(DAY_ENDS),
          travel_mode=rng.choice(list(TravelMode)),
          pace=rng.choice(list(Pace)),
          interests=sorted(rng.sample(sorted(INTEREST_CATEGORIES), interest_count)),
      )


  def generate_requests(count: int, seed: int) -> list[PlanRequest]:
      rng = random.Random(seed)
      by_key: dict[str, PlanRequest] = {}
      while len(by_key) < count:
          request = _random_request(rng)
          by_key.setdefault(request_key(request), request)
      return list(by_key.values())


  def build_eval_set(seed: int) -> list[EvalEntry]:
      """Xếp theo key (hash) rồi cắt: 30 entry đầu là test, còn lại là dev."""
      requests = sorted(generate_requests(EVAL_SIZE, seed), key=request_key)
      return [
          EvalEntry(
              key=request_key(request),
              split=Split.TEST if index < TEST_SIZE else Split.DEV,
              request=request,
          )
          for index, request in enumerate(requests)
      ]


  def write_eval_set(entries: Sequence[EvalEntry], path: Path) -> None:
      path.parent.mkdir(parents=True, exist_ok=True)
      with path.open("w", encoding="utf-8", newline="\n") as handle:
          for entry in entries:
              handle.write(entry.model_dump_json() + "\n")


  def read_eval_set(path: Path, split: Split | None = None) -> list[EvalEntry]:
      lines = path.read_text(encoding="utf-8").splitlines()
      entries = [EvalEntry.model_validate_json(line) for line in lines if line.strip()]
      return [entry for entry in entries if split is None or entry.split is split]
  ```

- [ ] **Step 4: Chạy test, xác nhận pass**

  Run: `.venv\Scripts\python -m pytest tests/training/test_requests.py -v`

  Expected: 7 passed.

- [ ] **Step 5: Lint, type check, commit**

  ```powershell
  .venv\Scripts\ruff format src tests
  .venv\Scripts\ruff check src tests
  .venv\Scripts\mypy src
  git add src/travel_agent/training tests/training
  git commit -m "feat: add request generator and frozen dev/test eval split"
  ```

---

### Task 4: Parse output và metric

**Cần Plan 1 Task 6–7 (validator) đã xong.**

**Files:**
- Create: `src/travel_agent/training/parsing.py`
- Create: `src/travel_agent/training/metrics.py`
- Create: `tests/training/factories.py`
- Test: `tests/training/test_parsing.py`
- Test: `tests/training/test_metrics.py`

**Interfaces:**
- Consumes:
  - `validate_itinerary(request, itinerary, places, travel) -> ValidationReport`, `IssueCode` (Plan 1 Task 6–7).
  - `InMemoryPlaceRepository` (`travel_agent.data.place_repository`), `TravelTimeProvider` (`travel_agent.routing.travel_time`).
  - `FixedTravelTime` (`tests/validation/factories.py`, Plan 1 Task 6).
  - `make_place`, `make_request` (Task 1).
- Produces:
  - `parse_itinerary(raw: str) -> Itinerary | None`.
  - `PlanOutcome(BaseModel)`: `key: str`, `parsed: bool`, `valid: bool`, `day_count: int = 0`, `stop_count: int = 0`, `unknown_place_count: int = 0`, `place_ids: list[str] = []`, `issue_codes: list[str] = []`, `latency_s: float = 0.0`.
  - `EvalSummary(BaseModel)`: `n: int`, `first_pass_valid_rate: float`, `parse_error_rate: float`, `unknown_place_rate: float`, `avg_stops_per_day: float`, `distinct_place_count: int`, `latency_p50_s: float`, `issue_code_distribution: dict[str, int]`.
  - `score_output(key: str, request: PlanRequest, raw: str, candidates: Sequence[Place], travel: TravelTimeProvider, latency_s: float) -> PlanOutcome`.
  - `summarize(outcomes: Sequence[PlanOutcome]) -> EvalSummary`.
  - `regressions(current: EvalSummary, previous: EvalSummary) -> list[str]`.
  - Test factories: `PLACES`, `REQUEST`, `VALID_RAW`, `UNKNOWN_PLACE_RAW`.

- [ ] **Step 1: Tạo test factories**

  `tests/training/factories.py`:

  ```python
  """Dữ liệu giả cho test eval. Không phải dữ liệu thật của Huế."""

  import json

  from tests.planning.factories import make_place, make_request
  from travel_agent.domain.models import Category

  PLACES = [
      make_place("t:museum", Category.MUSEUM),
      make_place("t:lunch", Category.RESTAURANT),
      make_place("t:dinner", Category.RESTAURANT),
      make_place("t:cafe", Category.CAFE),
  ]

  REQUEST = make_request()  # 1 ngày, 2026-12-01, moderate, 08:00-21:00


  def _raw(lunch_id: str) -> str:
      stops = [
          {"place_id": "t:museum", "arrive": "08:30", "depart": "10:30"},
          {"place_id": lunch_id, "arrive": "11:30", "depart": "12:30"},
          {"place_id": "t:dinner", "arrive": "18:00", "depart": "19:00"},
      ]
      return json.dumps({"days": [{"date": "2026-12-01", "stops": stops}]})


  VALID_RAW = _raw("t:lunch")
  UNKNOWN_PLACE_RAW = _raw("x:404")
  ```

- [ ] **Step 2: Viết test (sẽ fail)**

  `tests/training/test_parsing.py`:

  ```python
  from tests.training.factories import VALID_RAW
  from travel_agent.training.parsing import parse_itinerary


  def test_parses_valid_json() -> None:
      itinerary = parse_itinerary(VALID_RAW)
      assert itinerary is not None
      assert [stop.place_id for stop in itinerary.days[0].stops] == [
          "t:museum",
          "t:lunch",
          "t:dinner",
      ]


  def test_surrounding_whitespace_is_allowed() -> None:
      assert parse_itinerary(f"\n  {VALID_RAW}\n") is not None


  def test_not_json_returns_none() -> None:
      assert parse_itinerary("Đây là lịch trình của bạn") is None


  def test_code_fence_is_not_repaired() -> None:
      assert parse_itinerary(f"```json\n{VALID_RAW}\n```") is None


  def test_wrong_schema_returns_none() -> None:
      assert parse_itinerary('{"days": []}') is None
      assert parse_itinerary('{"plan": "x"}') is None
  ```

  `tests/training/test_metrics.py`:

  ```python
  import pytest

  from tests.training.factories import PLACES, REQUEST, UNKNOWN_PLACE_RAW, VALID_RAW
  from tests.validation.factories import FixedTravelTime
  from travel_agent.training.metrics import (
      EvalSummary,
      PlanOutcome,
      regressions,
      score_output,
      summarize,
  )


  def score(raw: str) -> PlanOutcome:
      return score_output("k1", REQUEST, raw, PLACES, FixedTravelTime(), latency_s=2.0)


  def test_valid_plan_is_scored_valid() -> None:
      outcome = score(VALID_RAW)
      assert (outcome.parsed, outcome.valid) == (True, True)
      assert (outcome.day_count, outcome.stop_count) == (1, 3)
      assert outcome.place_ids == ["t:museum", "t:lunch", "t:dinner"]
      assert outcome.unknown_place_count == 0
      assert outcome.latency_s == 2.0


  def test_place_outside_candidates_is_unknown() -> None:
      outcome = score(UNKNOWN_PLACE_RAW)
      assert (outcome.parsed, outcome.valid) == (True, False)
      assert outcome.unknown_place_count == 1
      assert "unknown_place" in outcome.issue_codes


  def test_unparseable_output_is_not_valid() -> None:
      outcome = score("không phải json")
      assert (outcome.parsed, outcome.valid) == (False, False)
      assert outcome.stop_count == 0


  def test_summarize_rates() -> None:
      outcomes = [
          PlanOutcome(
              key="a",
              parsed=True,
              valid=True,
              day_count=1,
              stop_count=4,
              place_ids=["p1", "p2", "p3", "p4"],
              issue_codes=["opening_hours_unknown"],
              latency_s=1.0,
          ),
          PlanOutcome(
              key="b",
              parsed=True,
              valid=False,
              day_count=2,
              stop_count=6,
              unknown_place_count=3,
              place_ids=["p1", "p5", "x1", "x2", "x3", "p6"],
              issue_codes=["unknown_place", "unknown_place", "unknown_place", "stop_overlap"],
              latency_s=3.0,
          ),
          PlanOutcome(key="c", parsed=False, valid=False, latency_s=5.0),
          PlanOutcome(key="d", parsed=False, valid=False, latency_s=7.0),
      ]
      summary = summarize(outcomes)
      assert summary.n == 4
      assert summary.first_pass_valid_rate == 0.25
      assert summary.parse_error_rate == 0.5
      assert summary.unknown_place_rate == 0.3  # 3 trên 10 stop
      assert summary.avg_stops_per_day == pytest.approx(10 / 3)
      assert summary.distinct_place_count == 9
      assert summary.latency_p50_s == 4.0
      assert summary.issue_code_distribution == {
          "opening_hours_unknown": 1,
          "stop_overlap": 1,
          "unknown_place": 3,
      }


  def test_summarize_all_unparsed_has_zero_rates() -> None:
      summary = summarize([PlanOutcome(key="a", parsed=False, valid=False)])
      assert summary.unknown_place_rate == 0.0
      assert summary.avg_stops_per_day == 0.0


  def test_summarize_rejects_empty_input() -> None:
      with pytest.raises(ValueError, match="không có kết quả"):
          summarize([])


  def _summary(valid_rate: float) -> EvalSummary:
      return EvalSummary(
          n=10,
          first_pass_valid_rate=valid_rate,
          parse_error_rate=0.0,
          unknown_place_rate=0.0,
          avg_stops_per_day=4.0,
          distinct_place_count=20,
          latency_p50_s=1.0,
          issue_code_distribution={},
      )


  def test_regression_when_valid_rate_drops() -> None:
      problems = regressions(_summary(0.4), _summary(0.5))
      assert len(problems) == 1
      assert "first_pass_valid_rate" in problems[0]


  def test_no_regression_when_equal_or_better() -> None:
      assert regressions(_summary(0.5), _summary(0.5)) == []
      assert regressions(_summary(0.6), _summary(0.5)) == []
  ```

- [ ] **Step 3: Chạy test, xác nhận fail**

  Run: `.venv\Scripts\python -m pytest tests/training/test_parsing.py tests/training/test_metrics.py -v`

  Expected: FAIL với `ModuleNotFoundError: No module named 'travel_agent.training.parsing'`.

- [ ] **Step 4: Implement `parsing.py`**

  `src/travel_agent/training/parsing.py`:

  ```python
  """Parse output thô của model thành Itinerary. Nghiêm ngặt: không sửa hộ output."""

  from __future__ import annotations

  from pydantic import ValidationError

  from travel_agent.domain.models import Itinerary


  def parse_itinerary(raw: str) -> Itinerary | None:
      """Trả None khi output không phải JSON hợp lệ theo schema Itinerary.

      Không cắt code fence, không vá JSON: output hỏng phải được tính là lỗi của model.
      """
      try:
          return Itinerary.model_validate_json(raw.strip())
      except ValidationError:
          return None
  ```

- [ ] **Step 5: Implement `metrics.py`**

  `src/travel_agent/training/metrics.py`:

  ```python
  """Chấm một output và tổng hợp metric cho cả bộ eval."""

  from __future__ import annotations

  import statistics
  from collections import Counter
  from collections.abc import Sequence

  from pydantic import BaseModel, Field

  from travel_agent.data.place_repository import InMemoryPlaceRepository
  from travel_agent.domain.models import Place, PlanRequest
  from travel_agent.routing.travel_time import TravelTimeProvider
  from travel_agent.training.parsing import parse_itinerary
  from travel_agent.validation.report import IssueCode
  from travel_agent.validation.validator import validate_itinerary


  class PlanOutcome(BaseModel):
      key: str
      parsed: bool
      valid: bool
      day_count: int = 0
      stop_count: int = 0
      unknown_place_count: int = 0
      place_ids: list[str] = Field(default_factory=list)
      issue_codes: list[str] = Field(default_factory=list)
      latency_s: float = 0.0


  class EvalSummary(BaseModel):
      n: int
      first_pass_valid_rate: float
      parse_error_rate: float
      unknown_place_rate: float
      avg_stops_per_day: float
      distinct_place_count: int
      latency_p50_s: float
      issue_code_distribution: dict[str, int]


  def score_output(
      key: str,
      request: PlanRequest,
      raw: str,
      candidates: Sequence[Place],
      travel: TravelTimeProvider,
      latency_s: float,
  ) -> PlanOutcome:
      """Chỉ candidate mới là địa điểm hợp lệ: id ngoài danh sách bị báo `unknown_place`."""
      itinerary = parse_itinerary(raw)
      if itinerary is None:
          return PlanOutcome(key=key, parsed=False, valid=False, latency_s=latency_s)
      report = validate_itinerary(request, itinerary, InMemoryPlaceRepository(candidates), travel)
      codes = [issue.code.value for issue in report.issues]
      place_ids = [stop.place_id for day in itinerary.days for stop in day.stops]
      return PlanOutcome(
          key=key,
          parsed=True,
          valid=report.is_valid,
          day_count=len(itinerary.days),
          stop_count=len(place_ids),
          unknown_place_count=codes.count(IssueCode.UNKNOWN_PLACE.value),
          place_ids=place_ids,
          issue_codes=codes,
          latency_s=latency_s,
      )


  def summarize(outcomes: Sequence[PlanOutcome]) -> EvalSummary:
      if not outcomes:
          raise ValueError("không có kết quả nào để tổng hợp")
      n = len(outcomes)
      stops = sum(outcome.stop_count for outcome in outcomes)
      days = sum(outcome.day_count for outcome in outcomes)
      unknown = sum(outcome.unknown_place_count for outcome in outcomes)
      codes = Counter(code for outcome in outcomes for code in outcome.issue_codes)
      return EvalSummary(
          n=n,
          first_pass_valid_rate=sum(outcome.valid for outcome in outcomes) / n,
          parse_error_rate=sum(not outcome.parsed for outcome in outcomes) / n,
          unknown_place_rate=unknown / stops if stops else 0.0,
          avg_stops_per_day=stops / days if days else 0.0,
          distinct_place_count=len({pid for outcome in outcomes for pid in outcome.place_ids}),
          latency_p50_s=statistics.median(outcome.latency_s for outcome in outcomes),
          issue_code_distribution=dict(sorted(codes.items())),
      )


  def regressions(current: EvalSummary, previous: EvalSummary) -> list[str]:
      """Cổng thăng hạng: trả danh sách lý do khi model mới kém mốc trước. Rỗng là qua cổng."""
      problems: list[str] = []
      if current.first_pass_valid_rate < previous.first_pass_valid_rate:
          problems.append(
              f"first_pass_valid_rate giảm: {current.first_pass_valid_rate:.3f} "
              f"< {previous.first_pass_valid_rate:.3f}"
          )
      return problems
  ```

- [ ] **Step 6: Chạy test, xác nhận pass**

  Run: `.venv\Scripts\python -m pytest tests/training/test_parsing.py tests/training/test_metrics.py -v`

  Expected: 13 passed.

  Nếu `test_valid_plan_is_scored_valid` fail vì validator báo ERROR: in `outcome.issue_codes`, đối chiếu với bảng luật ở Plan 1 Task 7, rồi sửa `VALID_RAW` trong `tests/training/factories.py` cho đúng luật. Không sửa validator để test này qua.

- [ ] **Step 7: Lint, type check, commit**

  ```powershell
  .venv\Scripts\ruff format src tests
  .venv\Scripts\ruff check src tests
  .venv\Scripts\mypy src
  git add src/travel_agent/training/parsing.py src/travel_agent/training/metrics.py tests/training
  git commit -m "feat: add strict output parsing and eval metrics with promotion gate"
  ```

---

### Task 5: Generator Ollama và runner

**Files:**
- Create: `src/travel_agent/training/generator.py`
- Create: `src/travel_agent/training/runner.py`
- Test: `tests/training/test_generator.py`
- Test: `tests/training/test_runner.py`

**Interfaces:**
- Consumes: `select_candidates` (Task 1), `build_messages` (Task 2), `EvalEntry`, `Split`, `request_key` (Task 3), `score_output`, `PlanOutcome` (Task 4), `Itinerary` (domain).
- Produces:
  - `GenerationError(RuntimeError)`.
  - `PlanGenerator(Protocol)`: `generate(self, messages: list[dict[str, str]]) -> str`.
  - `Transport = Callable[[str, dict[str, Any], float], dict[str, Any]]`.
  - `OllamaGenerator(model: str, *, host: str = DEFAULT_HOST, temperature: float = 0.0, seed: int = 0, num_predict: int = 2048, timeout_s: float = 600.0, schema_format: bool = True, transport: Transport | None = None)`.
  - `candidate_seed(key: str) -> int`.
  - `run_eval(entries: Sequence[EvalEntry], places: Sequence[Place], generator: PlanGenerator, travel: TravelTimeProvider, clock: Callable[[], float] = time.perf_counter) -> list[PlanOutcome]`.

- [ ] **Step 1: Viết test (sẽ fail)**

  `tests/training/test_generator.py`:

  ```python
  from typing import Any

  import pytest

  from travel_agent.domain.models import Itinerary
  from travel_agent.training.generator import GenerationError, OllamaGenerator

  MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


  class FakeTransport:
      def __init__(self, response: dict[str, Any]) -> None:
          self.response = response
          self.calls: list[tuple[str, dict[str, Any], float]] = []

      def __call__(self, url: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
          self.calls.append((url, payload, timeout_s))
          return self.response


  def test_sends_chat_request_with_thinking_off_and_schema() -> None:
      transport = FakeTransport({"message": {"content": '{"days": []}'}})
      generator = OllamaGenerator(
          "model-x", temperature=0.2, seed=5, num_predict=512, transport=transport
      )
      assert generator.generate(MESSAGES) == '{"days": []}'
      [(url, payload, timeout_s)] = transport.calls
      assert url == "http://127.0.0.1:11434/api/chat"
      assert timeout_s == 600.0
      assert payload == {
          "model": "model-x",
          "messages": MESSAGES,
          "stream": False,
          "think": False,
          "format": Itinerary.model_json_schema(),
          "options": {"temperature": 0.2, "seed": 5, "num_predict": 512},
      }


  def test_plain_json_format_when_schema_disabled() -> None:
      transport = FakeTransport({"message": {"content": "{}"}})
      OllamaGenerator("model-x", schema_format=False, transport=transport).generate(MESSAGES)
      assert transport.calls[0][1]["format"] == "json"


  def test_missing_content_raises() -> None:
      transport = FakeTransport({"error": "model not found"})
      with pytest.raises(GenerationError, match="model not found"):
          OllamaGenerator("model-x", transport=transport).generate(MESSAGES)
  ```

  `tests/training/test_runner.py`:

  ```python
  from tests.training.factories import PLACES, REQUEST, VALID_RAW
  from tests.validation.factories import FixedTravelTime
  from travel_agent.training.requests import EvalEntry, Split, request_key
  from travel_agent.training.runner import candidate_seed, run_eval


  class FakeGenerator:
      def __init__(self, raw: str) -> None:
          self.raw = raw
          self.seen: list[list[dict[str, str]]] = []

      def generate(self, messages: list[dict[str, str]]) -> str:
          self.seen.append(messages)
          return self.raw


  class FakeClock:
      def __init__(self) -> None:
          self.now = 0.0

      def __call__(self) -> float:
          self.now += 1.5
          return self.now


  ENTRY = EvalEntry(key=request_key(REQUEST), split=Split.DEV, request=REQUEST)


  def test_candidate_seed_is_stable_per_key() -> None:
      assert candidate_seed("00000010abcdef12") == 16
      assert candidate_seed(ENTRY.key) == candidate_seed(ENTRY.key)


  def test_runs_each_entry_and_scores_it() -> None:
      generator = FakeGenerator(VALID_RAW)
      [outcome] = run_eval([ENTRY], PLACES, generator, FixedTravelTime(), clock=FakeClock())
      assert outcome.key == ENTRY.key
      assert outcome.valid
      assert outcome.latency_s == 1.5
      [messages] = generator.seen
      assert [message["role"] for message in messages] == ["system", "user"]
      assert "t:museum" in messages[1]["content"]


  def test_bad_output_is_counted_not_raised() -> None:
      [outcome] = run_eval([ENTRY], PLACES, FakeGenerator("hỏng"), FixedTravelTime())
      assert not outcome.parsed
  ```

- [ ] **Step 2: Chạy test, xác nhận fail**

  Run: `.venv\Scripts\python -m pytest tests/training/test_generator.py tests/training/test_runner.py -v`

  Expected: FAIL với `ModuleNotFoundError: No module named 'travel_agent.training.generator'`.

- [ ] **Step 3: Implement `generator.py`**

  `src/travel_agent/training/generator.py`:

  ```python
  """Gọi model sinh lịch trình. Code eval chỉ phụ thuộc Protocol `PlanGenerator`."""

  from __future__ import annotations

  import json
  import urllib.error
  import urllib.request
  from collections.abc import Callable
  from typing import Any, Protocol

  from travel_agent.domain.models import Itinerary

  DEFAULT_HOST = "http://127.0.0.1:11434"

  Transport = Callable[[str, dict[str, Any], float], dict[str, Any]]


  class GenerationError(RuntimeError):
      """Lỗi hạ tầng khi gọi model (mạng, timeout, model chưa pull). Không phải lỗi của model."""


  class PlanGenerator(Protocol):
      def generate(self, messages: list[dict[str, str]]) -> str: ...


  def http_post_json(url: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
      body = json.dumps(payload).encode("utf-8")
      request = urllib.request.Request(
          url, data=body, headers={"Content-Type": "application/json"}
      )
      try:
          with urllib.request.urlopen(request, timeout=timeout_s) as response:
              decoded = json.loads(response.read().decode("utf-8"))
      except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
          raise GenerationError(f"Gọi Ollama thất bại: {exc}") from exc
      if not isinstance(decoded, dict):
          raise GenerationError("Ollama trả về dữ liệu không phải JSON object")
      return decoded


  class OllamaGenerator:
      """Gọi `/api/chat` của Ollama, thinking tắt, ép output theo JSON schema của Itinerary.

      `schema_format=False` dùng `format: "json"` cho bản Ollama không nhận schema này.
      """

      def __init__(
          self,
          model: str,
          *,
          host: str = DEFAULT_HOST,
          temperature: float = 0.0,
          seed: int = 0,
          num_predict: int = 2048,
          timeout_s: float = 600.0,
          schema_format: bool = True,
          transport: Transport | None = None,
      ) -> None:
          self._model = model
          self._url = f"{host.rstrip('/')}/api/chat"
          self._options = {"temperature": temperature, "seed": seed, "num_predict": num_predict}
          self._timeout_s = timeout_s
          self._format: dict[str, Any] | str = (
              Itinerary.model_json_schema() if schema_format else "json"
          )
          self._transport = transport or http_post_json

      def generate(self, messages: list[dict[str, str]]) -> str:
          payload = {
              "model": self._model,
              "messages": messages,
              "stream": False,
              "think": False,
              "format": self._format,
              "options": self._options,
          }
          response = self._transport(self._url, payload, self._timeout_s)
          message = response.get("message")
          content = message.get("content") if isinstance(message, dict) else None
          if not isinstance(content, str):
              raise GenerationError(f"Ollama không trả nội dung: {response.get('error', response)}")
          return content
  ```

- [ ] **Step 4: Implement `runner.py`**

  `src/travel_agent/training/runner.py`:

  ```python
  """Chạy bộ eval qua một PlanGenerator. Cùng key thì cùng candidate ở mọi lần chạy."""

  from __future__ import annotations

  import time
  from collections.abc import Callable, Sequence

  from travel_agent.domain.models import Place
  from travel_agent.planning.candidates import select_candidates
  from travel_agent.planning.prompt import build_messages
  from travel_agent.routing.travel_time import TravelTimeProvider
  from travel_agent.training.generator import PlanGenerator
  from travel_agent.training.metrics import PlanOutcome, score_output
  from travel_agent.training.requests import EvalEntry


  def candidate_seed(key: str) -> int:
      return int(key[:8], 16)


  def run_eval(
      entries: Sequence[EvalEntry],
      places: Sequence[Place],
      generator: PlanGenerator,
      travel: TravelTimeProvider,
      clock: Callable[[], float] = time.perf_counter,
  ) -> list[PlanOutcome]:
      """Không bắt `GenerationError`: lỗi hạ tầng làm hỏng lần eval, không tính cho model."""
      outcomes: list[PlanOutcome] = []
      for entry in entries:
          candidates = select_candidates(entry.request, places, candidate_seed(entry.key))
          messages = build_messages(entry.request, candidates)
          started = clock()
          raw = generator.generate(messages)
          latency_s = clock() - started
          outcomes.append(
              score_output(entry.key, entry.request, raw, candidates, travel, latency_s)
          )
      return outcomes
  ```

- [ ] **Step 5: Chạy test, xác nhận pass**

  Run: `.venv\Scripts\python -m pytest tests/training/test_generator.py tests/training/test_runner.py -v`

  Expected: 6 passed.

- [ ] **Step 6: Lint, type check, commit**

  ```powershell
  .venv\Scripts\ruff format src tests
  .venv\Scripts\ruff check src tests
  .venv\Scripts\mypy src
  git add src/travel_agent/training/generator.py src/travel_agent/training/runner.py tests/training
  git commit -m "feat: add Ollama plan generator and eval runner"
  ```

---

### Task 6: Lệnh CLI `make-evalset`, `eval` và ghi MLflow

**Files:**
- Create: `src/travel_agent/training/tracking.py`
- Create: `src/travel_agent/training/commands.py`
- Modify: `src/travel_agent/cli.py` (import, và một dòng trong `_build_parser`)
- Modify: `pyproject.toml` (extra `mlops`, override mypy cho `mlflow`)
- Test: `tests/training/test_tracking.py`
- Test: `tests/training/test_commands.py`

**Interfaces:**
- Consumes: `build_eval_set`, `write_eval_set`, `read_eval_set`, `Split` (Task 3); `EvalSummary`, `summarize`, `regressions` (Task 4); `OllamaGenerator`, `DEFAULT_HOST`, `run_eval` (Task 5); `ReviewStore`, `ReviewStatus` (`travel_agent.review`); `HaversineEstimator` (`travel_agent.routing.travel_time`).
- Produces:
  - `numeric_metrics(summary: EvalSummary) -> dict[str, float]`.
  - `log_eval_run(run_name: str, params: Mapping[str, str | int | float], summary: EvalSummary) -> None`.
  - `load_usable_places(db: Path) -> list[Place]`: mọi địa điểm trừ loại đã bị `rejected`, đã áp override của người duyệt.
  - `add_training_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None`.
  - Lệnh `travel-agent make-evalset --out PATH --seed N`.
  - Lệnh `travel-agent eval --db PATH --evalset PATH --model TAG --out PATH [--split dev|test] [--allow-test] [--limit N] [--host URL] [--temperature F] [--seed N] [--num-predict N] [--no-schema] [--run-name NAME] [--mlflow] [--baseline PATH]`. Exit code: 0 xong, 1 kém mốc `--baseline`, 2 thiếu file hoặc chạy `test` mà không có `--allow-test`.
  - File kết quả `--out`: `{"meta": {...}, "summary": {...EvalSummary...}}`. File `<out bỏ đuôi>.outcomes.jsonl`: mỗi dòng một `PlanOutcome`.

- [ ] **Step 1: Thêm extra `mlops` và override mypy**

  Trong `pyproject.toml`, sửa khối `[project.optional-dependencies]` thành:

  ```toml
  [project.optional-dependencies]
  dev = ["pytest>=8.0", "ruff>=0.6", "mypy>=1.10", "httpx>=0.27"]
  mlops = ["dvc>=3.50", "mlflow>=2.14"]
  ```

  Thêm vào cuối file:

  ```toml
  [[tool.mypy.overrides]]
  module = ["mlflow", "mlflow.*"]
  ignore_missing_imports = true
  ```

  Cài: `.venv\Scripts\python -m pip install -e ".[dev,mlops]"`

  Expected: cài xong không lỗi. Nếu `pip` báo xung đột phiên bản, dừng và báo lại; không tự hạ phiên bản phụ thuộc đang có.

- [ ] **Step 2: Viết test (sẽ fail)**

  `tests/training/test_tracking.py`:

  ```python
  import sys
  import types
  from typing import Any

  import pytest

  from travel_agent.training.metrics import EvalSummary
  from travel_agent.training.tracking import log_eval_run, numeric_metrics

  SUMMARY = EvalSummary(
      n=10,
      first_pass_valid_rate=0.4,
      parse_error_rate=0.1,
      unknown_place_rate=0.05,
      avg_stops_per_day=4.5,
      distinct_place_count=30,
      latency_p50_s=12.0,
      issue_code_distribution={"stop_overlap": 3},
  )


  def test_numeric_metrics_flattens_issue_codes() -> None:
      assert numeric_metrics(SUMMARY) == {
          "n": 10.0,
          "first_pass_valid_rate": 0.4,
          "parse_error_rate": 0.1,
          "unknown_place_rate": 0.05,
          "avg_stops_per_day": 4.5,
          "distinct_place_count": 30.0,
          "latency_p50_s": 12.0,
          "issue.stop_overlap": 3.0,
      }


  class FakeRun:
      def __enter__(self) -> "FakeRun":
          return self

      def __exit__(self, *exc: object) -> None:
          return None


  def test_log_eval_run_sends_params_and_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
      calls: list[tuple[str, Any]] = []

      def start_run(run_name: str) -> FakeRun:
          calls.append(("run", run_name))
          return FakeRun()

      fake = types.SimpleNamespace(
          set_tracking_uri=lambda uri: calls.append(("uri", uri)),
          set_experiment=lambda name: calls.append(("experiment", name)),
          start_run=start_run,
          log_params=lambda params: calls.append(("params", params)),
          log_metrics=lambda metrics: calls.append(("metrics", metrics)),
      )
      monkeypatch.setitem(sys.modules, "mlflow", fake)
      monkeypatch.setenv("MLFLOW_TRACKING_URI", "sqlite:///x.db")

      log_eval_run("baseline", {"model": "m"}, SUMMARY)

      assert calls == [
          ("uri", "sqlite:///x.db"),
          ("experiment", "hue-planner"),
          ("run", "baseline"),
          ("params", {"model": "m"}),
          ("metrics", numeric_metrics(SUMMARY)),
      ]
  ```

  `tests/training/test_commands.py`:

  ```python
  import json
  from pathlib import Path
  from typing import Any

  import pytest

  from tests.planning.factories import make_pool
  from tests.review.conftest import NOW
  from travel_agent.cli import main
  from travel_agent.data.place_repository import SqlitePlaceRepository
  from travel_agent.review.models import ReviewInput, ReviewStatus
  from travel_agent.review.store import ReviewStore
  from travel_agent.training import commands
  from travel_agent.training.commands import load_usable_places
  from travel_agent.training.requests import EVAL_SIZE, TEST_SIZE, read_eval_set


  class FakeGenerator:
      def __init__(self, model: str, **kwargs: Any) -> None:
          self.model = model

      def generate(self, messages: list[dict[str, str]]) -> str:
          return "không phải json"


  @pytest.fixture
  def db(tmp_path: Path) -> Path:
      path = tmp_path / "hue.sqlite"
      repo = SqlitePlaceRepository(path)
      repo.upsert_many(make_pool(per_category=6))
      repo.close()
      return path


  @pytest.fixture
  def evalset(tmp_path: Path) -> Path:
      path = tmp_path / "eval.jsonl"
      assert main(["make-evalset", "--out", str(path), "--seed", "11"]) == 0
      return path


  def run_eval_cmd(db: Path, evalset: Path, out: Path, *extra: str) -> int:
      base = ["eval", "--db", str(db), "--evalset", str(evalset), "--model", "fake"]
      return main([*base, "--out", str(out), "--limit", "5", *extra])


  def test_make_evalset_writes_100_entries(evalset: Path) -> None:
      assert len(read_eval_set(evalset)) == EVAL_SIZE


  def test_load_usable_places_drops_rejected(db: Path) -> None:
      store = ReviewStore(db)
      store.save(ReviewInput(place_id="t:cafe/0", status=ReviewStatus.REJECTED), NOW)
      store.close()
      ids = {place.id for place in load_usable_places(db)}
      assert "t:cafe/0" not in ids
      assert "t:cafe/1" in ids


  def test_eval_writes_summary_and_outcomes(
      db: Path, evalset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
  ) -> None:
      monkeypatch.setattr(commands, "OllamaGenerator", FakeGenerator)
      out = tmp_path / "reports" / "run.json"
      assert run_eval_cmd(db, evalset, out, "--run-name", "smoke") == 0
      report = json.loads(out.read_text(encoding="utf-8"))
      assert report["summary"]["n"] == 5
      assert report["summary"]["parse_error_rate"] == 1.0
      assert report["meta"]["run_name"] == "smoke"
      assert report["meta"]["model"] == "fake"
      assert report["meta"]["split"] == "dev"
      assert len(report["meta"]["evalset_sha256"]) == 64
      outcomes = (tmp_path / "reports" / "run.outcomes.jsonl").read_text(encoding="utf-8")
      assert len(outcomes.splitlines()) == 5


  def test_eval_fails_gate_against_better_baseline(
      db: Path, evalset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
  ) -> None:
      monkeypatch.setattr(commands, "OllamaGenerator", FakeGenerator)
      first = tmp_path / "first.json"
      assert run_eval_cmd(db, evalset, first) == 0
      better = json.loads(first.read_text(encoding="utf-8"))
      better["summary"]["first_pass_valid_rate"] = 0.5
      baseline = tmp_path / "baseline.json"
      baseline.write_text(json.dumps(better), encoding="utf-8")
      assert run_eval_cmd(db, evalset, tmp_path / "second.json", "--baseline", str(baseline)) == 1


  def test_eval_refuses_test_split_without_flag(
      db: Path, evalset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
  ) -> None:
      monkeypatch.setattr(commands, "OllamaGenerator", FakeGenerator)
      out = tmp_path / "t.json"
      assert run_eval_cmd(db, evalset, out, "--split", "test") == 2
      assert not out.exists()
      assert run_eval_cmd(db, evalset, out, "--split", "test", "--allow-test") == 0
      assert json.loads(out.read_text(encoding="utf-8"))["summary"]["n"] == min(5, TEST_SIZE)


  def test_eval_refuses_missing_db(evalset: Path, tmp_path: Path) -> None:
      assert run_eval_cmd(tmp_path / "missing.sqlite", evalset, tmp_path / "x.json") == 2
  ```

- [ ] **Step 3: Chạy test, xác nhận fail**

  Run: `.venv\Scripts\python -m pytest tests/training/test_tracking.py tests/training/test_commands.py -v`

  Expected: FAIL với `ModuleNotFoundError: No module named 'travel_agent.training.tracking'`.

- [ ] **Step 4: Implement `tracking.py`**

  `src/travel_agent/training/tracking.py`:

  ```python
  """Ghi tham số và metric của một lần eval vào MLflow. Import mlflow trễ: chỉ cần khi ghi."""

  from __future__ import annotations

  import os
  from collections.abc import Mapping

  from travel_agent.training.metrics import EvalSummary

  # Ngoài OneDrive: store không bị đồng bộ và tránh đường dẫn có dấu.
  DEFAULT_TRACKING_URI = "sqlite:///C:/dev/travelagent-runs/mlflow.db"
  EXPERIMENT = "hue-planner"


  def numeric_metrics(summary: EvalSummary) -> dict[str, float]:
      metrics = {
          "n": float(summary.n),
          "first_pass_valid_rate": summary.first_pass_valid_rate,
          "parse_error_rate": summary.parse_error_rate,
          "unknown_place_rate": summary.unknown_place_rate,
          "avg_stops_per_day": summary.avg_stops_per_day,
          "distinct_place_count": float(summary.distinct_place_count),
          "latency_p50_s": summary.latency_p50_s,
      }
      for code, count in summary.issue_code_distribution.items():
          metrics[f"issue.{code}"] = float(count)
      return metrics


  def log_eval_run(
      run_name: str, params: Mapping[str, str | int | float], summary: EvalSummary
  ) -> None:
      import mlflow

      mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI))
      mlflow.set_experiment(EXPERIMENT)
      with mlflow.start_run(run_name=run_name):
          mlflow.log_params(dict(params))
          mlflow.log_metrics(numeric_metrics(summary))
  ```

- [ ] **Step 5: Implement `commands.py`**

  `src/travel_agent/training/commands.py`:

  ```python
  """Lệnh CLI cho eval: make-evalset, eval."""

  from __future__ import annotations

  import argparse
  import hashlib
  import json
  import subprocess
  import sys
  from pathlib import Path

  from travel_agent.domain.models import Place
  from travel_agent.review.models import ReviewStatus
  from travel_agent.review.store import ReviewStore
  from travel_agent.routing.travel_time import HaversineEstimator
  from travel_agent.training.generator import DEFAULT_HOST, OllamaGenerator
  from travel_agent.training.metrics import EvalSummary, regressions, summarize
  from travel_agent.training.requests import Split, build_eval_set, read_eval_set, write_eval_set
  from travel_agent.training.runner import run_eval
  from travel_agent.training.tracking import log_eval_run

  EXIT_OK = 0
  EXIT_REGRESSION = 1
  EXIT_USAGE = 2


  def add_training_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
      evalset = sub.add_parser("make-evalset", help="Sinh bộ eval 100 request (chạy một lần)")
      evalset.add_argument("--out", type=Path, required=True)
      evalset.add_argument("--seed", type=int, required=True)
      evalset.set_defaults(func=_cmd_make_evalset)

      run = sub.add_parser("eval", help="Chạy bộ eval qua một model trong Ollama")
      run.add_argument("--db", type=Path, required=True)
      run.add_argument("--evalset", type=Path, required=True)
      run.add_argument("--model", required=True)
      run.add_argument("--out", type=Path, required=True)
      run.add_argument("--split", type=Split, choices=list(Split), default=Split.DEV)
      run.add_argument("--allow-test", action="store_true", help="Cho phép chạy bộ test đóng băng")
      run.add_argument("--limit", type=int, help="Chỉ chạy N request đầu (smoke test)")
      run.add_argument("--host", default=DEFAULT_HOST)
      run.add_argument("--temperature", type=float, default=0.0)
      run.add_argument("--seed", type=int, default=0)
      run.add_argument("--num-predict", type=int, default=2048)
      run.add_argument("--no-schema", action="store_true", help='Dùng format "json" thay schema')
      run.add_argument("--run-name", default="eval")
      run.add_argument("--mlflow", action="store_true", help="Ghi tham số và metric vào MLflow")
      run.add_argument("--baseline", type=Path, help="File kết quả mốc trước; kém hơn thì exit 1")
      run.set_defaults(func=_cmd_eval)


  def load_usable_places(db: Path) -> list[Place]:
      """Mọi địa điểm trừ loại người duyệt đã loại; đã áp override của người duyệt."""
      store = ReviewStore(db)
      try:
          items, _ = store.query(limit=-1)  # LIMIT -1 = không giới hạn
      finally:
          store.close()
      return [item.effective_place() for item in items if item.status is not ReviewStatus.REJECTED]


  def file_sha256(path: Path) -> str:
      return hashlib.sha256(path.read_bytes()).hexdigest()


  def current_commit() -> str:
      try:
          result = subprocess.run(
              ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
          )
      except (OSError, subprocess.CalledProcessError):
          return "unknown"
      return result.stdout.strip()


  def _cmd_make_evalset(args: argparse.Namespace) -> int:
      entries = build_eval_set(args.seed)
      write_eval_set(entries, args.out)
      test = sum(1 for entry in entries if entry.split is Split.TEST)
      dev = len(entries) - test
      print(f"Đã ghi {len(entries)} request vào {args.out} (dev {dev}, test {test}).")
      return EXIT_OK


  def _cmd_eval(args: argparse.Namespace) -> int:
      for path in (args.db, args.evalset):
          if not path.exists():
              print(f"Không tìm thấy {path}.", file=sys.stderr)
              return EXIT_USAGE
      if args.split is Split.TEST and not args.allow_test:
          print("Bộ test đóng băng. Thêm --allow-test khi chạy so sánh cuối.", file=sys.stderr)
          return EXIT_USAGE

      entries = read_eval_set(args.evalset, args.split)
      if args.limit is not None:
          entries = entries[: args.limit]
      generator = OllamaGenerator(
          args.model,
          host=args.host,
          temperature=args.temperature,
          seed=args.seed,
          num_predict=args.num_predict,
          schema_format=not args.no_schema,
      )
      outcomes = run_eval(entries, load_usable_places(args.db), generator, HaversineEstimator())
      summary = summarize(outcomes)
      meta: dict[str, str | int | float] = {
          "run_name": args.run_name,
          "model": args.model,
          "split": args.split.value,
          "temperature": args.temperature,
          "seed": args.seed,
          "num_predict": args.num_predict,
          "git_commit": current_commit(),
          "evalset_sha256": file_sha256(args.evalset),
          "db_sha256": file_sha256(args.db),
      }

      args.out.parent.mkdir(parents=True, exist_ok=True)
      report = {"meta": meta, "summary": summary.model_dump(mode="json")}
      args.out.write_text(
          json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
      )
      outcomes_path = args.out.with_suffix(".outcomes.jsonl")
      with outcomes_path.open("w", encoding="utf-8", newline="\n") as handle:
          for outcome in outcomes:
              handle.write(outcome.model_dump_json() + "\n")

      print(f"{args.run_name}: {summary.n} request, model {args.model}, split {args.split.value}")
      print(f"  first_pass_valid_rate: {summary.first_pass_valid_rate:.3f}")
      print(f"  parse_error_rate:      {summary.parse_error_rate:.3f}")
      print(f"  unknown_place_rate:    {summary.unknown_place_rate:.3f}")
      print(f"  avg_stops_per_day:     {summary.avg_stops_per_day:.2f}")
      print(f"  distinct_place_count:  {summary.distinct_place_count}")
      print(f"  latency_p50_s:         {summary.latency_p50_s:.1f}")
      for code, count in summary.issue_code_distribution.items():
          print(f"  issue {code}: {count}")

      if args.mlflow:
          log_eval_run(args.run_name, meta, summary)
      if args.baseline is not None:
          previous = json.loads(args.baseline.read_text(encoding="utf-8"))["summary"]
          problems = regressions(summary, EvalSummary.model_validate(previous))
          for problem in problems:
              print(f"KHÔNG QUA CỔNG: {problem}", file=sys.stderr)
          if problems:
              return EXIT_REGRESSION
      return EXIT_OK
  ```

- [ ] **Step 6: Đăng ký lệnh trong `cli.py`**

  Trong `src/travel_agent/cli.py`, thêm import (đặt đúng thứ tự alphabet, sau dòng import `travel_agent.sources.store`):

  ```python
  from travel_agent.training.commands import add_training_commands
  ```

  Trong `_build_parser`, ngay trước `return parser`, thêm:

  ```python
      add_training_commands(sub)
  ```

  Sửa docstring dòng đầu file thành:

  ```python
  """CLI: travel-agent fetch-osm | ingest-* | places | review | export-... | make-evalset | eval"""
  ```

- [ ] **Step 7: Chạy test, xác nhận pass**

  Run: `.venv\Scripts\python -m pytest tests/training tests/test_cli.py -v`

  Expected: toàn bộ pass (34 test trong `tests/training` chưa tính `test_evalset_file.py`, cộng các test CLI cũ).

- [ ] **Step 8: Lint, type check, commit**

  ```powershell
  .venv\Scripts\ruff format src tests
  .venv\Scripts\ruff check src tests
  .venv\Scripts\mypy src
  git add pyproject.toml src/travel_agent/cli.py src/travel_agent/training tests/training
  git commit -m "feat: add make-evalset and eval commands with MLflow logging and gate"
  ```

---

### Task 7: Khung MLOps (config, DVC, bộ eval đóng băng, CI)

**Files:**
- Create: `configs/eval.yaml`
- Create: `dvc.yaml`
- Create: `data/eval/hue_eval_v1.jsonl` (sinh bằng `dvc repro`)
- Create: `data/hue.sqlite.dvc` (sinh bằng `dvc add`)
- Create: `scripts/check.ps1`
- Create: `.github/workflows/ci.yml`
- Modify: `README.md` (thêm mục "Eval và MLOps")
- Test: `tests/training/test_evalset_file.py`

**Interfaces:**
- Consumes: lệnh `make-evalset`, `eval` (Task 6); `read_eval_set`, `request_key`, `Split`, `EVAL_SIZE`, `TEST_SIZE` (Task 3).
- Produces:
  - `configs/eval.yaml` với khóa `evalset.seed`, `baseline.model`, `generation.temperature`, `generation.seed`, `generation.num_predict`.
  - Stage DVC `make_evalset` (đóng băng sau lần chạy đầu) và `baseline_eval`.
  - File `data/eval/hue_eval_v1.jsonl` do git theo dõi.

- [ ] **Step 1: Tạo config**

  `configs/eval.yaml`:

  ```yaml
  evalset:
    seed: 20261111
  baseline:
    # Tag Ollama của Qwen3.5 4B. Giá trị này là phỏng đoán theo quy ước đặt tên;
    # Task 8 Step 1 xác minh và sửa lại.
    model: qwen3.5:4b
  generation:
    temperature: 0.0
    seed: 0
    num_predict: 2048
  ```

- [ ] **Step 2: Khởi tạo DVC, đặt cache và remote ngoài OneDrive**

  ```powershell
  New-Item -ItemType Directory -Force C:\dev\travelagent-dvc, C:\dev\travelagent-dvc-cache, C:\dev\travelagent-runs
  .venv\Scripts\dvc init
  .venv\Scripts\dvc cache dir --local C:\dev\travelagent-dvc-cache
  .venv\Scripts\dvc remote add --local -d localstore C:\dev\travelagent-dvc
  .venv\Scripts\dvc add data/hue.sqlite
  ```

  Expected: có thư mục `.dvc/`, file `data/hue.sqlite.dvc`. `--local` ghi đường dẫn máy này vào `.dvc/config.local` (không commit).

  Nếu `dvc init` hoặc `dvc add` lỗi vì đường dẫn có dấu (`Máy tính`): dừng, báo lại. Cách xử lý đã ghi trong roadmap là chuyển project sang `C:\dev\TravelAgent`; đó là quyết định của chủ dự án.

- [ ] **Step 3: Viết `dvc.yaml`**

  ```yaml
  vars:
    - configs/eval.yaml

  stages:
    make_evalset:
      cmd: >-
        python -m travel_agent make-evalset
        --seed ${evalset.seed}
        --out data/eval/hue_eval_v1.jsonl
      params:
        - configs/eval.yaml:
            - evalset
      outs:
        - data/eval/hue_eval_v1.jsonl:
            cache: false

    baseline_eval:
      cmd: >-
        python -m travel_agent eval
        --db data/hue.sqlite
        --evalset data/eval/hue_eval_v1.jsonl
        --split dev
        --model ${baseline.model}
        --temperature ${generation.temperature}
        --seed ${generation.seed}
        --num-predict ${generation.num_predict}
        --run-name baseline
        --mlflow
        --out reports/eval/baseline_dev.json
      deps:
        - data/hue.sqlite
        - data/eval/hue_eval_v1.jsonl
        - src/travel_agent/planning
        - src/travel_agent/training
        - src/travel_agent/validation
      params:
        - configs/eval.yaml:
            - baseline
            - generation
      outs:
        - reports/eval/baseline_dev.outcomes.jsonl
      metrics:
        - reports/eval/baseline_dev.json:
            cache: false
  ```

  `cache: false` giữ file trong git thay vì cache DVC: bộ eval và file metric đều nhỏ và cần đọc được trong diff.

- [ ] **Step 4: Sinh bộ eval và đóng băng stage**

  ```powershell
  .venv\Scripts\Activate.ps1
  $env:PYTHONPATH="src"
  dvc repro make_evalset
  dvc freeze make_evalset
  ```

  Expected: in `Đã ghi 100 request vào data/eval/hue_eval_v1.jsonl (dev 70, test 30).` Sau `dvc freeze`, stage `make_evalset` trong `dvc.yaml` có `frozen: true`, nên `dvc repro` về sau không sinh lại bộ eval dù code sinh request thay đổi.

- [ ] **Step 5: Viết test canh file bộ eval**

  `tests/training/test_evalset_file.py`:

  ```python
  """Canh file bộ eval đã commit. Vỡ nếu file bị sửa tay hoặc sinh lại sai."""

  from pathlib import Path

  from travel_agent.training.requests import (
      EVAL_SIZE,
      TEST_SIZE,
      Split,
      read_eval_set,
      request_key,
  )

  EVALSET = Path(__file__).parents[2] / "data" / "eval" / "hue_eval_v1.jsonl"


  def test_committed_eval_set_is_intact() -> None:
      entries = read_eval_set(EVALSET)
      keys = [entry.key for entry in entries]
      assert len(entries) == EVAL_SIZE
      assert len(set(keys)) == EVAL_SIZE
      assert sum(1 for entry in entries if entry.split is Split.TEST) == TEST_SIZE
      assert all(entry.key == request_key(entry.request) for entry in entries)
  ```

  Run: `.venv\Scripts\python -m pytest tests/training/test_evalset_file.py -v`

  Expected: 1 passed.

- [ ] **Step 6: Script kiểm tra local**

  `scripts/check.ps1`:

  ```powershell
  # Chạy toàn bộ kiểm tra không cần GPU. Dùng trước khi commit; CI chạy cùng các bước này.
  $ErrorActionPreference = "Stop"
  $py = ".venv\Scripts\python"

  & $py -m ruff format --check src tests
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  & $py -m ruff check src tests
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  & $py -m mypy src
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  & $py -m pytest
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  & $py -m dvc stage list
  exit $LASTEXITCODE
  ```

  Run: `powershell -File scripts\check.ps1`

  Expected: mọi bước pass; bước cuối in hai stage `make_evalset` và `baseline_eval`.

- [ ] **Step 7: Workflow CI**

  `.github/workflows/ci.yml`:

  ```yaml
  name: ci

  on:
    push:
    pull_request:

  jobs:
    check:
      runs-on: ubuntu-latest
      steps:
        - uses: actions/checkout@v4
        - uses: actions/setup-python@v5
          with:
            python-version: "3.11"
        - run: python -m pip install -e ".[dev,mlops]"
        - run: python -m ruff format --check src tests
        - run: python -m ruff check src tests
        - run: python -m mypy src
        - run: python -m pytest
        - run: python -m dvc stage list
  ```

  Workflow không chạy bước nào cần GPU hay Ollama. Repo chưa có remote, nên workflow chỉ chạy sau khi chủ dự án tạo repo GitHub và push. Kiểm tra phiên bản mới nhất của `actions/checkout` và `actions/setup-python` trước khi push.

- [ ] **Step 8: Cập nhật README**

  Thêm vào `README.md`, ngay trước mục `## Kiểm thử`:

  ````markdown
  ## Eval và MLOps

  Thiết kế: `docs/superpowers/specs/2026-11-11-sft-rl-training-design.md`.

  Cài thêm công cụ MLOps:

  ```powershell
  .venv\Scripts\python -m pip install -e ".[dev,mlops]"
  ```

  Cấu hình một lần trên mỗi máy (cache DVC, DVC remote và MLflow nằm ngoài OneDrive):

  ```powershell
  New-Item -ItemType Directory -Force C:\dev\travelagent-dvc, C:\dev\travelagent-dvc-cache, C:\dev\travelagent-runs
  .venv\Scripts\dvc cache dir --local C:\dev\travelagent-dvc-cache
  .venv\Scripts\dvc remote add --local -d localstore C:\dev\travelagent-dvc
  ```

  Chạy pipeline (cần Ollama đang chạy và đã pull model ghi trong `configs/eval.yaml`):

  ```powershell
  .venv\Scripts\Activate.ps1
  $env:PYTHONPATH="src"
  dvc repro baseline_eval
  dvc metrics show
  ```

  - **Bộ eval:** `data/eval/hue_eval_v1.jsonl`, 70 dev và 30 test. Stage `make_evalset` đã đóng băng;
    không sinh lại. Lệnh `eval --split test` cần thêm `--allow-test` và chỉ dùng cho lần so sánh cuối.
  - **Tham số:** sửa trong `configs/eval.yaml`, không sửa trong `dvc.yaml`.
  - **MLflow:** `.venv\Scripts\mlflow ui --backend-store-uri sqlite:///C:/dev/travelagent-runs/mlflow.db`.
  - **Lưu ý:** duyệt tay địa điểm làm đổi `data/hue.sqlite`, nên `dvc repro` sẽ chạy lại eval.
    Chạy `dvc add data/hue.sqlite` sau mỗi đợt duyệt để ghi version dữ liệu mới.
  ````

  Trong mục `## Kiểm thử`, thêm dòng sau khối lệnh:

  ```markdown
  Hoặc chạy tất cả bằng một lệnh: `powershell -File scripts\check.ps1`.
  ```

- [ ] **Step 9: Commit**

  ```powershell
  powershell -File scripts\check.ps1
  git add configs dvc.yaml .dvc .dvcignore data/hue.sqlite.dvc data/.gitignore data/eval scripts/check.ps1 .github README.md tests/training/test_evalset_file.py
  git status --short
  git commit -m "chore: add DVC pipeline, frozen eval set, CI workflow and local check script"
  ```

  Trước khi commit, đọc `git status --short`: không có file `.dvc/config.local`, không có `data/hue.sqlite`, không có thư mục cache. Nếu `data/.gitignore` không tồn tại (DVC không tạo vì `.gitignore` gốc đã bỏ qua `data/*.sqlite`), bỏ nó khỏi lệnh `git add`.

---

### Task 8: Chạy baseline 4B và ghi báo cáo

Task này cần Ollama và GPU. Không có unit test; kiểm bằng smoke run.

**Files:**
- Modify: `configs/eval.yaml` (tag model đã xác minh)
- Create: `reports/eval/baseline_dev.json` (sinh bằng `dvc repro`)
- Create: `reports/eval/README.md`
- Create: `dvc.lock` (sinh bằng `dvc repro`)

**Interfaces:**
- Consumes: pipeline DVC (Task 7).
- Produces: `reports/eval/baseline_dev.json`, là mốc `--baseline` cho plan SFT.

- [ ] **Step 1: Xác minh tag và license của model**

  1. Mở `https://ollama.com/library`, tìm Qwen3.5, ghi lại tag chính xác của bản 4B.
  2. Pull và xem thông tin:

     ```powershell
     ollama pull <tag vừa tìm được>
     ollama show <tag vừa tìm được>
     ```

  3. Đọc mục license trong output của `ollama show`. Spec giả định Apache-2.0. Nếu license khác, dừng và báo lại trước khi chạy tiếp.
  4. Sửa `baseline.model` trong `configs/eval.yaml` thành tag vừa xác minh, và xóa hai dòng comment "phỏng đoán".

  Nếu không có bản 4B trên Ollama: dừng và báo lại. Không tự thay bằng cỡ model khác.

- [ ] **Step 2: Smoke run 3 request**

  ```powershell
  $env:PYTHONPATH="src"
  .venv\Scripts\python -m travel_agent eval --db data\hue.sqlite --evalset data\eval\hue_eval_v1.jsonl --model <tag> --limit 3 --run-name smoke --out C:\dev\travelagent-runs\smoke.json
  ```

  Expected: in bảng metric với `3 request`. Đọc `C:\dev\travelagent-runs\smoke.outcomes.jsonl`.

  Xử lý lỗi:
  - `Gọi Ollama thất bại`: kiểm tra Ollama đang chạy (`ollama ps`).
  - Ollama báo lỗi về `format` hoặc schema: chạy lại với `--no-schema`. Nếu cách này chạy được, thêm `--no-schema` vào `cmd` của stage `baseline_eval` trong `dvc.yaml` và ghi lý do trong `reports/eval/README.md`.
  - Ollama báo model không hỗ trợ `think`: dừng và báo lại; cần quyết định cách tắt thinking cho model này.
  - `parse_error_rate` bằng 1.0 ở cả 3 request: in một output thô để xem model trả gì trước khi chạy đầy đủ.

- [ ] **Step 3: Chạy baseline đầy đủ trên dev**

  ```powershell
  .venv\Scripts\Activate.ps1
  $env:PYTHONPATH="src"
  dvc repro baseline_eval
  dvc metrics show
  ```

  Expected: `reports/eval/baseline_dev.json` có `summary.n` bằng 70. Thời gian chạy chưa đo; `latency_p50_s` của smoke run nhân 70 cho ước lượng.

- [ ] **Step 4: Xem mẫu output bằng mắt**

  Mở `reports/eval/baseline_dev.outcomes.jsonl`. Đọc 5 dòng `valid: true` và 5 dòng `valid: false`. Ghi lại: loại lỗi nào nhiều nhất, model có bịa `place_id` không, số stop mỗi ngày có hợp `pace` không.

- [ ] **Step 5: Viết báo cáo baseline**

  `reports/eval/README.md`, điền số thật lấy từ `reports/eval/baseline_dev.json`:

  ```markdown
  # Kết quả eval

  Mỗi dòng là một lần chạy trên bộ dev (70 request) của `data/eval/hue_eval_v1.jsonl`.
  Số liệu gốc nằm trong file JSON cùng thư mục; bảng này chỉ để đọc nhanh.

  | Mốc | Model | Ngày | first_pass_valid_rate | parse_error_rate | unknown_place_rate | avg_stops_per_day | distinct_place_count | latency_p50_s |
  |---|---|---|---|---|---|---|---|---|
  | baseline | (tag model) | (ngày chạy) | (số) | (số) | (số) | (số) | (số) | (số) |

  ## Ghi chú baseline

  - **Lỗi nhiều nhất:** (3 `IssueCode` đứng đầu trong `issue_code_distribution`, kèm số lần)
  - **Nhận xét khi đọc mẫu:** (kết quả của Step 4)
  - **Cấu hình:** temperature 0.0, seed 0, thinking tắt, format (schema hoặc json)
  - **Git commit và hash dữ liệu:** xem `meta` trong `baseline_dev.json`
  ```

  Mọi ô `(…)` phải được thay bằng số đo thật trước khi commit. Không ước lượng.

- [ ] **Step 6: Commit**

  ```powershell
  git add configs/eval.yaml dvc.yaml dvc.lock reports/eval/baseline_dev.json reports/eval/README.md reports/eval/.gitignore
  git commit -m "chore: record baseline eval for Qwen 4B on dev split"
  dvc push
  ```

  Expected: `dvc push` đẩy `data/hue.sqlite` và file outcomes vào `C:\dev\travelagent-dvc`.

---

## Nghiệm thu plan

- `powershell -File scripts\check.ps1` pass toàn bộ.
- `data/eval/hue_eval_v1.jsonl` có 100 request, 70 dev và 30 test, stage `make_evalset` có `frozen: true`.
- `reports/eval/baseline_dev.json` có đủ metric trên 70 request dev, kèm git commit và hash dữ liệu.
- MLflow có run `baseline` trong experiment `hue-planner`.
- Chưa chạy eval nào trên split `test`.

## Plan kế tiếp

Plan 3 (solver và dataset SFT) viết sau khi có số baseline thật: phân bố `IssueCode` của baseline cho biết mẫu repair nên tập trung vào loại lỗi nào.
