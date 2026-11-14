# Design: SFT rồi RL cho Qwen 4B lập lịch trình Huế (train local 8GB)

- **Ngày:** 2026-11-11
- **Roadmap liên quan:** [2026-11-03-hue-planner-roadmap.md](../plans/2026-11-03-hue-planner-roadmap.md)
- **Plan đang dở:** [2026-11-03-plan-1-hue-foundation.md](../plans/2026-11-03-plan-1-hue-foundation.md) (Task 6–7, validator, chưa code)

---

## 1. Mục tiêu

Finetune một model Qwen 4B để sinh `Itinerary` JSON hợp lệ cho Huế, qua hai giai đoạn:

1. **SFT** trên nhãn do solver sinh ra.
2. **RL** với reward lấy từ `validate_itinerary()`.

Mục tiêu của RL là **tính hợp lệ**: ít ERROR hơn, không bịa `place_id`, plan sạch ngay lần sinh đầu. Chất lượng "gu" của lịch trình không nằm trong mục tiêu của spec này.

Kết quả cuối là bảng so sánh ba mốc trên cùng một bộ eval: baseline 4B chưa train, SFT, SFT+RL.

## 2. Quyết định đã chốt, và chỗ thay đổi so với roadmap

| Chủ đề | Roadmap 2026-11-03 | Spec này |
|---|---|---|
| Base model | `Qwen/Qwen3.5-9B` | Qwen3.5 bản 4B. Tên repo chính xác phải xác minh ở bước smoke test. |
| Cổng quyết định finetune | Chỉ finetune nếu baseline chưa đạt | Bỏ cổng. Vẫn đo baseline để có mốc so sánh. |
| Nguồn nhãn SFT | Teacher `Qwen3.8-27B` trên A100 thuê | Solver (chọn điểm theo luật + OR-Tools), lọc bằng validator. Miễn phí. |
| Phương pháp finetune | LoRA bf16 trên GPU thuê | QLoRA 4-bit trên RTX 4060 Laptop 8GB. |
| RL | Ngoài phạm vi (brief mục 2.2) | Thêm giai đoạn GRPO, có fallback best-of-N. |
| Số candidate trong prompt | Tối đa 40 | `max(12, min(30, số stop tối đa của pace × num_days + 4))`. Validator cấm lặp `place_id`, nên 20 cố định không đủ cho plan 3 ngày packed (cần tới 24 điểm khác nhau). |
| Khu vực candidate | Không nêu | Chỉ lấy điểm trong bán kính quanh Đại Nội, tùy phương tiện: car và motorbike 12 km, walk 2 km. |

**Đánh đổi đã chấp nhận:**

- Tài liệu Unsloth (theo ghi nhận trong roadmap) khuyên không train QLoRA 4-bit cho Qwen3.5. Chọn train local nghĩa là chấp nhận rủi ro này. Smoke test là cổng kiểm tra.
- Model sẽ học theo cách xếp lịch của solver: đúng luật nhưng đều tay.
- Nếu SFT trên nhãn solver đã đạt tỉ lệ hợp lệ rất cao thì RL còn ít dư địa. Báo cáo ghi đúng số đo được, kể cả khi RL không cải thiện.

## 3. Ngoài phạm vi

- Repair loop lúc chạy và fallback OR-Tools lúc chạy (Plan 2 của roadmap). Spec này chỉ dùng solver để sinh nhãn.
- Metric `preference_match` do người chấm.
- Reward về chất lượng (khớp sở thích, tối ưu quãng đường).
- Tích hợp hội thoại, LangGraph.
- Giám sát production, phát hiện drift, A/B test. Chưa có production.
- Orchestrator (Airflow, Kubeflow), feature store.

## 4. Kiến trúc

```text
PlanRequest
  -> select_candidates()   12–30 Place từ SQLite (công thức ở mục 2)
  -> build_messages()      prompt chat duy nhất, dùng chung mọi giai đoạn
  -> [model sinh Itinerary JSON | solver sinh nhãn]
  -> validate_itinerary()  -> ValidationReport
  -> reward() / metric eval / lọc dataset
```

