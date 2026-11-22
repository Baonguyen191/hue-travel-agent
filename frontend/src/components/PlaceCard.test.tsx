import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { Place } from "../api/types";
import placeJson from "../test/fixtures/place-531787.json";
import { PlaceCard } from "./PlaceCard";

const place = placeJson as Place;

function renderCard(item: Place) {
  return render(
    <MemoryRouter>
      <PlaceCard place={item} />
    </MemoryRouter>,
  );
}

describe("PlaceCard", () => {
  it("shows the name, the Vietnamese category and a link to the detail page", () => {
    renderCard(place);

    expect(screen.getByRole("heading", { name: "Đại Nội Huế" })).toBeInTheDocument();
    expect(screen.getByText("Di tích")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Đại Nội Huế" })).toHaveAttribute("href", "/explore/huetripo%3A531787");
  });

  it("shows a photo named after the place from the photo endpoint", () => {
    renderCard(place);

    const photo = screen.getByRole("img", { name: "Đại Nội Huế" });
    expect(photo.getAttribute("src")).toMatch(/\?w=480$/);
  });

  it("shows rating, reference price with the unit caveat, and unverified hours", () => {
    renderCard(place);

    expect(screen.getByText("4,7/5 · 17 lượt")).toBeInTheDocument();
    expect(screen.getByText("200.000 ₫ (tham khảo, đơn vị chưa rõ)")).toBeInTheDocument();
    expect(screen.getByText("07:30-17:30 (chưa xác minh)")).toBeInTheDocument();
  });

  it("links to the source page in a new tab", () => {
    renderCard(place);

    const link = screen.getByRole("link", { name: "Trang nguồn" });
    expect(link).toHaveAttribute("href", place.source_url);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("says chưa có when there is no rating and no price", () => {
    renderCard({
      ...place,
      rating_value: null,
      rating_count: null,
      price_status: "UNKNOWN",
      price_min_vnd: null,
      price_max_vnd: null,
      opening_hours_raw: null,
      opening_hours_confidence: "UNKNOWN",
      source_url: null,
    });

    expect(screen.getByText("chưa có")).toBeInTheDocument();
    expect(screen.getByText("giá chưa rõ")).toBeInTheDocument();
    expect(screen.getByText("chưa có thông tin (chưa rõ)")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Trang nguồn" })).not.toBeInTheDocument();
  });

  it("shows a free claim as the source's claim, not as a verified free entry", () => {
    renderCard({ ...place, price_status: "FREE_CLAIM", price_min_vnd: null, price_max_vnd: null, is_free_claim: true });

    expect(screen.getByText("miễn phí theo nguồn")).toBeInTheDocument();
  });
});
