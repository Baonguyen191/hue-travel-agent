# Plan 3: sửa nền và chốt baseline mới (chặng 1)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development hoặc superpowers:executing-plans. Mỗi step dùng checkbox (`- [ ]`).

**Goal:** Xử lý 10 mục trong [open-items](2026-11-12-open-items-before-sft.md), rồi chạy lại baseline `qwen3.5:4b` trên dev. Baseline mới là mốc để so với SFT.

**Architecture:** Mọi thay đổi nằm trong module logic thuần đã có: `planning/candidates.py`, `planning/prompt.py`, `training/generator.py`, `training/runner.py`, `training/metrics.py`, `training/commands.py`, `training/requests.py`, `validation/validator.py`. Không thêm module mới. Pipeline DVC giữ nguyên hình dạng.

**Tech Stack:** Python 3.11, Pydantic v2, pytest, Ollama `/api/chat`, DVC, MLflow.

**Spec:** [2026-11-11-sft-rl-training-design.md](../specs/2026-11-11-sft-rl-training-design.md). Bàn giao: [2026-11-14-handoff-remaining-work.md](2026-11-14-handoff-remaining-work.md).

**Nhánh:** `feat/stage0-1-foundation`, tách từ `main` tại `69f7437`.

## Global Constraints

- Mỗi lệnh Python: `$env:PYTHONPATH="src"`, chạy bằng `.venv\Scripts\python`.
- `powershell -File scripts\check.ps1` xanh trước mỗi commit.
- Message commit tiếng Anh, kiểu `feat:`/`fix:`/`test:`/`docs:`/`chore:`, kết thúc bằng `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Giữ nguyên `data/eval/hue_eval_v1.jsonl` và `frozen: true` của `make_evalset`.
- Đổi prompt thì cập nhật snapshot `tests/planning/snapshots/generation_messages.json` có chủ đích, và ghi lý do trong commit.
- Parser giữ nguyên output của model; output hỏng tính là hỏng.
- Giữ dòng baseline cũ trong `reports/eval/README.md`, thêm nhãn "trước khi sửa candidate và schema".

## Quyết định đã chốt

| Chủ đề | Quyết định | Nguồn |
|---|---|---|
| Lọc candidate | Bán kính quanh Đại Nội (16.4698, 107.5786) theo phương tiện: car 12 km, motorbike 12 km, walk 2 km. | Người dùng chọn ngày 2026-11-14, dựa trên số đo dưới đây. |
| Số candidate tối đa | Giữ công thức `clamp(max_stops × num_days + 4, 12, 30)`. Sửa spec mục 2 (đang ghi 20). Lý do: validator cấm lặp `place_id`, request packed 3 ngày cần ít nhất 18 điểm cộng 6 bữa ăn. | Plan này. Task 7 đo token để kiểm. |
| Exit code của `eval` | 0 qua cổng, 1 crash (traceback mặc định của Python), 2 sai cách dùng hoặc hai báo cáo không so được, 3 không qua cổng. | Plan này. Tách crash khỏi regression (open-items mục 8). |
| Nơi đặt bán kính | Hằng số module trong `candidates.py`, cùng chỗ với `MAX_STOPS_PER_DAY`. | Plan này. Candidate là logic dùng chung cho eval, dataset và runtime; đưa vào config phải truyền qua mọi lời gọi. |

Số đo dẫn tới quyết định lọc (70 request dev, `select_candidates` hiện tại, tỉ lệ cặp candidate cần hơn 60 phút di chuyển):

| Lọc | car | motorbike | walk |
|---|---|---|---|
| Không lọc | 18,3% | 19,5% | 46,6% |
| ≤ 12 km | 1,1% | 0,2% | 39,8% |
| ≤ 2 km | 0% | 0% | 0,7% |

---

### Task 1: Probe schema theo số ngày

Mục tiêu: xác định nguyên nhân model luôn trả 1 ngày (open-items mục 2) trước khi sửa code.

**Files:** chỉ script tạm trong scratchpad; không commit.

- [x] **Step 1:** Chọn 5 request dev có `num_days` 2 hoặc 3 từ `data/eval/hue_eval_v1.jsonl`.
- [x] **Step 2:** Với mỗi request, gọi Ollama `qwen3.5:4b` hai lần qua `OllamaGenerator` với cùng `build_messages(request, select_candidates(request, places, candidate_seed(key)))`:
  - lần A: `ITINERARY_FORMAT_SCHEMA` hiện tại;
  - lần B: bản sao của schema, với `days.minItems = days.maxItems = num_days`.
- [x] **Step 3:** Ghi số ngày trả về của từng lần vào bảng.

**Điều kiện xong:**
- Lần B trả đúng số ngày ở cả 5 request: nguyên nhân là schema. Làm tiếp Task 2.
- Lần B vẫn sai: dừng, đọc output, báo người dùng trước khi làm Task 2.

### Task 2: Schema theo request

**Files:**
- Modify: `src/travel_agent/training/generator.py`
- Modify: `src/travel_agent/training/runner.py`
- Test: `tests/training/test_generator.py`, `tests/training/test_runner.py`

**Interfaces:**
- Produces: `itinerary_format_schema(num_days: int | None) -> dict[str, Any]`; `PlanGenerator.generate(messages, format_schema: dict[str, Any] | None = None) -> Generation`.
- `ITINERARY_FORMAT_SCHEMA = itinerary_format_schema(None)`. Giữ tên này để test đối chiếu schema với `Itinerary` vẫn chạy.

- [x] **Step 1: Test viết trước** (thêm vào `tests/training/test_generator.py`):

```python
from travel_agent.training.generator import ITINERARY_FORMAT_SCHEMA, itinerary_format_schema


