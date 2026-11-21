import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { Place } from "../api/types";
import placeJson from "../test/fixtures/place-531787.json";
import { PlacesMap } from "./PlacesMap";

const place = placeJson as Place;

describe("PlacesMap", () => {
  it("renders a labelled map region with OpenStreetMap attribution", () => {
    render(
      <MemoryRouter>
        <PlacesMap places={[place]} />
      </MemoryRouter>,
    );

    expect(screen.getByRole("region", { name: "Bản đồ địa điểm" })).toBeInTheDocument();
    expect(document.querySelector(".leaflet-container")).not.toBeNull();
    expect(document.querySelector(".leaflet-control-attribution")).toHaveTextContent("OpenStreetMap");
  });

  it("lists a legend entry only for the categories on the map", () => {
    render(
      <MemoryRouter>
        <PlacesMap places={[place]} />
      </MemoryRouter>,
    );

    const legend = screen.getByRole("list", { name: "Chú giải bản đồ" });
    expect(legend).toHaveTextContent("Di tích");
    expect(legend).not.toHaveTextContent("Quán ăn");
  });

  it("omits the legend when there are no places", () => {
    render(
      <MemoryRouter>
        <PlacesMap places={[]} />
      </MemoryRouter>,
    );

    expect(screen.queryByRole("list", { name: "Chú giải bản đồ" })).not.toBeInTheDocument();
  });
});
