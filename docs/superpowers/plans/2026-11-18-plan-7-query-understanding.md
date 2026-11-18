# Plan 7: Hiểu câu yêu cầu tự do (query understanding)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development hoặc superpowers:executing-plans. Mỗi step dùng checkbox (`- [ ]`).

**Goal:** Từ một câu tiếng Việt tự do ("đi Huế 2 ngày cuối tuần này với bố mẹ, thích chùa, không đi bộ nhiều"), dựng đúng `PlanRequest` cộng các ràng buộc và sở thích mà `PlanRequest` chưa có ô, hoặc hỏi lại khi thiếu thông tin quan trọng. Đo trước, chỉ train nếu số đo cho thấy cần.

**Architecture:** lai giữa luật và LLM.

```
câu -> chuẩn hóa (code: bỏ dấu để so, viết tắt "2n1đ", số)
    -> LLM (Ollama, JSON schema) trích: intent, các trường, cụm ngày nguyên văn, địa điểm nhắc tới, sở thích mềm
    -> code: giải cụm ngày theo ngày tham chiếu, ánh xạ sở thích vào 9 interest, liên kết tên địa điểm với DB, điền mặc định
    -> ParsedQuery (hợp lệ theo pydantic) | câu hỏi lại
```

LLM không tự tính ngày: nó trả cụm ngày nguyên văn ("cuối tuần này", "thứ 7 tới", "20/12"), code tính ra ngày. Đây là chỗ model nhỏ hay sai nhất.

**Nhánh:** `feat/stage0-1-foundation`. Liên quan: plan 6 (pipeline `plan_trip` nhận `PlanRequest` từ plan này).

## Global Constraints

- Không thêm thư viện mới khi chưa hỏi người dùng (so khớp mờ dùng `difflib`/chuẩn hóa Unicode có sẵn).
- Tải model mới về Ollama (ví dụ model embedding) phải hỏi người dùng trước.
- Việc gọi Ollama (đo) hỏi trước khi chạy dài; chạy qua Task Scheduler.
- `check.ps1` xanh; test không gọi mạng (generator giả).

## Quyết định đã chốt

| Chủ đề | Quyết định |
|---|---|
| Thành phố | Chỉ Huế. Câu hỏi về thành phố khác: intent `out_of_scope`, trả lời từ chối lịch sự. |
| Intent | `plan_new`, `modify_plan`, `place_info`, `out_of_scope`. Plan này làm đủ `plan_new`; ba intent kia chỉ cần nhận đúng. |
| Interests | Ánh xạ về 9 từ của `planning/candidates.py: INTEREST_CATEGORIES` (history, culture, spiritual, food, coffee, nature, photography, shopping, sightseeing). Cụm không ánh xạ được giữ ở `soft_preferences`. |
| Ràng buộc cứng | `must_include` và `exclude`: tên địa điểm hoặc loại (ví dụ "không đi chợ"). Tên được liên kết với `place_id` trong DB; không liên kết được thì giữ nguyên văn và báo. |
| Sở thích mềm | Danh sách cụm chữ nguyên văn ("yên tĩnh", "đi cùng bố mẹ già", "có trẻ nhỏ"). Plan này chỉ trích ra; dùng để xếp hạng địa điểm là plan sau (dữ liệu mô tả mới có 373/1.587 điểm, xem "Việc để sau"). |
| Ngân sách, số người | Không có ô riêng (DB chỉ có giá cho 503 điểm, solver chưa dùng). Giữ ở `soft_preferences`. |
| Thiếu thông tin | Thiếu số ngày hoặc thiếu hẳn thời điểm đi: hỏi lại (`clarification`). Thiếu pace, phương tiện, giờ: điền mặc định của `PlanRequest`, ghi vào `defaulted`. |
| Ngày tham chiếu | Truyền vào (mặc định hôm nay). Eval cố định ngày tham chiếu để kết quả tái lập. |

**`ParsedQuery`** (pydantic): `intent`, `request: PlanRequest | None`, `date_text: str | None`, `must_include: list[PlaceMention]`, `exclude: list[PlaceMention]`, `exclude_categories: list[Category]`, `soft_preferences: list[str]`, `defaulted: list[str]`, `clarification: str | None`. `PlaceMention`: `text`, `place_id | None`, `score`.

---

### Task 1: Schema và phần chuẩn hóa bằng code

**Files:** Create `src/travel_agent/understanding/{__init__,models,normalize,dates}.py`; Test `tests/understanding/`.

