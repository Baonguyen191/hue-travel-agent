import { describe, expect, it } from "vitest";
import type { BudgetOption, BudgetResult, CostItem } from "../api/types";
import { anyOptionFits, budgetWarnings, optionFits, optionLabelText, sourceTag, unitText } from "./budget";

function item(overrides: Partial<CostItem>): CostItem {
  return {
    code: "meal",
    label: "Quán",
    amount_vnd: 300000,
    amount_max_vnd: 400000,
    quantity: 1,
    price_unit: "VND_PER_PERSON_PER_MEAL_ASSUMED",
    source: "HUE_POI_SOURCE",
    price_kind: "ESTIMATED",
    note: null,
    poi_id: null,
    ...overrides,
  };
}

function option(overrides: Partial<BudgetOption>): BudgetOption {
  return {
    transport_outbound: null,
    transport_return: null,
    hotel: null,
    items: [],
    known_total_vnd: 0,
    known_total_max_vnd: 0,
    unknown_item_count: 0,
    budget_status: "OVER_BUDGET",
    budget_remaining_vnd: -100000,
    label: null,
    warnings: [],
    ...overrides,
  };
}

describe("sourceTag", () => {
  it("tags mock, Hue data, estimates and unknown prices", () => {
    expect(sourceTag(item({ source: "MOCK", price_kind: "QUOTED" })).text).toBe("MOCK");
    expect(sourceTag(item({ source: "HUE_POI_SOURCE", price_kind: "ESTIMATED" })).text).toBe("DATA");
    expect(sourceTag(item({ source: "BUDGET_CONFIG", price_kind: "ESTIMATED" })).text).toBe("ƯỚC TÍNH");
    expect(sourceTag(item({ source: "HUE_POI_SOURCE", price_kind: "UNKNOWN" })).text).toBe("CHƯA RÕ");
  });

  it("never lets an unknown price show as a verified source", () => {
    expect(sourceTag(item({ source: "MOCK", price_kind: "UNKNOWN" })).text).toBe("CHƯA RÕ");
  });
});

describe("fit and labels", () => {
  it("treats both within-budget statuses as fitting", () => {
    expect(optionFits(option({ budget_status: "WITHIN_BUDGET" }))).toBe(true);
    expect(optionFits(option({ budget_status: "WITHIN_BUDGET_EXCLUDING_UNKNOWN" }))).toBe(true);
    expect(optionFits(option({ budget_status: "OVER_BUDGET" }))).toBe(false);
    expect(optionFits(option({ budget_status: "UNKNOWN" }))).toBe(false);
  });

  it("reports when no option fits", () => {
    const budget: BudgetResult = {
      options: [option({ budget_status: "OVER_BUDGET" }), option({ budget_status: "UNKNOWN" })],
      warnings: [],
      shortfall_vnd: 500000,
    };

    expect(anyOptionFits(budget)).toBe(false);
  });

  it("gives Vietnamese names to labels and leaves unlabelled options with a dash", () => {
    expect(optionLabelText("BUDGET")).toBe("Tiết kiệm");
    expect(optionLabelText("BALANCED")).toBe("Cân bằng");
    expect(optionLabelText("COMFORT")).toBe("Thoải mái");
    expect(optionLabelText(null)).toBe("—");
  });

  it("names the price units", () => {
    expect(unitText("VND_PER_ROOM_PER_NIGHT")).toBe("mỗi phòng, mỗi đêm");
    expect(unitText("SOMETHING_NEW")).toBe("SOMETHING_NEW");
  });

  it("collects budget and option warnings without repeats", () => {
    const budget: BudgetResult = {
      options: [option({ warnings: ["Known total excludes items with an unknown amount."] }), option({ warnings: ["Known total excludes items with an unknown amount."] })],
      warnings: ["Ngân sách không đủ cho lưu trú."],
      shortfall_vnd: null,
    };

    expect(budgetWarnings(budget)).toEqual([
      "Ngân sách không đủ cho lưu trú.",
      "Tổng đã biết không gồm các mục chưa rõ giá.",
    ]);
  });
});