def test_schema_pins_day_count() -> None:
    days = itinerary_format_schema(3)["properties"]["days"]
    assert (days["minItems"], days["maxItems"]) == (3, 3)


def test_schema_without_day_count_matches_default() -> None:
    assert itinerary_format_schema(None) == ITINERARY_FORMAT_SCHEMA
    assert "maxItems" not in ITINERARY_FORMAT_SCHEMA["properties"]["days"]


def test_generate_sends_per_call_schema() -> None:
    sent: list[dict] = []

    def transport(url: str, payload: dict, timeout_s: float) -> dict:
        sent.append(payload)
        return {"message": {"content": "{}"}}

    generator = OllamaGenerator("m", transport=transport)
    generator.generate([{"role": "user", "content": "x"}], format_schema=itinerary_format_schema(2))
    assert sent[0]["format"]["properties"]["days"]["maxItems"] == 2


def test_no_schema_mode_ignores_per_call_schema() -> None:
    sent: list[dict] = []

    def transport(url: str, payload: dict, timeout_s: float) -> dict:
        sent.append(payload)
        return {"message": {"content": "{}"}}

    generator = OllamaGenerator("m", schema_format=False, transport=transport)
    generator.generate([{"role": "user", "content": "x"}], format_schema=itinerary_format_schema(2))
    assert sent[0]["format"] == "json"
```

Thêm vào `tests/training/test_runner.py` một test: generator giả ghi lại `format_schema` nhận được; với entry `num_days=2`, `format_schema["properties"]["days"]["maxItems"] == 2`.

- [x] **Step 2:** `python -m pytest tests/training/test_generator.py tests/training/test_runner.py -v`. Mong đợi: FAIL vì `itinerary_format_schema` chưa có.

- [x] **Step 3: Code.** Trong `generator.py`, đổi hằng số thành hàm:

```python
def itinerary_format_schema(num_days: int | None) -> dict[str, Any]:
    """Schema viết tay cùng hình dạng `Itinerary`; `num_days` ép đúng số phần tử của `days`."""
    days: dict[str, Any] = {
        "type": "array",
        "minItems": 1,
        "items": {...},  # giữ nguyên phần items hiện tại
    }
    if num_days is not None:
        days["minItems"] = num_days
        days["maxItems"] = num_days
    return {"type": "object", "properties": {"days": days}, "required": ["days"]}


