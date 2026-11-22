import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "../App";
import type { PlanRecord } from "../api/types";
import { eventKindLabel } from "../lib/plan";
import { routeFetch } from "../test/fetchMock";
import planJson from "../test/fixtures/plan.json";
import { heroPoi } from "./PlanLayout";

const THREAD = "e3d7c6b9-956b-42f7-9916-479fe993c969";
const record = planJson as unknown as PlanRecord;

function renderPlan() {
  return render(
    <MemoryRouter initialEntries={[`/plan/${THREAD}`]}>
      <App />
    </MemoryRouter>,
  );
}

function withoutPoiIds(source: PlanRecord): PlanRecord {
  return {
    ...source,
    payload: {
      ...source.payload,
      itinerary: {
        ...source.payload.itinerary,
        days: source.payload.itinerary.days.map((day) => ({
          ...day,
          events: day.events.map((event) => ({ ...event, poi_id: null })),
        })),
      },
    },
  };
}

describe("heroPoi", () => {
  it("returns the first VISIT with a poi_id across the days", () => {
    expect(heroPoi(record)).toEqual({ poiId: "huetripo:531787", name: "Đại Nội Huế", category: "historic" });
  });

  it("returns null when no event has a poi_id", () => {
    expect(heroPoi(withoutPoiIds(record))).toBeNull();
  });
});

describe("itinerary tab", () => {
  beforeEach(() => {
    window.localStorage.setItem("hue.userId", "tester-0003");
  });

  it("shows a photo named after each VISIT stop with a poi_id", async () => {
    routeFetch(() => ({ body: planJson }));
    renderPlan();
    await screen.findByRole("heading", { level: 1 });

    const panel = screen.getByRole("tabpanel");
    const visits = record.payload.itinerary.days[0].events.filter((event) => event.kind === "VISIT" && event.poi_id);
    expect(visits.length).toBeGreaterThan(0);
    for (const event of visits) {
      const photo = within(panel).getByRole("img", { name: event.name });
      expect(photo.getAttribute("src")).toMatch(/\?w=480$/);
    }
  });

  it("shows a break without poi_id with its kind label and no photo", async () => {
    const base = record.payload.itinerary;
    const breakEvent = { ...base.days[0].events[0], kind: "MEAL_BREAK" as const, poi_id: null, name: "Nghỉ giải lao", category: null };
    const custom: PlanRecord = {
      ...record,
      payload: { ...record.payload, itinerary: { ...base, days: [{ ...base.days[0], events: [breakEvent] }] } },
    };
    routeFetch(() => ({ body: custom }));
    renderPlan();
    await screen.findByRole("heading", { level: 1 });

    const panel = screen.getByRole("tabpanel");
    expect(within(panel).queryByRole("img")).not.toBeInTheDocument();
    expect(within(panel).getByText(eventKindLabel(breakEvent))).toBeInTheDocument();
    expect(within(panel).getByText("Nghỉ giải lao")).toBeInTheDocument();
  });

  it("keeps the day tabs as role=tab with aria-selected", async () => {
    routeFetch(() => ({ body: planJson }));
    renderPlan();
    await screen.findByRole("heading", { level: 1 });

    const tabs = screen.getAllByRole("tab");
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    await userEvent.click(tabs[1]);
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    expect(tabs[0]).toHaveAttribute("aria-selected", "false");
  });
});
