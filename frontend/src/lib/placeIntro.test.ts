import { describe, expect, it } from "vitest";
import type { Place } from "../api/types";
import placeJson from "../test/fixtures/place-531787.json";
import {
  clip,
  distanceKm,
  factualParagraph,
  firstSentence,
  highlights,
  introTeaser,
  placeNote,
  placePhone,
  ratingScore,
  ratingWord,
  splitParagraphs,
} from "./placeIntro";

const place = placeJson as Place;

const noData: Place = {
  ...place,
  category: "attraction",
  address: null,
  rating_value: null,
  rating_count: null,
  rating_source: null,
  opening_hours_raw: null,
  visit_minutes: null,
  price_min_vnd: null,
  price_max_vnd: null,
  price_status: "UNKNOWN",
  is_free_claim: false,
};

describe("factualParagraph", () => {
  it("builds the paragraph from all the data", () => {
    expect(factualParagraph(place)).toBe(
      "Đại Nội Huế là di tích ở Đường 23 tháng 8, Phường Phú Xuân, Thành phố Huế. " +
        "Nơi này được đánh giá 4,7/5 với 17 lượt trên Google. " +
        "Thời gian tham quan trung bình khoảng 150 phút, giá tham khảo 200.000 ₫ (đơn vị chưa rõ). " +
        "Giờ mở cửa theo nguồn: 07:30-17:30.",
    );
  });

  it("omits the rating clause when there is no rating", () => {
    const text = factualParagraph({ ...place, rating_value: null, rating_count: null, rating_source: null });

    expect(text).not.toContain("đánh giá");
    expect(text).toContain("Đường 23 tháng 8");
  });

  it("omits the address clause when there is no address", () => {
    const text = factualParagraph({ ...place, address: null });

    expect(text.startsWith("Đại Nội Huế là di tích.")).toBe(true);
    expect(text).not.toContain("Đường 23");
  });

  it("says a free place is free according to the source", () => {
    const text = factualParagraph({
      ...place,
      price_status: "FREE_CLAIM",
      price_min_vnd: null,
      price_max_vnd: null,
      is_free_claim: true,
    });

    expect(text).toContain("Thời gian tham quan trung bình khoảng 150 phút, miễn phí theo nguồn.");
    expect(text).not.toContain("tham khảo");
  });

  it("gives a free place a sentence of its own when visit time is missing", () => {
    const text = factualParagraph({
      ...place,
      visit_minutes: null,
      price_status: "FREE_CLAIM",
      price_min_vnd: null,
      price_max_vnd: null,
    });

    expect(text).toContain("Miễn phí theo nguồn.");
  });

  it("gives a reference price with its unit caveat when visit time is missing", () => {
    const text = factualParagraph({ ...place, visit_minutes: null });

    expect(text).toContain("Giá tham khảo 200.000 ₫ (đơn vị chưa rõ).");
  });

  it("keeps the lower-case category and hours and omits what is missing", () => {
    const text = factualParagraph(noData);

    expect(text).toBe("Đại Nội Huế là điểm tham quan.");
    expect(text).not.toContain("Giờ mở cửa");
  });

  it("uses the address without a category label when the category is unknown", () => {
    const text = factualParagraph({ ...noData, category: "unknown_kind" as Place["category"], address: "Số 1 đường X" });

    expect(text).toBe("Đại Nội Huế nằm ở Số 1 đường X.");
  });
});

describe("placeNote", () => {
  it("names unverified hours and reference prices in one line", () => {
    expect(placeNote(place)).toBe(
      "Giờ mở cửa và giá lấy từ nguồn, chưa được xác minh; đơn vị giá chưa rõ, nên kiểm tra trước khi đi.",
    );
  });

  it("names only unverified hours when the price is not a reference range", () => {
    expect(placeNote({ ...place, price_status: "UNKNOWN", price_min_vnd: null, price_max_vnd: null })).toBe(
      "Giờ mở cửa lấy từ nguồn, chưa được xác minh.",
    );
  });

  it("keeps the free-claim caveat", () => {
    expect(placeNote({ ...place, opening_hours_confidence: "UNKNOWN", price_status: "FREE_CLAIM" })).toBe(
      "Nguồn ghi là miễn phí; chưa kiểm chứng.",
    );
  });

  it("returns null when the source needs no caveat", () => {
    expect(placeNote({ ...place, opening_hours_confidence: "UNKNOWN", price_status: "UNKNOWN" })).toBeNull();
  });
});

describe("placePhone", () => {
  it("returns the number as shown and as a dialable string, with the owner as a note", () => {
    expect(placePhone(place)).toEqual({
      display: "0234 3523 237",
      tel: "0234 3523 237".replace(/\s/g, ""),
      note: "Đơn vị quản lý (Trung tâm Bảo tồn Di tích Cố đô Huế)",
    });
  });

  it("returns null when the source has no phone", () => {
    expect(placePhone({ ...place, raw_attributes: { "Địa chỉ": "x" } })).toBeNull();
  });
});

describe("splitParagraphs", () => {
  it("splits on line breaks and drops blank lines", () => {
    expect(splitParagraphs("  Một.\n\n Hai.\r\nBa.  \n")).toEqual(["Một.", "Hai.", "Ba."]);
  });
});