ITINERARY_FORMAT_SCHEMA: dict[str, Any] = itinerary_format_schema(None)
```

`PlanGenerator.generate` và `OllamaGenerator.generate` nhận thêm `format_schema: dict[str, Any] | None = None`. Trong `OllamaGenerator`: nếu `schema_format` là False thì gửi `"json"`; ngược lại gửi `format_schema or ITINERARY_FORMAT_SCHEMA`.

Trong `runner.py`: `generator.generate(messages, format_schema=itinerary_format_schema(entry.request.num_days))`. Cập nhật mọi generator giả trong test cho khớp chữ ký mới.

- [x] **Step 4:** Chạy lại test ở Step 2. Mong đợi: PASS. Chạy `check.ps1`.
- [x] **Step 5:** Commit `feat: pin itinerary day count in the per-request output schema`.

### Task 3: Lọc candidate theo bán kính

**Files:**
- Modify: `src/travel_agent/planning/candidates.py`
- Test: `tests/planning/test_candidates.py`, `tests/planning/factories.py`

**Interfaces:**
- Produces: `CITY_CENTER: Coordinates`, `MAX_RADIUS_KM: dict[TravelMode, float]`, `within_radius(place, mode) -> bool`. `select_candidates` giữ nguyên chữ ký.

- [x] **Step 1: Test viết trước.** Trong `factories.py`, `make_request` nhận thêm `travel_mode: TravelMode = TravelMode.MOTORBIKE`. Thêm vào `test_candidates.py`:

```python
from travel_agent.domain.models import TravelMode
from travel_agent.planning.candidates import MAX_RADIUS_KM, within_radius

# Độ vĩ: 1 độ khoảng 111 km. Tâm Đại Nội 16.4698, 107.5786.
NEAR = make_place("t:near", Category.MUSEUM, lat=16.4698 + 1.5 / 111, lon=107.5786)  # ~1,5 km
MID = make_place("t:mid", Category.MUSEUM, lat=16.4698 + 8 / 111, lon=107.5786)  # ~8 km
FAR = make_place("t:far", Category.MUSEUM, lat=16.4698 + 30 / 111, lon=107.5786)  # ~30 km


def test_radius_depends_on_travel_mode() -> None:
    assert MAX_RADIUS_KM[TravelMode.WALK] < MAX_RADIUS_KM[TravelMode.MOTORBIKE]
    assert within_radius(NEAR, TravelMode.WALK)
    assert not within_radius(MID, TravelMode.WALK)
    assert within_radius(MID, TravelMode.CAR)
    assert not within_radius(FAR, TravelMode.CAR)


def test_select_candidates_drops_places_outside_radius() -> None:
    pool = [*make_pool(), MID, FAR]
    walk = {p.id for p in select_candidates(make_request(travel_mode=TravelMode.WALK), pool, seed=1)}
    car = {
        p.id
        for seed in range(30)
        for p in select_candidates(make_request(travel_mode=TravelMode.CAR), pool, seed=seed)
    }
    assert not {"t:mid", "t:far"} & walk
    assert "t:far" not in car
    assert "t:mid" in car
```

- [x] **Step 2:** `python -m pytest tests/planning/test_candidates.py -v`. Mong đợi: FAIL vì `within_radius` chưa có.

- [x] **Step 3: Code** trong `candidates.py`:

```python
from travel_agent.domain.models import Category, Coordinates, Pace, Place, PlanRequest, TravelMode
from travel_agent.routing.travel_time import haversine_m

