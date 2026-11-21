import { describe, expect, it } from "vitest";
import {
  describePrice,
  describeRating,
  formatDate,
  formatKm,
  formatMinutes,
  formatTime,
  formatVnd,
  formatVndRange,
} from "./format";

describe("formatVnd", () => {
  it("groups thousands with dots and adds the dong sign", () => {
    expect(formatVnd(1250000)).toBe("1.250.000 ₫");
    expect(formatVnd(8000000)).toBe("8.000.000 ₫");
    expect(formatVnd(0)).toBe("0 ₫");
    expect(formatVnd(450)).toBe("450 ₫");
  });

  it("shows an unknown amount as unknown, never as zero", () => {
    expect(formatVnd(null)).toBe("chưa rõ");
    expect(formatVnd(undefined)).toBe("chưa rõ");
  });
});

describe("formatVndRange", () => {
  it("renders a range with an en dash", () => {
    expect(formatVndRange(200000, 300000)).toBe("200.000 – 300.000 ₫");
  });

  it("collapses equal or one-sided bounds into one amount", () => {
    expect(formatVndRange(200000, 200000)).toBe("200.000 ₫");
    expect(formatVndRange(200000, null)).toBe("200.000 ₫");
    expect(formatVndRange(null, 300000)).toBe("300.000 ₫");
  });

  it("returns unknown when both bounds are missing", () => {
    expect(formatVndRange(null, null)).toBe("chưa rõ");
  });
});

describe("formatTime", () => {
  it("reads HH:mm from naive local times without shifting them", () => {
    expect(formatTime("2026-12-05T08:01:00")).toBe("08:01");
    expect(formatTime("2026-12-05T23:59:00")).toBe("23:59");
  });

  it("keeps the wall-clock time even when an offset is present", () => {
    expect(formatTime("2026-12-05T08:01:00+07:00")).toBe("08:01");
  });

  it("returns a dash for missing or malformed input", () => {
    expect(formatTime(null)).toBe("—");
    expect(formatTime("not a time")).toBe("—");
  });
});

describe("formatDate", () => {
  it("turns ISO dates into dd/mm/yyyy", () => {
    expect(formatDate("2026-12-05")).toBe("05/12/2026");
  });

  it("returns unparseable input unchanged", () => {
    expect(formatDate("tuần sau")).toBe("tuần sau");
    expect(formatDate(null)).toBe("—");
  });
});

describe("formatKm and formatMinutes", () => {
  it("uses a decimal comma and the km unit", () => {
    expect(formatKm(1.249)).toBe("1,2 km");
    expect(formatKm(0)).toBe("0,0 km");
    expect(formatKm(null)).toBe("—");
  });

  it("formats minutes", () => {
    expect(formatMinutes(4)).toBe("4 phút");
    expect(formatMinutes(null)).toBe("—");
  });
});

describe("describePrice", () => {
  it("labels a reference range with the unit caveat", () => {
    expect(
      describePrice({ price_status: "REFERENCE_RANGE", price_min_vnd: 200000, price_max_vnd: 200000 }),
    ).toBe("200.000 ₫ (tham khảo, đơn vị chưa rõ)");
    expect(
      describePrice({ price_status: "REFERENCE_RANGE", price_min_vnd: 50000, price_max_vnd: 120000 }),
    ).toBe("50.000 – 120.000 ₫ (tham khảo, đơn vị chưa rõ)");
  });

  it("reports a free claim as the source's claim", () => {
    expect(describePrice({ price_status: "FREE_CLAIM", price_min_vnd: null, price_max_vnd: null })).toBe(
      "miễn phí theo nguồn",
    );
  });

  it("says the price is unknown when there is nothing to show", () => {
    expect(describePrice({ price_status: "UNKNOWN", price_min_vnd: null, price_max_vnd: null })).toBe("giá chưa rõ");
    expect(describePrice({ price_status: "REFERENCE_RANGE", price_min_vnd: null, price_max_vnd: null })).toBe(
      "giá chưa rõ",
    );
  });
});

describe("describeRating", () => {
  it("shows value and count", () => {
    expect(describeRating(4.7, 17)).toBe("4,7/5 · 17 lượt");
  });

  it("says no rating when there is none", () => {
    expect(describeRating(null, null)).toBe("chưa có");
  });
});