describe("ratingWord and ratingScore", () => {
  it("labels scores by the agreed bands", () => {
    expect(ratingWord(4.8)).toBe("Tuyệt vời");
    expect(ratingWord(4.5)).toBe("Tuyệt vời");
    expect(ratingWord(4.2)).toBe("Rất tốt");
    expect(ratingWord(3.5)).toBe("Tốt");
    expect(ratingWord(3.0)).toBe("Khá");
    expect(ratingWord(2.9)).toBe("Trung bình");
  });

  it("shows the score with a decimal comma", () => {
    expect(ratingScore(4.7)).toBe("4,7");
    expect(ratingScore(5)).toBe("5,0");
  });
});

describe("distanceKm", () => {
  it("is zero for the same point and about 11.1 km for 0.1 degree of latitude", () => {
    expect(distanceKm(16.4698, 107.5786, 16.4698, 107.5786)).toBe(0);
    expect(distanceKm(16.5698, 107.5786, 16.4698, 107.5786)).toBeCloseTo(11.12, 1);
  });
});

describe("clip and firstSentence", () => {
  it("keeps short text whole and cuts long text at a word with an ellipsis", () => {
    expect(clip("ngắn gọn", 140)).toBe("ngắn gọn");
    const cut = clip("chữ ".repeat(60), 140);
    expect(cut.endsWith("…")).toBe(true);
    expect(cut.length).toBeLessThanOrEqual(141);
    expect(cut).not.toMatch(/\s…$/);
  });

  it("takes the first sentence and leaves decimals alone", () => {
    expect(firstSentence("Đại Nội đánh giá 4.7 sao. Câu hai.")).toBe("Đại Nội đánh giá 4.7 sao.");
    expect(firstSentence("không có dấu chấm")).toBe("không có dấu chấm");
  });
});

describe("highlights", () => {
  it("builds all five bullets from the fixture, in order", () => {
    expect(highlights(place)).toEqual([
      "Đại Nội Huế là quần thể cung điện nằm trong Kinh thành Huế, từng là nơi ở và làm việc của các vua triều Nguyễn.",
      "Ngay trung tâm Huế",
      "Giá tham khảo 200.000 ₫ (đơn vị chưa rõ)",
      "Mở cửa 07:30-17:30 (chưa xác minh)",
      "Nên dành khoảng 150 phút",
    ]);
  });

  it("gives the distance from the centre when the place is more than a kilometre away", () => {
    expect(highlights({ ...place, lat: 16.5698 })[1]).toBe("Cách trung tâm Huế khoảng 11,1 km");
  });

  it("says a free place is free according to the source", () => {
    const items = highlights({ ...place, price_status: "FREE_CLAIM", price_min_vnd: null, price_max_vnd: null });
    expect(items).toContain("Miễn phí theo nguồn");
    expect(items.some((item) => item.startsWith("Giá tham khảo"))).toBe(false);
  });

  it("omits the price bullet when the price is unknown", () => {
    const items = highlights({ ...place, price_status: "UNKNOWN", price_min_vnd: null, price_max_vnd: null });
    expect(items.some((item) => item.includes("giá") || item.includes("Giá") || item.includes("Miễn phí"))).toBe(false);
  });

  it("gives the hours bullet with the unverified caveat only when hours are known", () => {
    expect(highlights({ ...place, opening_hours_raw: null })).not.toContainEqual(expect.stringContaining("Mở cửa"));
    expect(highlights(place)).toContain("Mở cửa 07:30-17:30 (chưa xác minh)");
  });

  it("leaves out the visit bullet for a food place and when visit time is missing", () => {
    expect(highlights({ ...place, category: "cafe" })).not.toContainEqual(expect.stringContaining("Nên dành"));
    expect(highlights({ ...place, visit_minutes: null })).not.toContainEqual(expect.stringContaining("Nên dành"));
  });

  it("takes the article's first sentence, or the summary's when there is no guide", () => {
    expect(highlights({ ...place, guide: null })[0]).toBe(
      "Đại Nội Huế từng là trung tâm chính trị, văn hóa và là nơi sinh hoạt của 13 vị vua triều Nguyễn trong suốt 143 năm.",
    );
  });

  it("cuts a long first sentence at a word with an ellipsis", () => {
    const long = { ...place, guide: { ...place.guide!, text: "Chữ ".repeat(60) } };
    const first = highlights(long)[0];
    expect(first.endsWith("…")).toBe(true);
    expect(first.length).toBeLessThanOrEqual(141);
  });

  it("returns only the distance bullet when no other data is present", () => {
    const bare: Place = {
      ...place,
      guide: null,
      summary: null,
      price_status: "UNKNOWN",
      price_min_vnd: null,
      price_max_vnd: null,
      opening_hours_raw: null,
      visit_minutes: null,
    };
    expect(highlights(bare)).toEqual(["Ngay trung tâm Huế"]);
  });
});

describe("introTeaser", () => {
  it("cuts the lead to about 120 characters with an ellipsis", () => {
    const teaser = introTeaser(place);
    expect(teaser.startsWith("Đại Nội Huế là quần thể cung điện")).toBe(true);
    expect(teaser.endsWith("…")).toBe(true);
    expect(teaser.length).toBeLessThanOrEqual(121);
  });

  it("uses the summary, then the factual paragraph, when there is no guide", () => {
    expect(introTeaser({ ...place, guide: null })).toMatch(/^Đại Nội Huế từng là trung tâm/);
    expect(introTeaser({ ...place, guide: null, summary: null })).toMatch(/^Đại Nội Huế là di tích/);
  });
});
