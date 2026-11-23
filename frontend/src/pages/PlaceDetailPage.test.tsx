import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Place } from "../api/types";
import placeJson from "../test/fixtures/place-531787.json";
import { calledUrls, routeFetch } from "../test/fetchMock";
import { PlaceDetailPage, askAssistantText } from "./PlaceDetailPage";

vi.mock("../components/PlacesMap", async () => {
  const { createElement } = await import("react");
  return {
    PlacesMap: ({ places }: { places: unknown[] }) => createElement("div", { "data-testid": "map" }, `${places.length}`),
  };
});

const place = placeJson as Place;

function LocationProbe() {
  return <p data-testid="probe">{JSON.stringify(useLocation().state)}</p>;
}

function renderDetail(poiId: string) {
  return render(
    <MemoryRouter initialEntries={[`/explore/${encodeURIComponent(poiId)}`]}>
      <Routes>
        <Route path="/explore/:poiId" element={<PlaceDetailPage />} />
        <Route path="/" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** The "Thông tin hữu ích" section (its rows are inside an open details element). */
function infoCard() {
  return screen.getByRole("heading", { name: "Thông tin hữu ích" }).closest("section") as HTMLElement;
}

function introCard() {
  return screen.getByRole("heading", { level: 2, name: "Giới thiệu" }).closest("section") as HTMLElement;
}

/** The article text of "Giới thiệu". It sits in a closed details element, so role queries need hidden: true. */
function introBody() {
  return within(introCard()).getByTestId("intro-body");
}

function ratingCard() {
  return screen.queryByRole("region", { name: "Đánh giá" });
}

function highlightItems(): string[] {
  const section = screen.getByRole("heading", { name: "Điểm nổi bật" }).closest("section") as HTMLElement;
  return within(section)
    .getAllByRole("listitem")
    .map((item) => item.textContent ?? "");
}

describe("PlaceDetailPage", () => {
  it("loads the POI by id and shows its main info", async () => {
    const fetchMock = routeFetch(() => ({ body: place }));
    renderDetail("huetripo:531787");

    expect(await screen.findByRole("heading", { level: 1, name: "Đại Nội Huế" })).toBeInTheDocument();
    expect(calledUrls(fetchMock)).toEqual(["/api/v1/places/huetripo%3A531787"]);
    const card = infoCard();
    expect(within(card).getByText("Đường 23 tháng 8, Phường Phú Xuân, Thành phố Huế")).toBeInTheDocument();
    expect(within(card).getByText("07:30-17:30 (chưa xác minh)")).toBeInTheDocument();
    expect(within(card).getByText("200.000 ₫ (tham khảo, đơn vị chưa rõ)")).toBeInTheDocument();
    expect(within(card).getByText("150 phút")).toBeInTheDocument();
    expect(screen.getByTestId("map")).toBeInTheDocument();
  });

  it("shows the rating score, its word and the review count in a card", async () => {
    routeFetch(() => ({ body: place }));
    renderDetail("huetripo:531787");

    await screen.findByRole("heading", { level: 1, name: "Đại Nội Huế" });
    const card = ratingCard() as HTMLElement;
    expect(card).toBeInTheDocument();
    expect(within(card).getByText("4,7")).toBeInTheDocument();
    expect(within(card).getByText("/5")).toBeInTheDocument();
    expect(within(card).getByText("Tuyệt vời")).toBeInTheDocument();
    expect(within(card).getByText("17 lượt đánh giá trên Google")).toBeInTheDocument();
  });

  it("shows no rating card when the place has no rating", async () => {
    routeFetch(() => ({ body: { ...place, rating_value: null, rating_count: null, rating_source: null } }));
    renderDetail("huetripo:531787");

    await screen.findByRole("heading", { level: 1, name: "Đại Nội Huế" });
    expect(ratingCard()).not.toBeInTheDocument();
  });

  it("lists highlight bullets built from the article, the location, the price, the hours and the visit time", async () => {
    routeFetch(() => ({ body: place }));
    renderDetail("huetripo:531787");

    await screen.findByRole("heading", { level: 1, name: "Đại Nội Huế" });
    expect(highlightItems()).toEqual([
      "Đại Nội Huế là quần thể cung điện nằm trong Kinh thành Huế, từng là nơi ở và làm việc của các vua triều Nguyễn.",
      "Ngay trung tâm Huế",
      "Giá tham khảo 200.000 ₫ (đơn vị chưa rõ)",
      "Mở cửa 07:30-17:30 (chưa xác minh)",
      "Nên dành khoảng 150 phút",
    ]);
  });

  it("opens the useful-info section by default and keeps the introduction closed", async () => {
    routeFetch(() => ({ body: place }));
    renderDetail("huetripo:531787");

    await screen.findByRole("heading", { level: 1, name: "Đại Nội Huế" });
    const info = screen.getByRole("heading", { name: "Thông tin hữu ích" }).closest("details") as HTMLElement;
    const intro = screen.getByRole("heading", { level: 2, name: "Giới thiệu" }).closest("details") as HTMLElement;
    expect(info).toHaveAttribute("open");
    expect(intro).not.toHaveAttribute("open");
  });

  it("shows the phone as a tel link and keeps the owner as a note", async () => {
    routeFetch(() => ({ body: place }));
    renderDetail("huetripo:531787");

    const link = await screen.findByRole("link", { name: "0234 3523 237" });
    expect(link).toHaveAttribute("href", "tel:02343523237");
    expect(within(infoCard()).getByText(/Đơn vị quản lý/)).toBeInTheDocument();
  });

  it("hides info rows and highlights the source has no data for", async () => {
    routeFetch(() => ({
      body: {
        ...place,
        address: null,
        rating_value: null,
        rating_count: null,
        rating_source: null,
        opening_hours_raw: null,
        price_status: "UNKNOWN",
        price_min_vnd: null,
        price_max_vnd: null,
        visit_minutes: null,
        guide: null,
        summary: null,
        raw_attributes: {},
      },
    }));
    renderDetail("huetripo:531787");

    await screen.findByRole("heading", { level: 1, name: "Đại Nội Huế" });
    const card = infoCard();
    for (const label of ["Địa chỉ", "Giờ mở cửa", "Giá", "Thời gian tham quan", "Điện thoại"]) {
      expect(within(card).queryByText(label)).not.toBeInTheDocument();
    }
    expect(ratingCard()).not.toBeInTheDocument();
    expect(highlightItems()).toEqual(["Ngay trung tâm Huế"]);
  });

  it("shows one compact note instead of the warnings panel", async () => {
    routeFetch(() => ({ body: place }));
    renderDetail("huetripo:531787");

    const note = await screen.findByText(/Giờ mở cửa và giá lấy từ nguồn, chưa được xác minh/);
    expect(note.tagName).toBe("P");
    expect(note).toHaveTextContent("đơn vị giá chưa rõ");
    expect(screen.queryByRole("region", { name: "Cảnh báo về dữ liệu" })).not.toBeInTheDocument();
  });

  it("removes the technical rows and the raw attributes table", async () => {
    routeFetch(() => ({ body: place }));
    renderDetail("huetripo:531787");

    await screen.findByRole("heading", { level: 1, name: "Đại Nội Huế" });
    expect(screen.queryByText("Tọa độ")).not.toBeInTheDocument();
    expect(screen.queryByText("16.46918, 107.57835")).not.toBeInTheDocument();
    expect(screen.queryByText("Mã trong nguồn")).not.toBeInTheDocument();
    expect(screen.queryByText("Thu thập lúc")).not.toBeInTheDocument();
    expect(screen.queryByText("Thuộc tính gốc từ nguồn")).not.toBeInTheDocument();
    expect(screen.queryByText("Loại hình (theo nguồn)")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Giới thiệu từ nguồn" })).not.toBeInTheDocument();
  });

  it("keeps a footer line with the source link", async () => {
    routeFetch(() => ({ body: place }));
    renderDetail("huetripo:531787");

    await screen.findByRole("heading", { level: 1, name: "Đại Nội Huế" });
    expect(screen.getByText(/^Dữ liệu: huetripo\.hue\.gov\.vn/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Mở trang nguồn" })).toHaveAttribute("href", place.source_url);
  });

  it("sends the user to the chat with a prefilled question about this place", async () => {
    routeFetch(() => ({ body: place }));
    renderDetail("huetripo:531787");

    await userEvent.click(await screen.findByRole("link", { name: "Hỏi trợ lý về nơi này" }));

    expect(screen.getByTestId("probe")).toHaveTextContent(JSON.stringify({ prefill: askAssistantText(place.name) }));
  });

  it("credits a Commons photo of the place with author, licence and a link", async () => {
    const withCommons: Place = {
      ...place,
      photo: {
        url: "/api/v1/places/huetripo%3A531787/photo?w=960",
        kind: "commons_place",
        author: "Nguyễn An",
        license: "CC BY-SA 4.0",
        credit_url: "https://commons.wikimedia.org/wiki/File:Dai_Noi.jpg",
      },
    };
    routeFetch(() => ({ body: withCommons }));
    renderDetail("huetripo:531787");

    await screen.findByRole("heading", { level: 1, name: "Đại Nội Huế" });
    const credit = screen.getByText(/^Ảnh: Nguyễn An/);
    expect(credit).toHaveTextContent("Ảnh: Nguyễn An · CC BY-SA 4.0 · Wikimedia Commons");
    expect(credit).not.toHaveTextContent("không phải ảnh của địa điểm này");
    const link = screen.getByRole("link", { name: "Wikimedia Commons" });
    expect(link).toHaveAttribute("href", "https://commons.wikimedia.org/wiki/File:Dai_Noi.jpg");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("says an illustrative Commons photo is not of this place", async () => {
    const illustrative: Place = {
      ...place,
      photo: {
        url: "/api/v1/places/huetripo%3A531787/photo?w=960",
        kind: "commons_illustrative",
        author: null,
        license: "CC0",
        credit_url: "https://commons.wikimedia.org/wiki/File:Bun_bo.jpg",
      },
    };
    routeFetch(() => ({ body: illustrative }));
    renderDetail("huetripo:531787");

    await screen.findByRole("heading", { level: 1, name: "Đại Nội Huế" });
    const credit = screen.getByText(/không phải ảnh của địa điểm này/);
    expect(credit).toHaveTextContent("Ảnh minh hoạ, không phải ảnh của địa điểm này. Ảnh: không rõ tác giả · CC0 · Wikimedia Commons");
    expect(screen.getByRole("link", { name: "Wikimedia Commons" })).toHaveAttribute(
      "href",
      "https://commons.wikimedia.org/wiki/File:Bun_bo.jpg",
    );
  });

  it("shows no photo credit for the source's own photo", async () => {
    routeFetch(() => ({ body: { ...place, photo: { url: "/x", kind: "source", author: null, license: null, credit_url: null } } }));
    renderDetail("huetripo:531787");

    await screen.findByRole("heading", { level: 1, name: "Đại Nội Huế" });
    expect(screen.queryByText(/^Ảnh:/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Wikimedia Commons" })).not.toBeInTheDocument();
  });

  it("says the POI is not in the source on 404", async () => {
    routeFetch(() => ({ status: 404, body: { detail: "POI was not found in the Hue source." } }));
    renderDetail("huetripo:0");

    expect(await screen.findByRole("heading", { name: "Không tìm thấy địa điểm" })).toBeInTheDocument();
  });

  it("shows other API errors with their detail", async () => {
    routeFetch(() => ({ status: 503, body: { detail: "Hue SQLite source file is unavailable." } }));
    renderDetail("huetripo:531787");

    expect(await screen.findByRole("alert")).toHaveTextContent("Hue SQLite source file is unavailable.");
  });
});

describe("PlaceDetailPage introduction", () => {
  it("shows the Wikipedia lead, section headings and paragraphs as text", async () => {
    routeFetch(() => ({ body: place }));
    renderDetail("huetripo:531787");

    await screen.findByRole("heading", { level: 2, name: "Giới thiệu" });
    const body = introBody();
    expect(within(body).getByText(/quần thể cung điện nằm trong Kinh thành Huế/)).toBeInTheDocument();
    expect(within(body).getByText(/Quần thể được UNESCO công nhận/)).toBeInTheDocument();
    expect(within(body).getByRole("heading", { level: 3, name: "Lịch sử", hidden: true })).toBeInTheDocument();
    expect(within(body).getByRole("heading", { level: 3, name: "Kiến trúc", hidden: true })).toBeInTheDocument();
    expect(within(body).getByText(/Kinh thành Huế được xây dựng từ năm 1805/)).toBeInTheDocument();
    expect(within(body).getByText(/cổng Ngọ Môn/)).toBeInTheDocument();
  });

  it("shows a one-line teaser under the closed summary", async () => {
    routeFetch(() => ({ body: place }));
    renderDetail("huetripo:531787");

    await screen.findByRole("heading", { level: 2, name: "Giới thiệu" });
    const summary = introCard().querySelector("summary") as HTMLElement;
    const teaser = within(summary).getByText(/^Đại Nội Huế là quần thể/);
    expect(teaser.textContent?.endsWith("…")).toBe(true);
    expect(teaser.textContent?.length).toBeLessThanOrEqual(121);
  });

  it("credits Vietnamese Wikipedia with the licence and a small link to the article", async () => {
    routeFetch(() => ({ body: place }));
    renderDetail("huetripo:531787");

    await screen.findByRole("heading", { level: 2, name: "Giới thiệu" });
    const body = introBody();
    expect(within(body).getByText(/Theo Wikipedia tiếng Việt \(CC BY-SA 4\.0\) ·/)).toBeInTheDocument();
    const link = within(body).getByRole("link", { name: "bài gốc", hidden: true });
    expect(link).toHaveAttribute("href", place.guide?.url);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("falls back to the huetripo summary when there is no guide", async () => {
    routeFetch(() => ({ body: { ...place, guide: null } }));
    renderDetail("huetripo:531787");

    await screen.findByRole("heading", { level: 2, name: "Giới thiệu" });
    const body = introBody();
    expect(within(body).getByText(/Đại Nội Huế từng là trung tâm chính trị/)).toBeInTheDocument();
    expect(within(body).getByText("Theo huetripo.hue.gov.vn")).toBeInTheDocument();
    expect(within(body).queryByText(/Wikipedia/)).not.toBeInTheDocument();
  });

  it("uses the factual paragraph alone when there is no guide and no summary", async () => {
    routeFetch(() => ({ body: { ...place, guide: null, summary: null } }));
    renderDetail("huetripo:531787");

    await screen.findByRole("heading", { level: 2, name: "Giới thiệu" });
    const body = introBody();
    expect(
      within(body).getByText(
        "Đại Nội Huế là di tích ở Đường 23 tháng 8, Phường Phú Xuân, Thành phố Huế. " +
          "Nơi này được đánh giá 4,7/5 với 17 lượt trên Google. " +
          "Thời gian tham quan trung bình khoảng 150 phút, giá tham khảo 200.000 ₫ (đơn vị chưa rõ). " +
          "Giờ mở cửa theo nguồn: 07:30-17:30.",
      ),
    ).toBeInTheDocument();
    expect(within(body).queryByText(/Theo huetripo/)).not.toBeInTheDocument();
    expect(within(body).queryByRole("heading", { level: 3, hidden: true })).not.toBeInTheDocument();
  });

  it("leaves out the factual paragraph when the Wikipedia article introduces the place", async () => {
    routeFetch(() => ({ body: place }));
    renderDetail("huetripo:531787");

    await screen.findByRole("heading", { level: 2, name: "Giới thiệu" });
    expect(within(introBody()).getByText(/quần thể cung điện nằm trong Kinh thành Huế/)).toBeInTheDocument();
    expect(within(introBody()).queryByText(/Nơi này được đánh giá/)).toBeNull();
  });

  it("leaves out the visit time for a restaurant", async () => {
    routeFetch(() => ({ body: { ...place, category: "restaurant" } }));
    renderDetail("huetripo:531787");

    await screen.findByRole("heading", { level: 1, name: "Đại Nội Huế" });
    expect(screen.queryByText("Thời gian tham quan")).not.toBeInTheDocument();
    expect(highlightItems()).not.toContain("Nên dành khoảng 150 phút");
  });

  it("does not show a visit time for a restaurant and marks a cut summary with an ellipsis", async () => {
    const { isFoodPlace, splitParagraphs } = await import("../lib/placeIntro");
    expect(isFoodPlace({ ...place, category: "restaurant" })).toBe(true);
    expect(isFoodPlace(place)).toBe(false);
    expect(splitParagraphs("rợp bóng thông già")).toEqual(["rợp bóng thông già…"]);
    expect(splitParagraphs("Câu đầy đủ.")).toEqual(["Câu đầy đủ."]);
  });
});
