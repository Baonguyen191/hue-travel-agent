import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PlacePhoto, photoUrl } from ".";

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
});