# Đại Nội. Bán kính chọn ngày 2026-11-14 từ số đo trên dev: với bán kính này, gần như không còn
# cặp candidate cần hơn 60 phút di chuyển. 12 km giữ được khu lăng (Minh Mạng khoảng 11 km).
CITY_CENTER = Coordinates(lat=16.4698, lon=107.5786)
MAX_RADIUS_KM: dict[TravelMode, float] = {
    TravelMode.WALK: 2.0,
    TravelMode.MOTORBIKE: 12.0,
    TravelMode.CAR: 12.0,
}


def within_radius(place: Place, mode: TravelMode) -> bool:
    return haversine_m(CITY_CENTER, place.coords) <= MAX_RADIUS_KM[mode] * 1000
```

Dòng đầu của `select_candidates`: `places = [p for p in places if within_radius(p, request.travel_mode)]`. Cập nhật docstring của module.

- [x] **Step 4:** Chạy lại test. Mong đợi: PASS. Các test cũ vẫn pass vì `make_place` mặc định cách tâm khoảng 0,2 km. Chạy `check.ps1`.
- [x] **Step 5:** Commit `feat: limit candidates to a travel-mode radius around the citadel`.

### Task 4: Validator không phạt đôi, escape `|` trong tên

**Files:**
- Modify: `src/travel_agent/validation/validator.py:51-62`
- Modify: `src/travel_agent/planning/prompt.py` (`format_candidate`)
- Test: `tests/validation/test_validator_structure.py`, `tests/planning/test_prompt.py`

- [x] **Step 1: Test viết trước.**

```python
# tests/validation/test_validator_structure.py
def test_repeated_unknown_place_is_reported_only_as_unknown() -> None:
    # Dựng itinerary có cùng id lạ "x:404" ở hai stop, bằng factory sẵn có của file này.
    report = ...
    codes = [issue.code for issue in report.issues]
    assert codes.count(IssueCode.UNKNOWN_PLACE) == 2
    assert IssueCode.DUPLICATE_PLACE not in codes
```

Đọc các factory trong `tests/validation/factories.py` để dựng itinerary; giữ test duplicate của id hợp lệ hiện có.

```python
# tests/planning/test_prompt.py
def test_pipe_in_place_name_does_not_break_candidate_row() -> None:
    row = format_candidate(make_place("t:a", Category.CAFE, name="Cà phê | Muối"))
    assert row.count("|") == 4
    assert "Cà phê / Muối" in row
```

- [x] **Step 2:** Chạy hai file test. Mong đợi: FAIL.
- [x] **Step 3: Code.**
  - `validator.py`: chỉ kiểm `DUPLICATE_PLACE` khi `place is not None`. Thêm comment một dòng: id lạ đã bị báo `UNKNOWN_PLACE` ở mỗi lần xuất hiện, nên không báo trùng thêm (tránh phạt đôi trong reward, spec mục 8.1).
  - `prompt.py`: `name = " ".join(place.name.split()).replace("|", "/")`.
- [x] **Step 4:** Chạy lại test. Snapshot prompt phải giữ nguyên (không tên nào trong snapshot có `|`). Chạy `check.ps1`.
- [x] **Step 5:** Commit `fix: report a repeated unknown place once per stop and escape pipes in candidate names`.

### Task 5: Cổng thăng hạng

**Files:**
- Modify: `src/travel_agent/training/metrics.py` (`regressions`)
- Modify: `src/travel_agent/training/commands.py`
- Test: `tests/training/test_metrics.py`, `tests/training/test_commands.py`

**Interfaces:**
- Produces: `COMPARABLE_META_KEYS = ("split", "evalset_sha256", "db_sha256", "limit", "schema_format")`; `incomparable(current_meta, previous_meta) -> list[str]`; `EXIT_REGRESSION = 3`.

- [x] **Step 1: Test viết trước.**

```python
# tests/training/test_metrics.py
BASE_META = {
    "split": "dev",
    "evalset_sha256": "a",
    "db_sha256": "b",
    "limit": "all",
    "schema_format": True,
}


