import { describe, expect, it } from "vitest";
import type { PlanRecord } from "../api/types";
import planApproved from "../test/fixtures/plan-approved.json";
import planWaiting from "../test/fixtures/plan.json";
import { translateWarnings } from "./warnings";
import type { TravelLeg } from "../api/types";
import {
  MODE_LABEL,
  SLOT_LABEL,
  effectiveStatus,
  eventKindLabel,
  findTravelLeg,
  isApproved,
  isWaiting,
  placesById,
  slotLabel,
  summarizeWarnings,
  travelLegText,
  travelText,
} from "./plan";

const bus: TravelLeg = {
  direction: "OUTBOUND",
  mode: "BUS",
  origin: "Hà Nội",
  destination: "Huế",
  depart_at: "2026-12-04T19:00:00",
  arrive_at: "2026-12-05T05:30:00",
  estimated: true,
  mock: true,
};

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
    for (const message of translateWarnings([...expected])) expect(summary.messages).toContain(message);
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

  it("labels rest blocks as rest", () => {
    expect(eventKindLabel({ ...waiting.payload.itinerary.days[0].events[0], kind: "REST" })).toBe("Nghỉ");
  });
});

describe("slot labels", () => {
  it("maps every slot to its Vietnamese label", () => {
    expect(SLOT_LABEL).toEqual({
      morning: "Sáng",
      lunch: "Trưa",
      rest: "Nghỉ trưa",
      afternoon: "Chiều",
      cafe: "Cà phê",
      sunset: "Hoàng hôn",
      dinner: "Tối",
    });
  });

  it("returns null for events without a slot, so older plans show no label", () => {
    expect(slotLabel("sunset")).toBe("Hoàng hôn");
    expect(slotLabel(null)).toBeNull();
    expect(slotLabel(undefined)).toBeNull();
  });
});

describe("travel legs", () => {
  it("names each transport mode in Vietnamese", () => {
    expect(MODE_LABEL).toEqual({ BUS: "Xe giường nằm", TRAIN: "Tàu hỏa", FLIGHT: "Máy bay" });
  });

  it("writes the outbound leg as depart day/month and time, arrival time, mode, route and estimate", () => {
    expect(travelLegText(bus)).toBe("04/12 19:00 → 05/12 05:30 · Xe giường nằm Hà Nội → Huế · ước tính");
  });

  it("drops the estimate marker when the time is not estimated", () => {
    expect(travelLegText({ ...bus, mode: "TRAIN", direction: "RETURN", origin: "Huế", destination: "Hà Nội", estimated: false })).toBe(
      "04/12 19:00 → 05/12 05:30 · Tàu hỏa Huế → Hà Nội",
    );
    expect(travelLegText({ ...bus, mode: "FLIGHT" })).toContain("· Máy bay Hà Nội → Huế");
  });

  it("finds a leg by direction and returns undefined when there is none", () => {
    const legs = [bus, { ...bus, direction: "RETURN" as const, origin: "Huế", destination: "Hà Nội" }];
    expect(findTravelLeg(legs, "RETURN")?.origin).toBe("Huế");
    expect(findTravelLeg(legs, "OUTBOUND")?.origin).toBe("Hà Nội");
    expect(findTravelLeg(undefined, "OUTBOUND")).toBeUndefined();
    expect(findTravelLeg([bus], "RETURN")).toBeUndefined();
  });
});

describe("travel legs on the same day", () => {
  it("writes only the arrival time when the leg lands the same day", () => {
    const flight = {
      direction: "OUTBOUND" as const,
      mode: "FLIGHT" as const,
      origin: "Hà Nội",
      destination: "Huế",
      depart_at: "2026-12-05T06:00:00",
      arrive_at: "2026-12-05T07:20:00",
      estimated: true,
      mock: true,
    };
    expect(travelLegText(flight)).toBe("05/12 06:00 → 07:20 · Máy bay Hà Nội → Huế · ước tính");
  });
});