### 4.1 Module logic thuần (test không cần GPU)

| Module | Trách nhiệm | Phụ thuộc |
|---|---|---|
| `travel_agent/validation/` | `validate_itinerary()` theo Plan 1 Task 6–7 | domain, routing |
| `travel_agent/planning/candidates.py` | `select_candidates(request, repo, seed)`: lọc theo `interests` và bán kính, giữ đa dạng `Category`, số lượng theo công thức ở mục 2 | domain, `place_repository` |
| `travel_agent/planning/prompt.py` | `build_messages(request, candidates, issues=None)`: prompt cho cả baseline, SFT, RL và runtime | domain |
| `travel_agent/planning/solver.py` | `solve(request, candidates, travel, seed)`: chọn điểm và xếp giờ | OR-Tools, domain, routing |
| `travel_agent/training/requests.py` | Sinh `PlanRequest` đa dạng; chia train/dev/test theo hash | domain |
| `travel_agent/training/corrupt.py` | Phá plan đúng có chủ đích để tạo mẫu repair | domain |
| `travel_agent/training/reward.py` | `reward(request, raw_output, places, travel) -> float` | validation |

`build_messages()` là nguồn duy nhất của prompt. Lệch prompt giữa lúc train và lúc chạy là lỗi hay gặp nhất của loại pipeline này, nên có snapshot test.

### 4.2 Script cần GPU

Nằm trong `scripts/train/`, phụ thuộc khai báo ở extra `train` của `pyproject.toml`:

- `build_dataset.py`, `check_dataset.py`, `sft.py`, `grpo.py`, `best_of_n.py`, `eval.py`, `export_gguf.py`.

Mỗi script đọc một file config YAML và không chứa logic nghiệp vụ; logic nằm ở các module mục 4.1.

## 5. Solver sinh nhãn

**Input:** `PlanRequest`, danh sách candidate, `TravelTimeProvider`, seed.

**Bước 1, chọn điểm:**

- Chấm mỗi candidate theo mức khớp `interests`, cộng nhiễu ngẫu nhiên có seed. Nhiễu để cùng một request cho ra nhiều plan khác nhau; không có thì model học thuộc một đáp án.
- Số stop mỗi ngày theo `pace`: relaxed 3–4, moderate 5–6, packed 7–8. Khớp ngưỡng `overloaded_day` của validator (4, 6, 8).
- Ép có stop `restaurant` giao với khung 11:00–13:30 và 17:30–20:00 khi khung ngày bao trọn các khung đó.

**Bước 2, xếp lịch:**

- OR-Tools Routing với time window lấy từ `opening_hours` đã parse. Điểm không rõ giờ mở cửa thì window bằng khung ngày.
- Thời lượng tham quan là hằng số theo `Category`. Đây là heuristic sản phẩm, chưa kiểm chứng, ghi rõ trong code.
- Có timeout. Kết quả `INFEASIBLE` hoặc hết giờ thì bỏ mẫu và đếm vào thống kê.

**Output:** `Itinerary` với `note = null`. Solver không có dữ kiện thật để viết ghi chú, và brief cấm bịa thông tin du lịch.

## 6. Dataset SFT

- **Quy mô:** 3.000–5.000 mẫu.
- **Mẫu sinh plan (khoảng 85%):** `build_messages(request, candidates)` + câu trả lời assistant là `Itinerary` JSON của solver.
- **Mẫu repair (khoảng 15%):** lấy plan đúng, phá bằng `corrupt.py` (đổi sang `place_id` lạ, làm chồng giờ, xếp vào lúc đóng cửa, thiếu thời gian di chuyển), chạy validator lấy issues, gọi `build_messages(..., issues=...)`. Đáp án là plan gốc.
- **Điều kiện bắt buộc:**
  - 100% đáp án qua `validate_itinerary()` không có ERROR.
  - Không request nào trùng hash với bộ dev hoặc test.
- **Định dạng:** JSONL theo chat template của Qwen, thinking tắt.
- **Kèm theo:** `manifest.json` (mục 10.2).

## 7. SFT