def test_regression_when_parse_error_rate_rises() -> None:
    worse = _summary(0.5).model_copy(update={"parse_error_rate": 0.2})
    problems = regressions(worse, _summary(0.5))
    assert len(problems) == 1
    assert "parse_error_rate" in problems[0]


def test_incomparable_lists_each_differing_key() -> None:
    assert incomparable(BASE_META, dict(BASE_META)) == []
    changed = {**BASE_META, "db_sha256": "c", "limit": 5}
    assert incomparable(changed, BASE_META) == ["db_sha256", "limit"]


def test_incomparable_treats_missing_key_as_different() -> None:
    old = {k: v for k, v in BASE_META.items() if k != "schema_format"}
    assert incomparable(BASE_META, old) == ["schema_format"]
```

Trong `tests/training/test_commands.py`:
- Đổi kỳ vọng của test regression ở dòng 131 từ `== 1` thành `== 3`.
- Thêm test: file mốc có `meta.db_sha256` khác DB đang dùng thì lệnh trả `2` và stderr có tên trường `db_sha256`.

- [x] **Step 2:** Chạy hai file test. Mong đợi: FAIL.
- [x] **Step 3: Code.**
  - `metrics.py`: trong `regressions`, thêm điều kiện `current.parse_error_rate > previous.parse_error_rate`, cùng định dạng thông báo với điều kiện đang có. Thêm `COMPARABLE_META_KEYS` và:

```python
def incomparable(current: Mapping[str, object], previous: Mapping[str, object]) -> list[str]:
    """Tên các trường điều kiện chạy khác nhau. Khác thì hai báo cáo không so được."""
    return [key for key in COMPARABLE_META_KEYS if current.get(key) != previous.get(key)]
```

  - `commands.py`:
    - `EXIT_REGRESSION = 3`, thêm comment: exit 1 dành cho crash.
    - `_load_baseline` trả `tuple[dict[str, object], EvalSummary] | None`, đọc cả `data["meta"]`.
    - Sau khi tính `meta`, nếu `incomparable(meta, baseline_meta)` khác rỗng: in `Không so được với mốc: khác <danh sách>` ra stderr và trả `EXIT_USAGE`. Bước này chạy trước bước so metric. Báo cáo của lần chạy vẫn được ghi ra đĩa.
- [x] **Step 4:** Chạy lại test. Chạy `check.ps1`.
- [x] **Step 5:** Commit `feat: gate on parse errors, refuse incomparable baselines, split regression exit code`.

### Task 6: Ghi cây dirty, chặn vòng lặp vô hạn

**Files:**
- Modify: `src/travel_agent/training/commands.py` (`current_commit`)
- Modify: `src/travel_agent/training/requests.py` (`generate_requests`)
- Test: `tests/training/test_commands.py`, `tests/training/test_requests.py`

- [x] **Step 1: Test viết trước.**

```python
# tests/training/test_requests.py
def test_generate_requests_refuses_impossible_count() -> None:
    with pytest.raises(ValueError, match="không đủ request khác nhau"):
        generate_requests(10**9, seed=1, max_attempts=1000)
```

```python
# tests/training/test_commands.py
def _fake_git(monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    outputs = {
        ("git", "rev-parse", "HEAD"): "abc123\n",
        ("git", "status", "--porcelain"): status,
    }

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=outputs[tuple(cmd)], stderr="")

    monkeypatch.setattr(commands.subprocess, "run", fake_run)


def test_current_commit_marks_dirty_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_git(monkeypatch, " M x.py\n")
    assert commands.current_commit() == "abc123-dirty"


def test_current_commit_clean_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_git(monkeypatch, "")
    assert commands.current_commit() == "abc123"
