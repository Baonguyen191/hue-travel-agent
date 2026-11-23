import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "../App";
import type { PlanRecord } from "../api/types";
import { eventKindLabel, travelLegText } from "../lib/plan";
import { routeFetch } from "../test/fetchMock";
import planJson from "../test/fixtures/plan.json";
import slotsJson from "../test/fixtures/plan-slots.json";
import { heroPoi } from "./PlanLayout";

const THREAD = "e3d7c6b9-956b-42f7-9916-479fe993c969";
const record = planJson as unknown as PlanRecord;
const slotsRecord = slotsJson as unknown as PlanRecord;
const outboundLeg = slotsRecord.payload.itinerary.travel_legs![0];
const returnLeg = slotsRecord.payload.itinerary.travel_legs![1];

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

describe("itinerary slots, reasons, rest rows and travel legs", () => {
  beforeEach(() => {
    window.localStorage.setItem("hue.userId", "tester-0003");
  });

  it("shows the slot label of each stop on day 1", async () => {
    routeFetch(() => ({ body: slotsJson }));
    renderPlan();
    await screen.findByRole("heading", { level: 1 });

    const panel = screen.getByRole("tabpanel");
    // "Cà phê" is also the category chip of the café stop, so look for the kim-soft slot pill specifically.
    for (const label of ["Sáng", "Trưa", "Chiều", "Cà phê", "Hoàng hôn", "Tối"]) {
      const pills = within(panel).getAllByText(label).filter((element) => element.className.includes("bg-kim-soft"));
      expect(pills).toHaveLength(1);
    }
  });

  it("shows the reason as a muted line under the place name", async () => {
    routeFetch(() => ({ body: slotsJson }));
    renderPlan();
    await screen.findByRole("heading", { level: 1 });

    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByText("Lý do: hợp sở thích di tích")).toHaveClass("text-muc-soft");
  });

  it("shows the guide intro only on the event that has one", async () => {
    routeFetch(() => ({ body: slotsJson }));
    renderPlan();
    await screen.findByRole("heading", { level: 1 });

    const panel = screen.getByRole("tabpanel");
    const intro = within(panel).getByText("Từng là nơi ở và làm việc của các vua triều Nguyễn, nay là di sản thế giới.");
    expect(intro).toHaveAttribute("title", "Wikipedia tiếng Việt");
    expect(intro).toHaveClass("italic", "line-clamp-2", "text-muc-soft");
    expect(within(panel).getAllByTitle("Wikipedia tiếng Việt")).toHaveLength(1);
  });

  it("labels the sunset stop as an estimate next to its time", async () => {
    routeFetch(() => ({ body: slotsJson }));
    renderPlan();
    await screen.findByRole("heading", { level: 1 });

    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByText("(giờ hoàng hôn ước tính)")).toBeInTheDocument();
    expect(within(panel).getByText("16:30–17:30")).toBeInTheDocument();
  });

  it("renders a rest block as a compact row with no photo or card body", async () => {
    routeFetch(() => ({ body: slotsJson }));
    renderPlan();
    await screen.findByRole("heading", { level: 1 });

    const panel = screen.getByRole("tabpanel");
    const row = within(panel).getByText("13:00–14:00").closest("li");
    expect(row).not.toBeNull();
    expect(row).toHaveTextContent("13:00–14:00 · Nghỉ trưa");
    expect(within(row as HTMLElement).queryByRole("img")).not.toBeInTheDocument();
  });

  it("shows the outbound leg above day 1 with the mock badge", async () => {
    routeFetch(() => ({ body: slotsJson }));
    renderPlan();
    await screen.findByRole("heading", { level: 1 });

    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByText("04/12 19:00 → 05/12 05:30 · Xe giường nằm Hà Nội → Huế · ước tính")).toBeInTheDocument();
    expect(within(panel).getByText(travelLegText(outboundLeg))).toBeInTheDocument();
    expect(within(panel).getByText("MÔ PHỎNG")).toBeInTheDocument();
    expect(within(panel).queryByText(travelLegText(returnLeg))).not.toBeInTheDocument();
  });

  it("shows the return leg after the last day and not the outbound leg there", async () => {
    routeFetch(() => ({ body: slotsJson }));
    renderPlan();
    await screen.findByRole("heading", { level: 1 });

    const tabs = screen.getAllByRole("tab");
    await userEvent.click(tabs[2]);

    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByText(travelLegText(returnLeg))).toBeInTheDocument();
    expect(within(panel).queryByText(travelLegText(outboundLeg))).not.toBeInTheDocument();
  });

  it("renders no travel leg rows when the plan has none", async () => {
    routeFetch(() => ({ body: planJson }));
    renderPlan();
    await screen.findByRole("heading", { level: 1 });

    const tabs = screen.getAllByRole("tab");
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).queryByText(/Xe giường nằm|Tàu hỏa|Máy bay/)).not.toBeInTheDocument();
    await userEvent.click(tabs[2]);
    expect(within(screen.getByRole("tabpanel")).queryByText(/Xe giường nằm|Tàu hỏa|Máy bay/)).not.toBeInTheDocument();
  });
});
