# Kết quả eval

Mỗi dòng là một lần chạy trên bộ dev (70 request) của `data/eval/hue_eval_v1.jsonl`.
Số liệu gốc nằm trong file JSON cùng thư mục. Kết quả từng request, kèm output thô của model, nằm trong `*.outcomes.jsonl` (DVC quản lý). Bảng dưới chỉ để đọc nhanh.

| Mốc | Model | Ngày | first_pass_valid_rate | parse_error_rate | unknown_place_rate | avg_stops_per_day | distinct_place_count | latency_p50_s |
|---|---|---|---|---|---|---|---|---|
| baseline, trước khi sửa candidate và schema | qwen3.5:4b (Q4_K_M) | 2026-11-12 | 0.057 (4/70) | 0.000 | 0.003 | 5.06 | 250 | 4.6 |
| baseline | qwen3.5:4b (Q4_K_M) | 2026-11-14 | 0.086 (6/70) | 0.000 | 0.010 | 5.39 | 423 | 9.1 |
| SFT sft-v1, checkpoint 250 | travel-sft-v1 (Qwen3.5-4B + LoRA r16, Q4_K_M) | 2026-11-17 | 0.229 (16/70) | 0.000 | 0.000 | 5.56 | 470 | 7.6 |
| RL rl-v1 (best-of-N, vòng 1) | travel-rl-v1 (SFT step 250 + 1 epoch trên 42 plan tự sinh, Q4_K_M) | 2026-11-18 | 0.386 (27/70) | 0.000 | 0.000 | 5.34 | 465 | 8.1 |

## So sánh cuối trên bộ test (2026-11-18, chạy đúng một lần)

Bộ test 30 request, đóng băng từ chặng 1, chạy một lần cho cả ba mốc bằng `eval --split test --allow-test`, cùng tham số sinh với dev. Số liệu gốc ở `{baseline,sft,rl}_test.json` và `*_test.outcomes.jsonl`.

| Mốc | Model | first_pass_valid_rate | parse_error_rate | unknown_place_rate | avg_stops_per_day | distinct_place_count | latency_p50_s |
|---|---|---|---|---|---|---|---|
| baseline | qwen3.5:4b | 0.067 (2/30) | 0.000 | 0.033 | 5.68 | 215 | 7.4 |
| SFT | travel-sft-v1 | 0.467 (14/30) | 0.000 | 0.000 | 4.75 | 202 | 5.5 |
| SFT+RL | travel-rl-v1 | 0.533 (16/30) | 0.000 | 0.000 | 4.58 | 196 | 5.5 |

- **Đọc kết quả:** SFT hơn baseline 12 request, rõ ràng vượt nhiễu. RL hơn SFT 2 request: với 30 request, chênh 1–2 request nằm trong nhiễu, nên trên test RL **chưa chứng minh được** là tốt hơn SFT. Trên dev (70 request) RL hơn SFT 11 request (27 so với 16).
- **Bộ test dễ hơn dev:** 15/30 request chỉ 1 ngày (dev 21/70) và 5/30 là pace packed (dev 29/70). Vì vậy tỉ lệ trên test cao hơn dev ở cả ba mốc; chỉ so được giữa các mốc trên cùng một bộ.
- **Theo số ngày** (đạt / tổng): baseline 1/15, 0/7, 1/8; SFT 9/15, 2/7, 3/8; RL 12/15, 2/7, 2/8.
- **Request có ít nhất một ERROR:**
  - baseline: `travel_time_insufficient` 26, `closed_during_visit` 11, `unknown_place` 4, `duplicate_place` 4;
  - SFT: `travel_time_insufficient` 16, `closed_during_visit` 1;
  - RL: `travel_time_insufficient` 14.
- **Model cuối:** `travel-rl-v1`. Cả hai mô hình đã train đều không bịa `place_id` và không lỗi parse. Lỗi còn lại gần như chỉ là thiếu thời gian di chuyển giữa hai điểm.
- **Giới hạn:** giờ mở cửa giả định "mọi ngày" cho 1.447/1.587 điểm; thời gian di chuyển là ước tính Haversine, chưa phải đường thật. Plan qua validator vẫn có thể sai ngoài thực tế.

## Ghi chú RL 2026-11-18

