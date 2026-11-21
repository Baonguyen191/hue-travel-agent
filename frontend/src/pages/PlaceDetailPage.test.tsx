import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Place } from "../api/types";
import placeJson from "../test/fixtures/place-531787.json";
import { calledUrls, routeFetch } from "../test/fetchMock";
import { PlaceDetailPage, placeWarnings } from "./PlaceDetailPage";

vi.mock("../components/PlacesMap", async () => {
  const { createElement } = await import("react");
  return {
    PlacesMap: ({ places }: { places: unknown[] }) => createElement("div", { "data-testid": "map" }, `${places.length}`),
  };
});

const place = placeJson as Place;

function renderDetail(poiId: string) {
  return render(
    <MemoryRouter initialEntries={[`/explore/${encodeURIComponent(poiId)}`]}>
      <Routes>
        <Route path="/explore/:poiId" element={<PlaceDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("PlaceDetailPage", () => {
  it("loads the POI by id and shows its normalized fields", async () => {
    const fetchMock = routeFetch(() => ({ body: place }));
    renderDetail("huetripo:531787");

    expect(await screen.findByRole("heading", { level: 1, name: "Đại Nội Huế" })).toBeInTheDocument();
    expect(calledUrls(fetchMock)).toEqual(["/api/v1/places/huetripo%3A531787"]);
    // The address appears in the header and again in the raw attributes table.
    expect(screen.getAllByText("Đường 23 tháng 8, Phường Phú Xuân, Thành phố Huế").length).toBeGreaterThan(1);
    expect(screen.getByText("200.000 ₫ (tham khảo, đơn vị chưa rõ)")).toBeInTheDocument();
    expect(screen.getByText("150 phút")).toBeInTheDocument();
    expect(screen.getByText("16.46918, 107.57835")).toBeInTheDocument();
    expect(screen.getByText("4,7/5 · 17 lượt (Google)")).toBeInTheDocument();
  });

  it("always shows the data warnings panel", async () => {
    routeFetch(() => ({ body: place }));
    renderDetail("huetripo:531787");

    const panel = await screen.findByRole("region", { name: "Cảnh báo về dữ liệu" });
    expect(panel).toHaveTextContent("Giờ mở cửa lấy từ nguồn và chưa được xác minh.");
    expect(panel).toHaveTextContent("đơn vị chưa rõ");
  });

  it("lists every raw source attribute and links to the source page", async () => {
    routeFetch(() => ({ body: place }));
    renderDetail("huetripo:531787");

    expect(await screen.findByRole("cell", { name: /Đường 23 tháng 8/ })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "Điện thoại" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Mở trang nguồn" })).toHaveAttribute("href", place.source_url);
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

describe("placeWarnings", () => {
  it("flags a missing rating and missing hours and keeps the unit caveat", () => {
    const warnings = placeWarnings({
      ...place,
      rating_value: null,
      rating_count: null,
      opening_hours_raw: null,
      opening_hours_confidence: "UNKNOWN",
      price_status: "UNKNOWN",
      price_min_vnd: null,
      price_max_vnd: null,
    });

    expect(warnings).toEqual(["Nguồn không có giờ mở cửa.", "Chưa có thông tin giá.", "Chưa có đánh giá."]);
  });

  it("warns that a free claim is unverified", () => {
    const warnings = placeWarnings({ ...place, price_status: "FREE_CLAIM", price_min_vnd: null, price_max_vnd: null });

    expect(warnings).toContain("Nguồn ghi là miễn phí; chưa kiểm chứng.");
  });
});