- **Stack:** Unsloth, QLoRA 4-bit. Loss chỉ tính trên token của assistant.
- **Siêu tham số khởi điểm (cần tinh chỉnh):** r=16, alpha=32, lr=2e-4, 2 epoch, `max_seq` 4096, batch 1 với gradient accumulation 8.
- **`max_seq` 4096:** dataset thử 4.000 mẫu đo bằng tokenizer thật có trung vị 1.694, p90 2.712, dài nhất 3.885 token; 2048 cắt mất 31% mẫu, gồm mọi plan 3 ngày moderate và packed. Smoke test phải xác nhận 4096 vừa 8 GB VRAM. `check.max_tokens` trong `configs/dataset.yaml` phải bằng giá trị này.
- **Smoke test trước run đầy đủ:** load model 4-bit, train 20 step, đo VRAM đỉnh, merge, convert GGUF, chạy được trong Ollama.
- **Run đầy đủ:** eval trên dev ở mỗi checkpoint. Giữ checkpoint có `first_pass_valid_rate` cao nhất.

## 8. RL

### 8.1 Reward

Hàm thuần, giá trị trong [-1, 1]:

| Tình huống | Reward |
|---|---|
| Output không parse được JSON hoặc sai schema `Itinerary` | -1,0 (kết thúc) |
| Parse được | bắt đầu từ +1,0 |
| Mỗi `unknown_place` | -0,5 |
| Mỗi ERROR khác | -0,2 |
| Mỗi ngày có số stop dưới sàn (relaxed 3, moderate 4, packed 6) | -0,3 |
| Mỗi `overloaded_day` hoặc `missing_meal` | -0,05 |
| `opening_hours_unknown` | 0 |

- Kẹp dưới tại -1,0.
- `opening_hours_unknown` không bị phạt vì đó là giới hạn của dữ liệu, không phải lỗi của model.
- Sàn số stop chặn việc model lách bằng plan tối thiểu (một stop mỗi ngày luôn hợp lệ). Phạt `overloaded_day` chặn chiều ngược lại.
- Các trọng số là khởi điểm, chưa kiểm chứng; chỉnh sau smoke test.

### 8.2 GRPO (hướng chính)

- **Stack:** TRL `GRPOTrainer`, khởi động từ adapter LoRA tốt nhất của SFT.
- **Prompt:** request sinh mới từ `requests.py`, thuộc tập train. Không cần nhãn.
- **Siêu tham số khởi điểm:** 4 rollout mỗi prompt, lr 5e-6, `max_completion_length` 1024, temperature 1,0, checkpoint mỗi 25 step, resume được.
- **Log mỗi step:** reward trung bình, tỉ lệ parse lỗi, số stop trung bình, phân bố `IssueCode`.
- **Smoke test:** 5 step, đo VRAM đỉnh và số phút mỗi step.

### 8.3 Cổng chuyển sang fallback

Chuyển sang best-of-N nếu smoke GRPO bị OOM sau khi đã giảm `max_completion_length` và số candidate, hoặc chậm hơn 5 phút mỗi step.

### 8.4 Best-of-N lặp (fallback)

Mỗi vòng:

1. Export GGUF của model hiện tại, chạy qua Ollama.
2. Sinh 4 plan cho mỗi request, khoảng 1.000 request tập train.
3. Chấm bằng `reward.py`. Với mỗi request giữ plan điểm cao nhất, và chỉ khi reward ≥ 0,9.
4. SFT tiếp 1 epoch trên tập vừa giữ.

Chạy 3–5 vòng. Dùng lại nguyên `reward.py` và harness eval.

### 8.5 Phát hiện lách reward và điều kiện dừng

- Theo dõi trên dev: số stop trung bình và số `place_id` khác nhau được dùng. Reward tăng mà hai chỉ số này sụt thì dừng và sửa reward.
- Dừng khi `first_pass_valid_rate` trên dev không tăng qua 3 lần eval liên tiếp, hoặc tụt dưới mức của SFT.

## 9. Eval