- **Phương pháp:** best-of-N (spec 8.4). Smoke GRPO không qua cổng spec 8.3: 8,8 phút mỗi step, VRAM đỉnh 9,43 GB trên GPU 8 GB. Chi tiết ở plan 5.
- **Vòng 1:** `travel-sft-v1` sinh 4 plan cho mỗi request trong 100 request RL (temperature 1,0, cùng JSON schema như eval). Chấm bằng `training/reward.py`, giữ plan tốt nhất nếu reward ≥ 0,9: được 42/100. Train tiếp 1 epoch từ adapter SFT step 250, lr 5e-5.
- **Vòng 2** (500 request, sinh bằng model vòng 1, giữ 318): dev 0,414 (29/70), chỉ hơn vòng 1 đúng 1 request. Số stop mỗi ngày giảm còn 5,01 (-9,9% so với SFT), sát ngưỡng 10% của spec 8.5: model bắt đầu chọn lịch thưa để dễ đủ thời gian di chuyển. Người dùng chọn vòng 1 và dừng RL.
- **Chạy bằng** `dvc repro --single-item` cho `rl`, `export_rl`, `eval_rl` (train lại vòng 1 từ dataset đã lưu ở `data/rl/rl-v1/round-1.jsonl`). Qua cổng so với SFT (exit 0). Lần chạy tay của cùng vòng được 0,400 (28/70); train lại cho 27/70, lệch 1 request do train trên GPU không tất định hoàn toàn.
- **So với SFT** (số lần lỗi): `travel_time_insufficient` 181 xuống 108, `closed_during_visit` 10 xuống 7, `duplicate_place` 8 xuống 2. Số stop mỗi ngày -4,0%, số địa điểm khác nhau -1,1%, trong ngưỡng 10%.
- Model card ở `models/rl/rl-v1/model_card.json`, `parent` là `sft-v1` step 250 (sha256 adapter khớp `models/sft/sft-v1/export.json`).

## Ghi chú SFT 2026-11-17

- **Chạy bằng** `dvc repro export_sft eval_sft`, cùng tham số sinh với baseline. Qua cổng so với baseline (exit 0). Model card ở `models/sft/sft-v1/model_card.json`.
- **Meta ghi `5670d32…-dirty`:** lúc chạy, `configs/sft.yaml` mới đổi `export.checkpoint` từ null sang 250 và chưa commit.
- **Chọn checkpoint** (dev, cùng tham số; chỉ 250 được eval qua DVC, ba cái còn lại chạy tay rồi xóa GGUF):

  | checkpoint | first_pass_valid_rate | lần `travel_time_insufficient` |
  |---|---|---|
  | 250 | 0.229 (16/70) | 181 |
  | 500 | 0.229 (16/70) | 219 |
  | 750 | 0.071 (5/70) | 302 |
  | 1000 | 0.129 (9/70) | 329 |

  250 và 500 hòa, lấy step sớm hơn (plan 4 mục 2). Loss train vẫn giảm đều tới step 1000 (khoảng 0.084 ở step 100, 0.040 ở step 1000), nhưng lỗi thời gian di chuyển tăng dần từ sau step 500: train lâu hơn làm model kém đi.
- **Theo số ngày:** 1 ngày đạt 8/21, 2 ngày đạt 6/21, 3 ngày đạt 2/28.
- **Lỗi nhiều nhất** (số request có ít nhất một ERROR loại đó, trên 70; baseline trong ngoặc):
  - `travel_time_insufficient`: 51 (59)
  - `closed_during_visit`: 8 (40)
  - `duplicate_place`: 7 (8)
  - `unknown_place`: 0 (4)
  - `stop_time_order`: 0 (1)
- **Cảnh báo `missing_meal`** (không phải ERROR) giảm từ 171 lần xuống 3.
- **Độ dài:** prompt dài nhất 1.936 token, output dài nhất 858 token. `done_reason` là `stop` ở cả 70 request.

## Ghi chú baseline 2026-11-14

- **Code:** commit `c33a20e`, chạy bằng `dvc repro baseline_eval`. Meta ghi `c33a20e…-dirty` dù cây sạch: đó là lỗi đã sửa ở `136fbb5` (DVC xóa output đã track trước khi chạy).
- **Khác lần trước:** candidate lọc theo bán kính quanh Đại Nội tùy phương tiện; schema ép đúng số ngày của từng request.
- **Theo số ngày:** 1 ngày đạt 4/21, 2 ngày đạt 0/21, 3 ngày đạt 2/28.
- **Số ngày đúng ở 70/70 request.** Lần trước 49 request nhiều ngày đều sai số ngày.
- **Lỗi nhiều nhất** (số request có ít nhất một ERROR loại đó, trên 70):
  - `travel_time_insufficient`: 59
  - `closed_during_visit`: 40
  - `duplicate_place`: 8
  - `unknown_place`: 4
  - `stop_time_order`: 1
- **Độ dài:** prompt dài nhất 1.936 token, output dài nhất 790 token. `done_reason` là `stop` ở cả 70 request.
- **Thử schema:** trên 5 request nhiều ngày của bộ dev, schema cũ cho 1 ngày ở cả 5 lần, schema ép số ngày cho đúng số ngày yêu cầu ở cả 5 lần.

