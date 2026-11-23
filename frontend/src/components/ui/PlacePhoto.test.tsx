import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Place } from "../../api/types";
import placeJson from "../../test/fixtures/place-531787.json";
import { PlacePhoto, isIllustrative, photoUrl } from ".";

describe("PlacePhoto", () => {
  it("builds the proxy URL for each size", () => {
    expect(photoUrl("huetripo:531787", "sm")).toBe("/api/v1/places/huetripo%3A531787/photo?w=160");
    expect(photoUrl("huetripo:531787", "md")).toBe("/api/v1/places/huetripo%3A531787/photo?w=480");
    expect(photoUrl("huetripo:531787", "lg")).toBe("/api/v1/places/huetripo%3A531787/photo?w=960");
  });

  it("renders a lazy image with the place name as alt text", () => {
    render(<PlacePhoto poiId="huetripo:1" name="Đại Nội Huế" category="historic" size="md" />);
    const image = screen.getByRole("img", { name: "Đại Nội Huế" });
    expect(image).toHaveAttribute("src", "/api/v1/places/huetripo%3A1/photo?w=480");
    expect(image).toHaveAttribute("loading", "lazy");
  });

  it("swaps to the category illustration when the image fails", () => {
    render(<PlacePhoto poiId="huetripo:1" name="Đại Nội Huế" category="historic" size="sm" />);
    fireEvent.error(screen.getByRole("img", { name: "Đại Nội Huế" }));
    expect(screen.queryByRole("img", { name: "Đại Nội Huế" })).not.toBeInTheDocument();
    expect(screen.getByTestId("place-illustration")).toHaveAttribute("data-category", "historic");
    expect(screen.getByText("Đại Nội Huế")).toHaveClass("sr-only");
  });

  it("shows the illustration straight away without a poi id", () => {
    render(<PlacePhoto poiId={null} name="Nghỉ trưa" category={null} size="sm" />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByTestId("place-illustration")).toHaveAttribute("data-category", "default");
  });

  it("labels the real image as an illustrative photo when asked", () => {
    render(<PlacePhoto poiId="huetripo:1" name="Bún bò" category="restaurant" size="md" illustrative />);
    expect(screen.getByText("Ảnh minh hoạ")).toHaveClass("absolute", "right-2", "top-2");
  });

  it("does not show the illustrative badge by default", () => {
    render(<PlacePhoto poiId="huetripo:1" name="Đại Nội Huế" category="historic" size="md" />);
    expect(screen.queryByText("Ảnh minh hoạ")).not.toBeInTheDocument();
  });

  it("hides the illustrative badge once the image fails and the illustration shows", () => {
    render(<PlacePhoto poiId="huetripo:1" name="Bún bò" category="restaurant" size="md" illustrative />);
    fireEvent.error(screen.getByRole("img", { name: "Bún bò" }));
    expect(screen.queryByText("Ảnh minh hoạ")).not.toBeInTheDocument();
    expect(screen.getByTestId("place-illustration")).toBeInTheDocument();
  });

  it("fills the full width at fixed heights for the banner aspect", () => {
    render(<PlacePhoto poiId="huetripo:1" name="Banner" category="historic" size="lg" aspect="banner" />);
    const wrapper = screen.getByRole("img", { name: "Banner" }).parentElement;
    expect(wrapper).toHaveClass("h-48", "w-full");
    expect(wrapper).not.toHaveClass("aspect-video");
  });
});

describe("isIllustrative", () => {
  const place = placeJson as Place;

  it("is true only for a generic Commons picture of the category", () => {
    expect(isIllustrative({ photo: { url: "/x", kind: "commons_illustrative", author: null, license: null, credit_url: null } })).toBe(true);
    expect(isIllustrative({ photo: { url: "/x", kind: "commons_place", author: null, license: null, credit_url: null } })).toBe(false);
    expect(isIllustrative({ photo: { url: "/x", kind: "source", author: null, license: null, credit_url: null } })).toBe(false);
    expect(isIllustrative({ photo: null })).toBe(false);
    expect(isIllustrative(place)).toBe(false);
  });
});
