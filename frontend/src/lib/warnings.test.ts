import { describe, expect, it } from "vitest";
import { translateWarning, translateWarnings } from "./warnings";

describe("translateWarning", () => {
  it("translates the per-visit opening-hour note used on every stop", () => {
    expect(translateWarning("Opening hours require verification before the visit.")).toBe(
      "Giờ mở cửa cần xác minh trước khi đi.",
    );
  });

  it("keeps the numbers and names from the backend message", () => {
    expect(translateWarning("3 places farther than 15 km from the centre were skipped.")).toBe(
      "Bỏ qua 3 địa điểm cách trung tâm hơn 15 km.",
    );
    expect(translateWarning("Chùa Thiên Mụ (Chùa Linh Mụ) did not fit its source opening-hour range.")).toBe(
      "Chùa Thiên Mụ (Chùa Linh Mụ) không vừa khung giờ mở cửa trong nguồn.",
    );
    expect(translateWarning("Visit duration clamped from 600 to 240 minutes.")).toBe(
      "Thời gian tham quan được điều chỉnh từ 600 xuống 240 phút.",
    );
  });

  it("translates the merged-places note and keeps the place in brackets", () => {
    expect(
      translateWarning(
        "10 places sharing a location with an already chosen site were merged (for example inside Đại Nội).",
      ),
    ).toBe("Gộp 10 địa điểm cùng vị trí với một điểm đã chọn (ví dụ trong Đại Nội).");
  });

  it("translates the budget messages, including the shortfall amount with dot grouping", () => {
    expect(translateWarning("Cheapest option exceeds the budget by 500,000 VND.")).toBe(
      "Phương án rẻ nhất vượt ngân sách 500.000 ₫.",
    );
    expect(translateWarning("2 people may not fit in 1 room(s)")).toBe("2 người có thể không vừa 1 phòng.");
  });

  it("translates provider failures with the provider's Vietnamese name", () => {
    expect(translateWarning("Hotel provider timed out; its offers were omitted.")).toBe(
      "Nhà cung cấp khách sạn quá thời gian chờ; bỏ qua các báo giá của nguồn này.",
    );
  });

  it("translates the attempt reason the orchestrator reports for a failed plan", () => {
    expect(translateWarning("no budget option")).toBe("Không có phương án ngân sách.");
  });

  it("translates cost-line notes from the budget", () => {
    expect(translateWarning("Free according to source.")).toBe("Nguồn ghi là miễn phí.");
    expect(
      translateWarning("Reference range from huetripo; assumed per person per meal; verify before travel."),
    ).toBe("Khoảng giá tham khảo từ huetripo; giả định mỗi người mỗi bữa; cần kiểm tra trước khi đi.");
  });

  it("returns an unmatched message unchanged, so a new backend warning still shows", () => {
    expect(translateWarning("Some brand new backend warning.")).toBe("Some brand new backend warning.");
  });

  it("does not translate an already Vietnamese message", () => {
    expect(translateWarning("Giá đã đổi từ 400.000 VND thành 450.000 VND; cần xác nhận lại.")).toBe(
      "Giá đã đổi từ 400.000 VND thành 450.000 VND; cần xác nhận lại.",
    );
  });
});

describe("translateWarnings", () => {
  it("drops repeats after translation", () => {
    expect(
      translateWarnings([
        "Opening hours require verification before the visit.",
        "Opening hours require verification before the visit.",
      ]),
    ).toEqual(["Giờ mở cửa cần xác minh trước khi đi."]);
  });
});
