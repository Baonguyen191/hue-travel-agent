# Lộ trình: LLM tự lập lịch trình Huế (finetune Qwen3.5-9B, chạy offline)

- **Ngày:** 2026-11-03
- **Spec gốc:** [TRAVEL_AI_AGENT_CLAUDE_BRIEF.md](../../../TRAVEL_AI_AGENT_CLAUDE_BRIEF.md)
- **Vai trò file này:** ghi các quyết định bổ sung cho brief, chia công việc thành 5 plan con. Plan nào có file chi tiết thì link ở mục tương ứng.

---

## 1. Quyết định đã chốt

1. **LLM tự sinh lịch trình và gợi ý.** Tool không dùng để lập lịch mà làm *verifier*.
2. **Validator là cổng bắt buộc.** Plan còn issue mức `ERROR` thì không bao giờ được trả cho user. Luồng xử lý:

   ```text
   PlanRequest + danh sách candidate POI (từ DB local)
     -> LLM sinh Itinerary JSON (chỉ dùng place_id có trong danh sách)
     -> validate_itinerary()
          hết ERROR -> trả cho user, kèm WARNING và nhãn "ước tính"
          còn ERROR -> gửi danh sách issue lại cho LLM sửa (tối đa 3 vòng)
          vẫn lỗi   -> OR-Tools sửa thứ tự/giờ trên tập điểm LLM đã chọn,
                       hoặc báo ràng buộc xung đột (không trả lịch trình giả)
   ```

3. **Chống bịa địa điểm.** LLM chỉ được dùng `place_id` trong danh sách candidate. Id lạ thì validator báo `UNKNOWN_PLACE`.
4. **Base model: `Qwen/Qwen3.5-9B`.**
   - License Apache-2.0, đã post-train.
   - Kiến trúc hybrid (Gated DeltaNet + Gated Attention), multimodal, context 262K.
   - Tắt thinking (`enable_thinking: False`) cả khi train lẫn khi chạy, vì output là JSON lịch trình chứ không cần chuỗi suy luận.
   - Không dùng Gemma.
5. **Finetune bằng LoRA bf16, không dùng QLoRA.** Tài liệu Unsloth khuyên không train QLoRA 4-bit cho mọi model Qwen3.5, và ghi LoRA bf16 cho 9B cần khoảng 22GB VRAM. Unsloth cũng ghi Qwen3.5 cần transformers v5.
6. **Teacher model sinh data: `Qwen/Qwen3.8-27B`** (Apache-2.0), tự host bằng vLLM trên GPU thuê.
   - Lý do: điều khoản API thương mại (Anthropic, OpenAI...) hạn chế việc dùng output để train model khác. Model Apache-2.0 không có ràng buộc này.
   - Đọc lại license và điều khoản hiện hành trước khi chạy.
7. **Thành phố đầu tiên: Huế.** POI lấy từ OpenStreetMap qua Overpass API.
   - Giấy phép ODbL-1.0, phải ghi "© OpenStreetMap contributors".
   - Tải một lần, lưu file raw, không query lặp lại.
8. **Runtime offline:**
   - Model GGUF Q4 chạy qua Ollama trên RTX 4060 Laptop 8GB.
   - DB là SQLite (một file local, không cần server).
   - PostgreSQL/PostGIS để sau, khi cần nhiều user.
9. **Travel time giai đoạn đầu:** ước tính từ khoảng cách haversine, luôn gắn nhãn `estimated`. OSRM local (dữ liệu Geofabrik Vietnam) thuộc một plan sau.

## 2. Ngoài phạm vi giai đoạn này

- **Ngân sách, giá vé:** OSM không có dữ liệu giá đáng tin, nên chưa validate budget. Nguồn giá là câu hỏi còn mở.
- **Thời tiết, rating, dữ liệu realtime.**
- **Ngày lễ (`PH`, `SH`) trong `opening_hours`:** parser trả `unknown`, không đoán.
- **Chat API, LangGraph (brief Phase 2):** tích hợp ở Plan 5.

## 3. Các plan con

Plan 2–5 chỉ viết chi tiết sau khi plan trước xong. Lý do: chúng phụ thuộc interface thật và độ phủ dữ liệu thật của plan trước.

