# Gợi ý dọn dữ liệu địa điểm Huế

Sinh bởi `scripts/data/suggest_cleanup.py` từ `data/hue.sqlite` (chỉ đọc).
Đây là danh sách đề xuất để người duyệt xác nhận. Chưa có gì trong DB bị sửa.
Sửa thật: `travel-agent review`, dùng override kèm evidence khi đổi giờ mở cửa.

Địa điểm xét (đã bỏ loại REJECTED): 1587.

## Số dòng theo loại

| Loại | Số dòng |
| --- | ---: |
| duplicate | 91 |
| category | 65 |
| missing_data | 96 |

## Quy tắc

- `duplicate`: tên giống nhau hoặc nằm trong nhau (đã bỏ dấu, bỏ từ Huế/Hue, độ dài tên ngắn nhất từ 6 ký tự), loại tương thích, cách dưới 300 m. Giữ bản có nhiều thuộc tính hơn, rồi nhiều lượt đánh giá hơn.
- `category`: từ khóa trong tên không khớp loại hiện tại. Số dòng theo quy tắc:
  - bãi biển nhưng xếp vào điểm tham quan: 15
  - cầu nhưng xếp vào công viên: 11
  - hồ nhưng xếp vào điểm tham quan: 9
  - phá hoặc đầm nhưng xếp vào điểm tham quan: 5
  - thác nước nhưng xếp vào điểm tham quan: 4
  - trung tâm thương mại, siêu thị hoặc cửa hàng, không phải chợ truyền thống: 8
  - tên ghi cafe hoặc coffee nhưng xếp nhà hàng: 10
  - đồi hoặc núi nhưng xếp vào điểm tham quan: 3
- `missing_data`: trong 100 địa điểm nhiều lượt đánh giá nhất (thuộc tính "Đánh giá"), thiếu giờ mở cửa hợp lệ hoặc thời lượng tham quan.

## Cách điền cột `decision` (trong CSV)

- `ok`: áp dụng gợi ý. Với `duplicate`: loại địa điểm ở cột `place_id`, giữ `other_place_id`. Với `category`: đổi loại sang `suggested_category`.
- `bo`: bỏ qua, không đổi gì.
- Để trống: chưa quyết định, không đổi gì.
- `giu:<place_id>` (chỉ dòng `duplicate`): chọn bản giữ. `place_id` phải là một trong hai id của cặp (`place_id` hoặc `other_place_id`); bản còn lại bị loại.
- `missing_data` chỉ là thông tin, điền gì cũng không đổi. Sửa giờ mở cửa bằng `travel-agent review` (có evidence).
- Không đổi tên cột hoặc thứ tự cột. Khi lưu lại từ Excel, chọn CSV UTF-8 để giữ tiếng Việt.
- Quy trình: chạy `scripts/data/apply_cleanup.py` để xem trước (không ghi gì), rồi chạy lại với `--apply` để áp dụng. Chạy lại không đổi thêm gì.

## Lưu ý

- Trùng tên trong nhóm 3 địa điểm sẽ hiện thành 3 cặp; chỉ cần xử lý một lần.
- Quy tắc từ khóa là heuristic. Từ ngắn như "hồ", "đồi", "lăng" khớp đúng dấu để tránh nhầm "đôi", "làng".
- Mục "shop" trong market không có loại tương ứng trong Category, nên chỉ cảnh báo.
