# Plan 6: Lập lịch dùng được (model đề xuất, code xếp giờ, model sửa lỗi)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development hoặc superpowers:executing-plans. Mỗi step dùng checkbox (`- [ ]`).

**Goal:** Từ một `PlanRequest`, trả lịch trình hợp lệ trong hơn 90% request dev, trong khoảng 20 giây, với model `travel-rl-v1`. Không train thêm.

**Architecture:**

```
request -> select_candidates -> model chọn điểm + thứ tự (prompt hiện có)
        -> retime(): code xếp lại giờ theo thời gian di chuyển, thời lượng, giờ mở cửa
        -> validate_itinerary -> còn ERROR? -> model sửa (build_messages(..., broken, issues)) -> retime -> validate
        -> trả Itinerary + cảnh báo (tối đa N lần sửa)
```

Logic thuần trong `src/travel_agent/planning/` (test không cần Ollama). Lệnh `plan` và endpoint FastAPI là lớp mỏng.

**Spec gốc:** [2026-11-11-sft-rl-training-design.md](../specs/2026-11-11-sft-rl-training-design.md). Kết quả trước plan này: `reports/eval/README.md` (RL dev 27/70, test 16/30; lỗi còn lại gần như chỉ `travel_time_insufficient`).

**Nhánh:** `feat/stage0-1-foundation`.

## Global Constraints

- Không đổi prompt, không đổi validator, không train. Model dùng như đã export.
- Eval mới phải so được với số cũ: cùng bộ dev, cùng candidate, cùng tham số sinh. Chỉ chạy bộ test lại khi người dùng đồng ý (bộ test chỉ dùng cho so sánh cuối).
- Việc dùng GPU/Ollama (eval) hỏi người dùng trước. Chạy qua Task Scheduler.
- `check.ps1` xanh, `set -o pipefail` khi pipe output test.

## Quyết định đã chốt

| Chủ đề | Quyết định |
|---|---|
| Xếp giờ | Giữ ngày và thứ tự điểm model chọn. Ngày bắt đầu ở `day_start`. Mỗi điểm: đến = max(rời điểm trước + thời gian di chuyển làm tròn lên phút, giờ mở cửa sớm nhất còn vừa); ở lại = thời lượng model ghi nếu > 0, không thì `VISIT_MINUTES[category]`; nếu không vừa giờ đóng cửa hoặc `day_end` thì bỏ điểm đó và ghi lý do. |
| Thời gian di chuyển | Cùng `TravelTimeProvider` với validator (`HaversineEstimator` hiện tại), để code xếp giờ và validator không lệch nhau. |
| Giờ mở cửa | Dùng chung một hàm với solver (tách `_open_ranges` ra helper công khai trong `planning/`), không viết lại. |
| Sửa lỗi | Tối đa 2 lần. Prompt sửa đúng là `build_messages(request, candidates, broken=itinerary, issues=report.issues)` như mẫu repair lúc SFT. Kết quả sửa cũng qua retime. Lần nào hết ERROR thì dừng. |
| Trả kết quả | Lịch cuối cùng (kể cả còn lỗi) kèm `ValidationReport`, số lần sửa, các điểm bị bỏ. Không trả lịch có ERROR như là hợp lệ. |

## Đo

Trên dev 70 request, model `travel-rl-v1` (và `travel-sft-v1` để so), bốn chế độ:

| Chế độ | Ý nghĩa |
|---|---|
| `raw` | Như hiện tại (đã có: RL 27/70). |
| `retime` | Chỉ xếp lại giờ, không gọi lại model. |
| `repair` | Chỉ sửa lỗi bằng model, tối đa 2 lần. |
| `retime+repair` | Đầy đủ. |

Ghi `first_pass_valid_rate` (sau toàn bộ pipeline), số lần gọi model trung bình, latency p50/p90, số điểm bị bỏ, `avg_stops_per_day`, `distinct_place_count`. Mục tiêu: `retime+repair` hơn 90% hợp lệ, `avg_stops_per_day` không giảm quá 10% so với `raw`.

---

### Task 1: Xếp giờ bằng code

**Files:** Create `src/travel_agent/planning/schedule.py`; Modify `src/travel_agent/planning/solver.py` (dùng helper giờ mở cửa chung); Test `tests/planning/test_schedule.py`.

**Interface:** `retime(request, itinerary, places, travel) -> RetimeResult(itinerary, dropped: list[DroppedStop])`.

- [ ] **Step 1: Test viết trước:**
  - lịch có giờ quá sát: sau retime không còn `travel_time_insufficient`;
  - điểm mở muộn: chờ tới giờ mở;
  - điểm đóng cửa cả ngày, hoặc không vừa trước `day_end`: bị bỏ và ghi lý do;
  - giữ nguyên ngày, thứ tự, `place_id`;
  - `place_id` lạ giữ nguyên để validator báo `unknown_place`;
  - lịch đã hợp lệ: retime không làm nó mất hợp lệ;
  - với mọi plan solver sinh ra (dùng fixture có sẵn), retime xong vẫn hợp lệ.
- [ ] **Step 2–4:** Code, test, `check.ps1`, commit.

### Task 2: Pipeline lập lịch và lệnh `plan`

**Files:** Create `src/travel_agent/planning/pipeline.py`; Modify `training/commands.py` + `cli.py` (lệnh `plan`); Test `tests/planning/test_pipeline.py`.

**Interface:** `plan_trip(request, places, generator, travel, *, retime=True, max_repairs=2) -> PlanResult(itinerary | None, report, attempts, dropped, raw_outputs)`.

- [ ] **Step 1: Test viết trước** với generator giả: output tốt thì 1 lần gọi; output lỗi thì gọi sửa đúng prompt repair; dừng khi hết ERROR hoặc hết lượt; output không parse được thì lần sửa dùng prompt sinh lại từ đầu; candidate giống eval (`candidate_seed`).
- [ ] **Step 2:** Lệnh `plan --model travel-rl-v1 --request request.json` (hoặc các cờ `--days --pace --interests --travel-mode --start-date`), in JSON lịch + cảnh báo.
- [ ] **Step 3:** `check.ps1`, commit.

### Task 3: Eval theo chế độ (cần Ollama, hỏi trước)

**Files:** Modify `training/runner.py`, `training/metrics.py`, `training/commands.py` (cờ `--retime`, `--max-repairs` cho `eval`; meta ghi chế độ để `incomparable()` không so nhầm chế độ khác nhau); Test cập nhật.

- [ ] **Step 1:** Code + test (generator giả).
- [ ] **Step 2 (Ollama):** chạy 4 chế độ × `travel-rl-v1` trên dev, thêm `retime+repair` cho `travel-sft-v1`. Ghi bảng vào `reports/eval/README.md`.
- [ ] **Step 3:** Đọc 10 lịch của `retime+repair`: điểm bị bỏ có hợp lý không, lịch có quá thưa không.

### Task 4: Endpoint API

**Files:** Create `src/travel_agent/api/app.py` (FastAPI `POST /plan`), lệnh `serve`; Test với `TestClient` và generator giả.

- [ ] **Step 1–3:** Code, test, README (cách chạy: Ollama + `travel-rl-v1` + `serve`), commit.

**Điều kiện xong:** bảng 4 chế độ trên dev; `retime+repair` hơn 90% hợp lệ hoặc ghi rõ vì sao chưa; lệnh `plan` và `POST /plan` chạy được với `travel-rl-v1`.
