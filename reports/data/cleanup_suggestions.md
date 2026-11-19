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

## Lưu ý

- Trùng tên trong nhóm 3 địa điểm sẽ hiện thành 3 cặp; chỉ cần xử lý một lần.
- Quy tắc từ khóa là heuristic. Từ ngắn như "hồ", "đồi", "lăng" khớp đúng dấu để tránh nhầm "đôi", "làng".
- Mục "shop" trong market không có loại tương ứng trong Category, nên chỉ cảnh báo.