## Model cũ trong Ollama

Model cũ trong Ollama, nguồn gốc và prompt lúc train chưa rõ, chạy với code trước chặng 1 (commit `8097840`), chỉ để tham khảo. Code lúc đó chưa lọc candidate theo bán kính và chưa ép số ngày. File kết quả từng request (`old_*.outcomes.jsonl`) không đưa vào git hay DVC.

| Model | Ngày | first_pass_valid_rate | parse_error_rate | unknown_place_rate | avg_stops_per_day | distinct_place_count | latency_p50_s |
|---|---|---|---|---|---|---|---|
| planner-grpo-g1-108 | 2026-11-14 | 0.071 (5/70) | 0.000 | 0.106 | 7.15 | 681 | 12.5 |
| planner-grpo-g1-216 | 2026-11-14 | 0.043 (3/70) | 0.000 | 0.049 | 7.54 | 659 | 13.0 |
| planner-grpo-g1-324 | 2026-11-14 | 0.057 (4/70) | 0.000 | 0.099 | 6.78 | 655 | 12.2 |
| planner-sft-r1d-1000 | 2026-11-14 | 0.014 (1/70) | 0.043 (3/70) | 0.013 | 9.13 | 618 | 12.5 |
| planner-sft-r1d-2000 | 2026-11-14 | 0.000 (0/70) | 0.000 | 0.012 | 8.43 | 670 | 13.3 |
| planner-sft-r1d-3000 | 2026-11-14 | 0.014 (1/70) | 0.000 | 0.058 | 8.24 | 697 | 13.2 |
| planner-sft-r2 | 2026-11-14 | 0.000 (0/70) | 0.000 | 0.009 | 7.41 | 641 | 12.8 |

## Ghi chú baseline 2026-11-12

File JSON của lần chạy này đã bị lần chạy 2026-11-14 ghi đè; bản gốc nằm trong lịch sử git ở commit `b3f5b93`.

- **Lỗi nhiều nhất** (số request có ít nhất một ERROR loại đó, trên 70):
  - `travel_time_insufficient`: 57 request (160 lần)
  - `day_count_mismatch`: 49 request
  - `closed_during_visit`: 24 request (30 lần)
  - `unknown_place` và `stop_time_order`: mỗi loại 1 lần
- **Theo số ngày:** request 1 ngày đạt 4/21. Request 2 và 3 ngày đạt 0/49. Model luôn trả đúng 1 ngày, nên toàn bộ 49 request nhiều ngày đều có `day_count_mismatch`.
- **Nhận xét khi đọc mẫu:**
  - Model hầu như không bịa `place_id`: 1 trên khoảng 350 stop.
  - Model xếp các điểm dừng cách nhau cố định 30–45 phút, bất kể khoảng cách thật.
  - Candidate được lấy từ toàn tỉnh. Có điểm như biển Lăng Cô cần khoảng 236–261 phút di chuyển (ước tính), nên lịch cách nhau 30 phút không thể hợp lệ. Đây là giới hạn của bước chọn candidate (chưa lọc theo khu vực), không chỉ là lỗi của model.
  - Số stop mỗi ngày theo pace: relaxed 4.2, moderate 5.2, packed 5.3. Model chưa tăng số stop cho pace packed (cần 6–8).
  - `done_reason` là `stop` ở cả 70 request. Prompt dài nhất 1.923 token, output dài nhất 301 token.
- **Dữ liệu:** `data/hue.sqlite` có 1.587 điểm huetripo. 1.447 điểm có giờ mở cửa được chuẩn hóa từ nguồn, với giả định "áp dụng mọi ngày" vì nguồn không ghi ngày. Giờ mở cửa của các điểm này được kiểm tra; 140 điểm còn lại là unknown.
- **Cấu hình** (giống lần 2026-11-14):
  - temperature 0.0, seed 0, `num_predict` 2048, `num_ctx` 8192
  - thinking tắt
  - output bị ép theo JSON schema viết tay (`ITINERARY_FORMAT_SCHEMA`)
  - prompt rule 5 ghi rõ cách ước tính thời gian di chuyển
- **Git commit và hash dữ liệu:** xem `meta` trong `baseline_dev.json` ở commit `b3f5b93`.
  - Lúc chạy, `configs/eval.yaml` chỉ khác commit `a7cd538` ở một dòng comment; giá trị tham số giữ nguyên.
  - `db_sha256` là sha256, còn file `.dvc` ghi md5 (`c7fa2450…`), nên hai giá trị khác nhau là bình thường.