### Plan 1: Dữ liệu Huế và Validator

**File chi tiết:** [2026-11-03-plan-1-hue-foundation.md](2026-11-03-plan-1-hue-foundation.md)

**Output:**
- File SQLite chứa POI Huế, có provenance.
- Parser `opening_hours`.
- `HaversineEstimator`.
- `validate_itinerary()`.
- CLI `travel-agent` với các lệnh `fetch-osm`, `ingest-osm`, `places`, `validate`.

**Nghiệm thu:**
- Toàn bộ test pass.
- Validate được một lịch trình viết tay dùng id POI Huế thật.
- Có số liệu độ phủ (số POI theo loại, % có `opening_hours`).

### Plan 2: Baseline sinh, kiểm, sửa (chưa finetune) và bộ eval

**Phần cần làm:**
- **Prompt sinh lịch trình**, gồm:
  - `PlanRequest`.
  - Tối đa 40 candidate đã lọc theo sở thích và độ đa dạng loại. Mỗi candidate có id, tên, loại, tọa độ làm tròn, `opening_hours_raw` (hoặc `unknown`).
  - JSON schema của `Itinerary`.
- **Gọi Ollama** với tham số `format` (JSON schema), model `Qwen3.5-9B` GGUF Q4 chính thức, tắt thinking.
- **Repair loop:** gửi JSON cũ cùng danh sách `Issue` cho LLM sửa, tối đa 3 vòng.
- **OR-Tools fallback:** giữ tập điểm LLM đã chọn, solver sắp lại thứ tự và giờ theo time window và travel time. Không có solution thì trả lời giải thích ràng buộc xung đột.
- **Bộ eval Huế:** 100 request, thay đổi số ngày (1–3), nhịp độ, sở thích, phương tiện. Chia 70 dev và 30 test. Bộ test đóng băng, không bao giờ đưa vào data train.

**Metric (định nghĩa dùng cho Plan 2, 4, 5):**

| Metric | Định nghĩa | Mục tiêu đề xuất (tinh chỉnh sau khi có baseline) |
|---|---|---|
| `first_pass_valid_rate` | % plan không có ERROR ngay lần sinh đầu | ≥ 80% sau finetune |
| `final_valid_rate` | % request có plan hợp lệ sau tối đa 3 lần sửa và fallback | 100% hoặc trả lời "không lập được" có giải thích; không bao giờ trả plan lỗi |
| `avg_repairs` | Số vòng sửa trung bình | ≤ 0,5 |
| `unknown_place_rate` | % stop có `place_id` không tồn tại | ≤ 1% |
| `preference_match` | Người chấm 1–5, mẫu 30 plan | ≥ 4 |
| `latency_p50` | Thời gian sinh một plan 3 ngày trên RTX 4060 | ≤ 90 giây |

`OPENING_HOURS_UNKNOWN` không tính là lỗi của model. Đó là giới hạn của dữ liệu.

**Nghiệm thu:** có báo cáo baseline cho tất cả metric trên bộ dev.

**Cổng quyết định:** chỉ làm Plan 3–4 nếu baseline chưa đạt mục tiêu, ví dụ `first_pass_valid_rate` < 80% hoặc `preference_match` < 4. Nếu prompt cộng repair loop đã đủ tốt thì không finetune.

### Plan 3: Pipeline dataset

**Phần cần làm:**
- **Bộ sinh request đa dạng:** tổ hợp số ngày, nhịp độ, sở thích, phương tiện. Kèm câu tiếng Việt tự nhiên mô tả yêu cầu.
- **Chạy teacher:** `Qwen3.8-27B` trên vLLM, A100 80GB thuê, dùng đúng prompt của Plan 2.
- **Lọc bằng validator:**
  - Chỉ giữ plan `is_valid`.
  - Đồng thời giữ các cặp *(plan lỗi + issues → plan đã sửa)* để dạy kỹ năng repair.
- **Làm sạch:** khử trùng lặp. Loại mọi request trùng hash với bộ test của Plan 2.
- **Kiểm tra thủ công:** người review 5% mẫu, ghi tỉ lệ đạt.
- **Xuất data:** JSONL theo chat template của Qwen, thinking tắt. Mục tiêu 3.000–5.000 mẫu.