- [ ] **Step 1: Test viết trước:**
  - `resolve_date_text("cuối tuần này", ref)`, "tuần sau", "thứ 7 tới", "mai", "ngày kia", "20/12", "20-12-2026", "đầu tháng 12", "tết dương lịch", và cụm không hiểu được trả `None`;
  - `parse_duration("2 ngày 1 đêm")`, "2n1đ", "3 hôm", "một ngày", "nửa ngày" (1 ngày, day_end sớm hơn);
  - `strip_diacritics`, so tên "dai noi" khớp "Đại Nội";
  - `map_interests` từ cụm tiếng Việt ("chùa", "lăng tẩm", "ăn uống", "cà phê", "chụp ảnh"...) về 9 từ, cụm không khớp trả về để đưa vào sở thích mềm.
- [ ] **Step 2–4:** Code, test, `check.ps1`, commit.

### Task 2: Bộ eval 150 câu và harness đo

**Files:** Create `data/eval/query_eval_v1.jsonl` (DVC theo dõi), `src/travel_agent/understanding/evaluate.py`, lệnh `qu-eval`; Test.

- [ ] **Step 1:** Viết 150 câu kèm `ParsedQuery` đúng, ngày tham chiếu cố định 2026-11-18. Phân bố: đủ thông tin 30; thiếu thông tin 25; ngày tương đối 25; không dấu, viết tắt, teencode 20; sở thích mềm 20; must/exclude địa điểm 15; intent khác và ngoài phạm vi 15. Chia 100 dev / 50 test theo hash.
- [ ] **Step 2:** Người dùng duyệt 20 câu ngẫu nhiên; sửa theo góp ý.
- [ ] **Step 3:** Số đo: intent accuracy; từng trường (start_date, num_days, pace, travel_mode, day_start, day_end) accuracy; interests F1; must/exclude precision và recall (kèm đúng `place_id`); clarification precision và recall; tỉ lệ khớp hoàn toàn cả `ParsedQuery`; latency p50.
- [ ] **Step 4:** Test cho harness với dự đoán giả; commit.

### Task 3: Bộ trích bằng LLM

**Files:** Create `src/travel_agent/understanding/extract.py` (prompt, JSON schema, few-shot), `understanding/link.py` (liên kết tên địa điểm với DB bằng tên bỏ dấu + `difflib`), lệnh `parse "câu"`; Test với generator giả.

- [ ] **Step 1:** Test viết trước: output LLM giả đi qua đúng chuỗi chuẩn hóa → `ParsedQuery`; LLM trả JSON hỏng thì thử lại 1 lần rồi báo lỗi; intent `out_of_scope` không dựng `request`; ngày do code tính, không lấy ngày LLM tự tính.
- [ ] **Step 2–3:** Code, `check.ps1`, commit.

### Task 4: Đo các model có sẵn (Ollama, hỏi trước)

- [ ] **Step 1:** Chạy `qu-eval` trên dev với `qwen3.5:4b`, `qwen3.5:9b`, `gemma3:4b` (prompt giống nhau). Ghi bảng vào `reports/understanding/README.md`.
- [ ] **Step 2:** Đọc 20 câu sai của model tốt nhất, phân loại lỗi (ngày, interests, địa điểm, intent, hỏi lại thừa hoặc thiếu).
- [ ] **Step 3:** Quyết định cùng người dùng:
  - đạt khoảng 90% khớp hoàn toàn: dùng prompt, không train;
  - thấp hơn: sửa prompt/few-shot và luật trước; vẫn thấp thì viết plan train adapter nhỏ (dữ liệu sinh bằng cách diễn đạt lại).

### Task 5: Nối với lập lịch

**Files:** Modify `planning/candidates.py` (nhận `must_include`/`exclude`), `planning/pipeline.py` (plan 6), lệnh `ask "câu"`; Test.

- [ ] **Step 1:** Candidate luôn chứa điểm `must_include` (nếu mở cửa trong khung), không chứa điểm/loại `exclude`.
- [ ] **Step 2:** `ask`: câu → `ParsedQuery` → hỏi lại nếu cần → `plan_trip` → lịch + cảnh báo + các mục đã điền mặc định.
- [ ] **Step 3:** Thử 10 câu thật, ghi kết quả.

## Việc để sau (plan khác)

- **Sở thích mềm bằng embedding:** cần tải model embedding (ví dụ `bge-m3`) và cần mô tả địa điểm; hiện chỉ 373/1.587 điểm có "Tóm tắt". Làm sau khi bổ sung mô tả.
- **Thời lượng tham quan thật:** 1.000 điểm có "Thời gian trải nghiệm TB (phút)" trong `attributes`; nên dùng thay `VISIT_MINUTES` ở `retime` và solver.
- **Hội thoại nhiều lượt và `modify_plan`.**

**Điều kiện xong:** bảng số đo QU của 3 model trên dev; quyết định train hay không đã chốt cùng người dùng; lệnh `ask` chạy từ câu tự do tới lịch trình.