```

- [x] **Step 2:** Chạy test. Mong đợi: FAIL.
- [x] **Step 3: Code.**
  - `current_commit`: sau `rev-parse`, chạy `git status --porcelain`. Có output thì thêm hậu tố `-dirty`. Lỗi khi gọi git vẫn trả `"unknown"`.
  - `generate_requests(count, seed, max_attempts=None)`: mặc định `max_attempts = count * 100`. Hết số lần thử mà chưa đủ thì `raise ValueError(f"không đủ request khác nhau: cần {count}, có {len(by_key)} sau {max_attempts} lần thử")`. Với seed của bộ eval, kết quả phải giữ nguyên: test `test_evalset_file.py` kiểm điều này.
- [x] **Step 4:** Chạy lại test. Chạy `check.ps1`.
- [x] **Step 5:** Commit `fix: mark dirty trees in run metadata and bound request generation`.

### Task 7: Đo token, chạy lại baseline, cập nhật tài liệu

**Files:**
- Modify: `reports/eval/README.md`, `reports/eval/baseline_dev.json` (do DVC sinh), `dvc.lock`
- Modify: `docs/superpowers/plans/2026-11-12-open-items-before-sft.md`
- Modify: `docs/superpowers/specs/2026-11-11-sft-rl-training-design.md` (mục 2, số candidate)

- [x] **Step 1: Chạy baseline.** `dvc repro baseline_eval`. Stage chạy lại vì code trong `deps` đã đổi.
- [x] **Step 2: Đo token.**
  - Prompt dài nhất: lấy `max(prompt_tokens)` trong `reports/eval/baseline_dev.outcomes.jsonl`. Đây là số token thật do tokenizer Qwen của Ollama đếm.
  - Output dài nhất có thể có: dựng một itinerary 3 ngày, 8 stop mỗi ngày, dùng `place_id` thật dài nhất trong DB, `note` là null. Gửi chuỗi JSON đó làm nội dung user message tới `qwen3.5:4b` với `num_predict: 1`. Lấy `prompt_eval_count`, trừ đi số token của message rỗng gửi cùng cách.
  - Ghi hai số và tổng vào open-items mục 3. Tổng vượt 2048 thì ghi: "chặng 3 phải chọn giữa `max_seq` lớn hơn và giảm `MAX_CANDIDATES`; smoke test đo VRAM cho cả hai."
  - Đã làm khác đi: `prompt_tokens` lớn nhất là 1.936. Độ dài output không đo qua Ollama mà đo cả mẫu bằng tokenizer và chat template thật của Qwen3.5-4B trên dataset thử 4.000 mẫu (`984b7ab`): dài nhất 3.885 token. Đã chọn `max_seq` 4096 (`c33a20e`), smoke test còn phải xác nhận VRAM.
- [x] **Step 3: Cập nhật `reports/eval/README.md`.**
  - Thêm nhãn "trước khi sửa candidate và schema" vào dòng baseline cũ.
  - Thêm dòng baseline mới.
  - Thêm ghi chú: phân bố lỗi mới; số request nhiều ngày đạt; `prompt_tokens` lớn nhất.
- [x] **Step 4: Cập nhật open-items.** Ghi trạng thái cho mỗi mục 1–10: "đã sửa ở `<commit>`", hoặc "bỏ qua: lý do". Các mục nhỏ để nguyên.
- [x] **Step 5: Cập nhật spec mục 2,** dòng "Số candidate trong prompt": thay "Tối đa 20" bằng công thức đang dùng, kèm lý do.
- [x] **Step 6:** `check.ps1`, `dvc push`, commit `chore: record baseline after candidate radius and per-request schema`.
  - Đã làm với commit `ce89b59` (output của lần chạy) và một commit `docs:` riêng cho tài liệu.

**Điều kiện xong của plan:**
- 10 mục đều có trạng thái.
- Baseline mới đã ghi.
- Trong baseline mới không còn `day_count_mismatch`. Nếu còn, mở outcomes để tìm nguyên nhân trước khi đóng plan.
- `check.ps1` xanh, `dvc status` sạch.
