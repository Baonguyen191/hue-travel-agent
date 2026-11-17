# Kết quả eval

Mỗi dòng là một lần chạy trên bộ dev (70 request) của `data/eval/hue_eval_v1.jsonl`.
Số liệu gốc nằm trong file JSON cùng thư mục. Kết quả từng request, kèm output thô của model, nằm trong `*.outcomes.jsonl` (DVC quản lý). Bảng dưới chỉ để đọc nhanh.

| Mốc | Model | Ngày | first_pass_valid_rate | parse_error_rate | unknown_place_rate | avg_stops_per_day | distinct_place_count | latency_p50_s |
|---|---|---|---|---|---|---|---|---|
| baseline, trước khi sửa candidate và schema | qwen3.5:4b (Q4_K_M) | 2026-11-12 | 0.057 (4/70) | 0.000 | 0.003 | 5.06 | 250 | 4.6 |
| baseline | qwen3.5:4b (Q4_K_M) | 2026-11-14 | 0.086 (6/70) | 0.000 | 0.010 | 5.39 | 423 | 9.1 |
| SFT sft-v1, checkpoint 250 | travel-sft-v1 (Qwen3.5-4B + LoRA r16, Q4_K_M) | 2026-11-17 | 0.229 (16/70) | 0.000 | 0.000 | 5.56 | 470 | 7.6 |

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
