# Kết quả eval

Mỗi dòng là một lần chạy trên bộ dev (70 request) của `data/eval/hue_eval_v1.jsonl`.
Số liệu gốc nằm trong file JSON cùng thư mục. Kết quả từng request, kèm output thô của model, nằm trong `*.outcomes.jsonl` (DVC quản lý). Bảng dưới chỉ để đọc nhanh.

| Mốc | Model | Ngày | first_pass_valid_rate | parse_error_rate | unknown_place_rate | avg_stops_per_day | distinct_place_count | latency_p50_s |
|---|---|---|---|---|---|---|---|---|
| baseline | qwen3.5:4b (Q4_K_M) | 2026-11-12 | 0.057 (4/70) | 0.000 | 0.003 | 5.06 | 250 | 4.6 |

## Ghi chú baseline

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
- **Cấu hình:**
  - temperature 0.0, seed 0, `num_predict` 2048, `num_ctx` 8192
  - thinking tắt
  - output bị ép theo JSON schema viết tay (`ITINERARY_FORMAT_SCHEMA`)
  - prompt rule 5 ghi rõ cách ước tính thời gian di chuyển
- **Git commit và hash dữ liệu:** xem `meta` trong `baseline_dev.json`.
  - Lúc chạy, `configs/eval.yaml` chỉ khác commit `a7cd538` ở một dòng comment; giá trị tham số giữ nguyên.
  - `db_sha256` là sha256, còn file `.dvc` ghi md5 (`c7fa2450…`), nên hai giá trị khác nhau là bình thường.
