import { describe, expect, it } from "vitest";
import type { CostItem, PlanRecord } from "../api/types";
import planApproved from "../test/fixtures/plan-approved.json";
import planWaiting from "../test/fixtures/plan.json";
import { describePoiCost, poiCostIndex } from "./poiCost";

const waiting = planWaiting as unknown as PlanRecord;
const approved = planApproved as unknown as PlanRecord;

function line(overrides: Partial<CostItem>): CostItem {
  return {
    code: "admission",
    label: "Điểm",
    amount_vnd: 400000,
    amount_max_vnd: null,
    quantity: 2,
    price_unit: "VND_PER_PERSON",
    source: "HUE_POI_SOURCE",
    price_kind: "ESTIMATED",
    note: null,
    poi_id: "huetripo:1",
    ...overrides,
  };
}

describe("POI cost index", () => {
  it("maps the Đại Nội stop to its admission line from the real plan", () => {
    const item = poiCostIndex(waiting).get("huetripo:531787");

    expect(item?.code).toBe("admission");
    expect(item?.amount_vnd).toBe(400000);
  });

  it("uses the approved option when there is one, and the POI lines are the same across options", () => {
    expect(poiCostIndex(approved).get("huetripo:531787")?.amount_vnd).toBe(400000);
  });
});

describe("describePoiCost", () => {
  it("shows an admission price per person from a group amount, with its source tag", () => {
    const item = poiCostIndex(waiting).get("huetripo:531787");

    expect(describePoiCost(item, 2)).toBe("Vé: 200.000 ₫/người (tham khảo) [DATA]");
  });

  it("shows a meal range per person with the unit caveat", () => {
    const meal = poiCostIndex(waiting).get("huetripo:528750");

    expect(describePoiCost(meal, 2)).toBe("150.000 – 300.000 ₫/người (tham khảo, đơn vị chưa rõ)");
  });

  it("says a free admission is only the source's claim", () => {
    expect(describePoiCost(line({ amount_vnd: 0 }), 2)).toBe("miễn phí theo nguồn");
  });

  it("says the price is unknown when the line has no amount or is marked unknown", () => {
    expect(describePoiCost(line({ amount_vnd: null, price_kind: "UNKNOWN" }), 2)).toBe("giá chưa rõ");
    expect(describePoiCost(undefined, 2)).toBe("giá chưa rõ");
  });
});