- **Bộ eval:** 100 request Huế, thay đổi số ngày (1–3), `pace`, `interests`, `travel_mode`. Chia 70 dev và 30 test theo hash. Test đóng băng, chỉ chạy ở lần so sánh cuối cùng.
- **Một harness cho ba mốc:** baseline 4B (GGUF chính thức qua Ollama), SFT, SFT+RL. Cùng prompt, cùng candidate, cùng seed, thinking tắt.
- **Metric tự động:**

| Metric | Định nghĩa |
|---|---|
| `first_pass_valid_rate` | % plan không có ERROR ở lần sinh đầu |
| `parse_error_rate` | % output không parse được thành `Itinerary` |
| `unknown_place_rate` | % stop có `place_id` ngoài danh sách candidate |
| `avg_stops_per_day` | Số stop trung bình mỗi ngày |
| `distinct_place_count` | Số `place_id` khác nhau được dùng trên toàn bộ dev |
| `issue_code_distribution` | Số lần xuất hiện của từng `IssueCode` |
| `latency_p50` | Thời gian sinh một plan trên RTX 4060 |

- **Output:** một file JSON kết quả mỗi lần chạy, và bảng so sánh ba mốc.

## 10. MLOps

### 10.1 Config

- Mỗi giai đoạn một file YAML: `configs/dataset.yaml`, `configs/sft.yaml`, `configs/grpo.yaml`, `configs/eval.yaml`.
- Script không hardcode siêu tham số. DVC theo dõi tham số qua các file này.

### 10.2 Version dữ liệu và model bằng DVC

- DVC theo dõi: file SQLite POI, dataset JSONL, bộ eval, adapter LoRA, file GGUF.
- Git chỉ giữ file `.dvc` và `dvc.lock`.
- **DVC remote:** một thư mục local nằm ngoài OneDrive, ví dụ `C:\dev\travelagent-dvc`. Có thể đổi sang remote đám mây sau mà không sửa pipeline.
- Mỗi dataset có `manifest.json`: hash nội dung JSONL, hash file SQLite, git commit, seed, số mẫu theo loại, phân bố theo số ngày, `pace`, `travel_mode`, số mẫu solver bỏ.
- Dataset bất biến. Sửa thì ra version mới.

### 10.3 Pipeline `dvc.yaml`

```text
build_dataset -> check_dataset -> sft -> eval_sft -> rl -> eval_rl -> export
                                  baseline_eval (độc lập, chỉ phụ thuộc bộ eval)
```

- Mỗi stage khai báo `deps`, `params`, `outs`, `metrics`. `dvc repro` chỉ chạy lại stage có đầu vào thay đổi.
- Stage `rl` chạy `grpo.py` hoặc `best_of_n.py` tùy tham số `rl.method` trong config.
- Thư mục output của training đặt ngoài OneDrive (checkpoint vài GB, và đường dẫn có dấu có thể làm lỗi công cụ convert).

### 10.4 Theo dõi thí nghiệm

- MLflow chạy local, lưu file, không cần server, dùng được offline.
- Log: tham số config, git commit, hash dataset, loss, reward, metric eval ở từng checkpoint.
- `dvc metrics diff` dùng để so sánh giữa các commit.

### 10.5 Registry và cổng thăng hạng

- Mỗi run có `model_card.json`: base model, hash dataset, config, metric dev, run cha (adapter SFT nào sinh ra run RL nào).
- `eval.py` trả exit code khác 0 khi metric dev thấp hơn mốc trước. Stage `export` phụ thuộc vào kết quả đó, nên chỉ model qua cổng mới được export GGUF.
- Thứ tự thăng hạng: baseline, SFT, SFT+RL.

### 10.6 Kiểm tra dữ liệu

`check_dataset.py` chạy trước khi train và chặn train nếu hỏng:

- 100% đáp án qua validator không có ERROR.
- Không request nào trùng hash với dev hoặc test.
- Mọi mẫu parse được theo schema; độ dài token không vượt `max_seq`.
- Phân bố theo số ngày, `pace`, `travel_mode` không lệch quá ngưỡng trong config.

### 10.7 Tái lập

- Seed cố định ở solver, sinh request, train, sinh mẫu eval.
- Khóa phiên bản phụ thuộc của extra `train`.
- Mỗi run ghi git commit, hash dataset và config.

