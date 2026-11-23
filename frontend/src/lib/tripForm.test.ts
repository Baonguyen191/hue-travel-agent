import { describe, expect, it } from "vitest";
import type { ParsedTrip } from "../api/types";
import parseDod from "../test/fixtures/parse-dod.json";
import parseMissing from "../test/fixtures/parse-missing.json";
import {
  EMPTY_VALUES,
  missingFormFields,
  toTripRequest,
  validateValues,
  valuesFromParsed,
  type FormValues,
} from "./tripForm";

const dod = parseDod as ParsedTrip;
const partial = parseMissing as ParsedTrip;

function complete(overrides: Partial<FormValues> = {}): FormValues {
  return {
    ...EMPTY_VALUES,
    origin: "Hà Nội",
    startDate: "2026-12-05",
    endDate: "2026-12-07",
    people: "2",
    ...overrides,
  };
}

describe("valuesFromParsed", () => {
  it("prefills every field from a complete parse", () => {
    expect(valuesFromParsed(dod)).toEqual({
      origin: "Hà Nội",
      destination: "Huế",
      startDate: "2026-12-05",
      endDate: "2026-12-07",
      people: "2",
      rooms: "1",
      budget: "8000000",
      preferences: ["di tích", "đặc sản"],
      categories: [],
    });
  });

  it("uses the fields the rules found when the request is incomplete, and defaults the destination", () => {
    const values = valuesFromParsed(partial);

    expect(values.origin).toBe("");
    expect(values.startDate).toBe("");
    expect(values.people).toBe("2");
    expect(values.destination).toBe("Huế");
  });

  it("defaults the destination to Huế when the parser gives none", () => {
    const values = valuesFromParsed({ request: null, missing_fields: [], source: "RULES", fields: {}, notes: [] });

    expect(values.destination).toBe("Huế");
  });
});

describe("missingFormFields", () => {
  it("maps API field names to form fields and drops unknown ones", () => {
    expect(missingFormFields(["origin", "start_date", "end_date", "budget_vnd", "surprise"])).toEqual([
      "origin",
      "startDate",
      "endDate",
      "budget",
    ]);
  });
});

describe("validateValues", () => {
  it("accepts a complete, consistent trip", () => {
    expect(validateValues(complete())).toEqual({});
  });

  it("requires origin, start and end dates, and people", () => {
    const errors = validateValues(EMPTY_VALUES);

    expect(errors.origin).toBe("Nhập điểm xuất phát.");
    expect(errors.startDate).toBe("Chọn ngày đi.");
    expect(errors.endDate).toBe("Chọn ngày về.");
    expect(errors.people).toBe("Số người từ 1 đến 20.");
  });

  it("requires the return date to be after the departure date", () => {
    expect(validateValues(complete({ endDate: "2026-12-05" })).endDate).toBe("Ngày về phải sau ngày đi.");
    expect(validateValues(complete({ endDate: "2026-12-04" })).endDate).toBe("Ngày về phải sau ngày đi.");
  });

  it("rejects an impossible calendar date", () => {
    expect(validateValues(complete({ startDate: "2026-02-31" })).startDate).toBe("Chọn ngày đi.");
  });

  it("keeps people within 1 to 20 and rooms within 1 to 10, as the backend does", () => {
    expect(validateValues(complete({ people: "0" })).people).toBeDefined();
    expect(validateValues(complete({ people: "21" })).people).toBeDefined();
    expect(validateValues(complete({ people: "2.5" })).people).toBeDefined();
    expect(validateValues(complete({ people: "20" })).people).toBeUndefined();
    expect(validateValues(complete({ rooms: "11" })).rooms).toBeDefined();
    expect(validateValues(complete({ rooms: "10" })).rooms).toBeUndefined();
  });

  it("treats an empty budget as unknown, but rejects a budget that is not a positive whole number", () => {
    expect(validateValues(complete({ budget: "" })).budget).toBeUndefined();
    expect(validateValues(complete({ budget: "0" })).budget).toBeDefined();
    expect(validateValues(complete({ budget: "8 triệu" })).budget).toBeDefined();
    expect(validateValues(complete({ budget: "8000000" })).budget).toBeUndefined();
  });

  it("allows at most ten preferences", () => {
    const eleven = Array.from({ length: 11 }, (_, index) => `sở thích ${index}`);

    expect(validateValues(complete({ preferences: eleven })).preferences).toBe("Tối đa 10 sở thích.");
  });
});

describe("toTripRequest", () => {
  it("rebuilds the exact request the parser returned for the DoD sentence", () => {
    const request = toTripRequest(valuesFromParsed(dod), dod.request);

    expect(request).toEqual(dod.request);
  });

  it("sends an empty budget as null and trims text fields", () => {
    const request = toTripRequest(complete({ origin: "  Hà Nội  ", budget: "" }), null);

    expect(request.origin).toBe("Hà Nội");
    expect(request.budget_vnd).toBeNull();
    expect(request.people).toBe(2);
    expect(request.rooms).toBe(1);
  });

  it("keeps the map and keyword fields of the base request", () => {
    const base = { ...dod.request!, keyword: "chùa", center_lat: 16.46, center_lon: 107.58, radius_km: 3 };
    const request = toTripRequest(valuesFromParsed(dod), base);

    expect(request).toMatchObject({ keyword: "chùa", center_lat: 16.46, center_lon: 107.58, radius_km: 3 });
  });

  it("keeps the transport, hotel tier and pace of the base request", () => {
    const base = { ...dod.request!, transport_mode: "train" as const, hotel_tier: "resort" as const, pace: "relaxed" as const };
    const request = toTripRequest(valuesFromParsed(dod), base);

    expect(request).toMatchObject({ transport_mode: "train", hotel_tier: "resort", pace: "relaxed" });
  });

  it("sends any transport and stay as null and the moderate pace when there is no base request", () => {
    const request = toTripRequest(complete(), null);

    expect(request).toMatchObject({ transport_mode: null, hotel_tier: null, pace: "moderate" });
  });
});
