# Việc còn mở trước khi làm Plan 3 (solver và dataset SFT)

- **Ngày:** 2026-11-12
- **Nguồn:** review toàn nhánh `feat/eval-baseline` sau Plan 2. Các mục dưới đây được xếp loại "trước dataset SFT".
- **Yêu cầu với Plan 3:** xử lý từng mục, hoặc ghi rõ lý do bỏ qua.
- **Baseline đã chốt:** [reports/eval/README.md](../../../reports/eval/README.md). Mục nào làm đổi prompt, candidate, validator hoặc metric thì phải chạy lại baseline trước khi so với SFT.

## Ảnh hưởng tới số đo và dữ liệu train

1. **Candidate lấy từ toàn tỉnh.**
   - Hiện trạng: `select_candidates` không lọc theo khu vực. Baseline có cặp điểm cách nhau hơn 4 giờ di chuyển, ví dụ biển Lăng Cô và nội thành.
   - Cần quyết định: lọc theo bán kính, hoặc theo cụm cho mỗi ngày.
   - Đổi candidate thì phải chạy lại baseline.
2. **Model luôn trả 1 ngày.**
   - Hiện trạng: 0/49 request nhiều ngày có đủ số ngày.
   - Cần tìm nguyên nhân: do prompt, hay do schema (`days` không có `minItems = num_days`).
   - Hướng xử lý: sinh schema theo từng request, với `minItems`/`maxItems` bằng `num_days`.
3. **Độ dài chuỗi so với `max_seq` 2048 của SFT.**
   - Hiện trạng: prompt dài nhất 1.923 token. Output của request 3 ngày, pace packed có thể khoảng 800 token.
   - Trước khi chốt `max_seq`: đo bằng tokenizer Qwen thật, hoặc giảm số candidate.
4. **`UNKNOWN_PLACE` và `DUPLICATE_PLACE` cùng báo một lỗi.**
   - Hiện trạng: một id lạ bị lặp lại thì bị tính hai lỗi.
   - Hậu quả: reward RL phạt đôi (spec mục 8.1).
5. **Ký tự `|` trong tên địa điểm.**
   - Hiện trạng: dòng candidate chưa escape `|`. Hiện chưa có tên nào chứa ký tự này.
   - Cần sửa trước khi sinh dataset, để không phải sinh lại.

## Cổng thăng hạng và tái lập

6. **So sánh khác loại.** Gate cần trả exit 2 khi một trong các trường sau khác với mốc trước: `split`, `evalset_sha256`, `db_sha256`, `n`/`limit`, `schema_format`.
7. **`parse_error_rate` chưa có trong gate.** Model SFT có thể trả JSON hỏng nhiều hơn mà vẫn qua cổng.
8. **Crash và regression cùng exit 1.** Stage `export` sẽ dựa vào exit code, nên cần tách hai mã.
9. **`git_commit` không ghi trạng thái dirty.** Lần chạy baseline có một dòng comment chưa commit; xem `reports/eval/README.md`.
10. **`generate_requests` thiếu chặn.** Hàm lặp vô hạn nếu `count` lớn hơn không gian request. Plan 3 sẽ sinh hàng nghìn request.

## Nhỏ, có thể để sau

- Prompt chỉ ghi thứ trong tuần của ngày đầu.
- File outcomes được mở chế độ `"w"` trước khi nạp DB. Nếu nạp DB lỗi thì còn lại một file rỗng.
- `ReviewStore(read_only=True)` không migrate schema.
- `cli.py` và `__main__` chưa là dep của `baseline_eval`.
- Chuẩn hóa giờ huetripo so sánh `HH:MM` dạng chuỗi, nên giờ không có số 0 đầu sẽ lọt qua. Dữ liệu hiện tại không có trường hợp này.
- Test còn mỏng ở: biên ngưỡng pace, giờ mở cửa theo thứ, `gap == 0`, `http_post_json`.
