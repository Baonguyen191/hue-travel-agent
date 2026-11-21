import { describe, expect, it } from "vitest";
import type { PlanRecord } from "../api/types";
import planApproved from "../test/fixtures/plan-approved.json";
import planWaiting from "../test/fixtures/plan.json";
import { effectiveStatus, eventKindLabel, isApproved, isWaiting, placesById, summarizeWarnings, travelText } from "./plan";

const waiting = planWaiting as unknown as PlanRecord;
const approved = planApproved as unknown as PlanRecord;

describe("effective status", () => {
  it("uses the checkpoint status over the stored trip status", () => {
    // The stored trip status stays AWAITING_APPROVAL after approve; the checkpoint says APPROVED.
    expect(approved.status).toBe("AWAITING_APPROVAL");
    expect(effectiveStatus(approved)).toBe("APPROVED");
    expect(isApproved(approved)).toBe(true);
  });

  it("is waiting only when the checkpoint says so", () => {
    expect(isWaiting(waiting)).toBe(true);
    expect(isWaiting(approved)).toBe(false);
  });

  it("falls back to the stored status when there is no checkpoint", () => {
    const record = { ...waiting, checkpoint: null };

    expect(effectiveStatus(record)).toBe("AWAITING_APPROVAL");
    expect(isWaiting(record)).toBe(false);
  });
});

describe("summarizeWarnings", () => {
  it("merges itinerary, day, search, budget and checkpoint warnings without repeats", () => {
    const summary = summarizeWarnings(waiting);
    const expected = new Set([
      ...waiting.payload.itinerary.warnings,
      ...waiting.payload.itinerary.days.flatMap((day) => day.warnings),
      ...waiting.payload.budget.warnings,
    ]);

    expect(summary.messages.length).toBeGreaterThan(0);
    expect(new Set(summary.messages).size).toBe(summary.messages.length);
    for (const message of expected) expect(summary.messages).toContain(message);
  });

  it("reports the validation result and the exclusion, merge and unplanned counts", () => {
    const summary = summarizeWarnings(waiting);

    expect(summary.validationValid).toBe(true);
    expect(summary.excluded).toBe(waiting.payload.itinerary.excluded_poi_ids.length);
    expect(summary.merged).toBe(waiting.payload.itinerary.merged_poi_ids.length);
    expect(summary.unplanned).toBe(waiting.payload.itinerary.unplanned_poi_ids.length);
  });

  it("keeps an invalid validation result visible", () => {
    const record = {
      ...waiting,
      payload: {
        ...waiting.payload,
        itinerary: { ...waiting.payload.itinerary, validation: { valid: false, warnings: ["Lịch trình trùng giờ"] } },
      },
    };

    const summary = summarizeWarnings(record);
    expect(summary.validationValid).toBe(false);
    expect(summary.validationMessages).toEqual(["Lịch trình trùng giờ"]);
    expect(summary.messages).toContain("Lịch trình trùng giờ");
  });
});

describe("timeline helpers", () => {
  it("labels meals and visits in Vietnamese", () => {
    const meal = waiting.payload.itinerary.days[0].events.find((event) => event.meal === "LUNCH")!;
    const visit = waiting.payload.itinerary.days[0].events.find((event) => event.kind === "VISIT")!;

    expect(eventKindLabel(meal)).toBe("Bữa trưa");
    expect(eventKindLabel(visit)).toBe("Tham quan");
  });

  it("shows travel as an estimate with a decimal comma, or a dash when unknown", () => {
    const withDistance = { ...waiting.payload.itinerary.days[0].events[0], travel_distance_km: 1.249, travel_minutes_estimated: 4 };
    const without = { ...withDistance, travel_distance_km: null, travel_minutes_estimated: null };

    expect(travelText(withDistance)).toBe("1,2 km · 4 phút (ước lượng)");
    expect(travelText(without)).toBe("—");
  });

  it("indexes candidate places by id", () => {
    const first = waiting.payload.search.poi_candidates[0].place;
    expect(placesById(waiting.payload.search).get(first.id)?.name).toBe(first.name);
  });
});