**Nghiệm thu:** 100% mẫu train qua validator. Không mẫu nào trùng bộ test. Có thống kê phân bố.

### Plan 4: Finetune LoRA trên GPU thuê và export GGUF

**Phần cần làm:**
- **Stack:** Unsloth + transformers v5, LoRA bf16, chỉ tính loss trên token của assistant.
- **Siêu tham số khởi điểm** (cần tinh chỉnh): r=16, alpha=32, lr=2e-4, 2 epoch, max_seq 4096.
- **Smoke test trước khi chạy run đầy đủ:** train 50 step, merge, convert sang GGUF bằng llama.cpp, chạy được trong Ollama. Phải làm bước này sớm vì kiến trúc Qwen3.5 mới, convert có thể lỗi.
- **Run đầy đủ:** cứ mỗi checkpoint thì chạy eval harness của Plan 2 trên bộ dev.
- **Đóng gói:** merge LoRA, export GGUF Q4_K_M, viết Modelfile Ollama.

**Nghiệm thu:** model GGUF chạy trên RTX 4060. Metric trên bộ dev tốt hơn baseline.

### Plan 5: Eval so sánh và tích hợp hội thoại

**Phần cần làm:**
- So sánh baseline với bản finetune trên bộ test đóng băng. Quyết định go/no-go theo bảng metric ở Plan 2.
- Tích hợp vào conversation API theo brief Phase 2: intent `TRIP_CREATE`, `TRIP_MODIFY`, giữ context.

**Nghiệm thu:** chạy được các kịch bản 5, 6, 9, 10, 11, 14 ở mục 12.1 của brief.

## 4. Chi phí GPU ước tính

**Giá tháng 11/2026, USD/GPU/giờ.** Giá P2P dao động; xem trang live trước khi thuê.

| Việc | GPU đề xuất | Giá | Thời gian ước tính | Chi phí ước tính |
|---|---|---|---|---|
| Plan 3: teacher Qwen3.8-27B bf16 (khoảng 54GB weight) | A100 80GB | ~$0,84 (Vast, median) đến $1,79 (secure) | 2–5 giờ | $2–9 |
| Plan 4: LoRA bf16 Qwen3.5-9B, mỗi run | RTX 5090 32GB / L40S 48GB / A100 80GB | ~$0,53–1,79 | 4–8 giờ | $3–14 |
| Plan 4: tổng 4–6 run (gồm smoke test) | như trên | | | $15–60 |

- **Tổng GPU:** khoảng $20–70.
- **Cơ sở ước tính:** khoảng 5.000 mẫu, mỗi mẫu 2.000–3.000 token; thông lượng chưa đo.
- **RTX 4090 24GB không khuyến nghị.** Mức 22GB của Unsloth chỉ còn rất ít dư cho context 4096, dễ OOM.
- **Chi phí lớn nhất không phải GPU** mà là thời gian review dữ liệu.

## 5. Rủi ro

- **Project nằm trong OneDrive, đường dẫn có dấu** (`Máy tính`):
  - OneDrive sẽ đồng bộ `.venv` và file model vài GB.
  - Một số tool (llama.cpp convert, build native) có thể lỗi với đường dẫn unicode.
  - Khuyến nghị chuyển project sang `C:\dev\TravelAgent` trước khi bắt đầu Plan 1.
- **Thư mục đang nằm trong git repo gốc ở `C:\Users\baoba`.** Plan 1 Task 1 tạo repo riêng.
- **Kiến trúc Qwen3.5 còn mới.** Model card ghi có GGUF cho llama.cpp/Ollama, nhưng việc convert bản đã merge LoRA thì chưa kiểm chứng. Vì vậy Plan 4 có bước smoke test sớm.
- **Độ phủ OSM ở Huế có thể thấp,** nhiều quán không có `opening_hours`. Kết quả sẽ có nhiều cảnh báo `unknown`. Đó là trạng thái thật của dữ liệu, không được tự lấp bằng dữ liệu bịa.
- **Overpass API theo nguyên tắc fair-use.** Tải một lần, lưu file raw, không tải lại trong test.