### 10.8 CI bằng GitHub Actions

- Workflow `.github/workflows/ci.yml`: ruff, mypy, pytest cho phần logic thuần; kiểm tra `dvc.yaml` hợp lệ. Không chạy bước cần GPU.
- **Điều kiện:** repo hiện chưa có remote. Workflow chỉ chạy sau khi tạo repo GitHub và push. Tạo remote là việc của chủ repo; spec này không tự làm.
- Trong lúc chưa có remote, cùng các lệnh đó chạy local bằng một lệnh.

## 11. Test

TDD cho mọi module logic thuần:

- **`candidates`:** không vượt giới hạn theo công thức ở mục 2; có đa dạng `Category`; cùng seed cho cùng kết quả.
- **`prompt`:** snapshot test. Đổi prompt thì test vỡ có chủ đích.
- **`solver`:** mọi plan sinh ra qua validator không có ERROR; ca không khả thi trả trạng thái rõ ràng; cùng seed cho cùng plan.
- **`reward`:** một test cho mỗi dòng trong bảng reward; JSON hỏng; kẹp dưới.
- **`requests`:** chia tập ổn định theo hash; không request nào nằm ở cả train và test.
- **`corrupt`:** mỗi kiểu phá sinh đúng `IssueCode` mong muốn.
- **`check_dataset`:** bắt được dataset có mẫu lỗi, mẫu trùng test.

Script GPU không có unit test; kiểm bằng smoke run.

## 12. Xử lý lỗi

| Tình huống | Hành vi |
|---|---|
| Smoke SFT bị OOM | Giảm `max_seq`, giảm số candidate. Vẫn OOM thì dừng và báo lại. Không tự đổi model. |
| Smoke GRPO OOM hoặc quá chậm | Chuyển sang best-of-N theo mục 8.3. |
| Model sinh JSON hỏng | Reward -1,0, đếm vào `parse_error_rate`. Không sửa hộ output. |
| Solver không khả thi hoặc hết giờ | Bỏ mẫu, ghi thống kê. |
| Train đứt giữa chừng | Resume từ checkpoint gần nhất. |
| `check_dataset` hỏng | Chặn stage train. |

## 13. Thứ tự triển khai

Mỗi bước một implementation plan riêng. Plan sau viết chi tiết khi plan trước xong, vì phụ thuộc interface và số đo thật.

1. **Validator.** Chạy tiếp Plan 1 Task 6–7 đã có.
2. **Candidates, prompt, bộ eval, baseline 4B, khung MLOps** (DVC init, `dvc.yaml` khung, MLflow, CI).
3. **Solver và dataset SFT**, gồm `corrupt` và `check_dataset`.
4. **SFT:** smoke test, run đầy đủ, eval, model card.
5. **RL:** reward, smoke GRPO, GRPO hoặc best-of-N, eval, so sánh ba mốc trên test.

## 14. Rủi ro

- **Model 4B:** tên repo chính xác, hỗ trợ QLoRA 4-bit và khả năng convert GGUF của bản đã merge chưa kiểm chứng. Smoke test ở bước 4 là cổng; kiểm tra tên repo và license ngay ở bước 2 khi chạy baseline.
- **VRAM 8GB:** GRPO phải backward qua prompt khoảng 2.000 token cộng output khoảng 1.000 token, nhân 4 rollout. Có thể không vừa. Đã có fallback.
- **Unsloth trên Windows native** chưa kiểm chứng; có thể phải dùng WSL2.
- **Đường dẫn OneDrive có dấu** (`Máy tính`): output training và DVC remote đặt ngoài OneDrive. Roadmap đã khuyến nghị chuyển cả project sang `C:\dev\TravelAgent`.
- **Reward bị lách:** đã có sàn số stop và chỉ số theo dõi, nhưng có thể còn kiểu lách chưa lường trước. Xem mẫu output bằng mắt ở mỗi lần eval.
- **Thời gian train local:** chưa đo. Smoke test cho số phút mỗi step trước khi cam kết run đầy đủ.
