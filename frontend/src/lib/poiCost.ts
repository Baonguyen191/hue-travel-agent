// Prices for itinerary stops come from the budget lines that carry a poi_id (admission and meal).
// Those amounts are for the whole group, so they are divided by the number of people for display.
import type { CostItem, PlanRecord } from "../api/types";
import { formatVndRange } from "./format";
import { sourceTag } from "./budget";

/** The cost line for each POI. Uses the approved option, else the first option; POI lines match across options. */
export function poiCostIndex(record: PlanRecord): Map<string, CostItem> {
  const options = record.payload.budget.options;
  const approved = record.checkpoint?.approval?.option;
  const option = options.find((candidate) => candidate.label !== null && candidate.label === approved) ?? options[0];
  const index = new Map<string, CostItem>();
  for (const item of option?.items ?? []) {
    if (!item.poi_id) continue;
    // An admission line is the better price for a sight; a meal line covers a restaurant.
    const current = index.get(item.poi_id);
    if (!current || (item.code === "admission" && current.code !== "admission")) index.set(item.poi_id, item);
  }
  return index;
}

function perPerson(amount: number | null, people: number): number | null {
  if (amount === null || people <= 0) return null;
  return amount / people;
}

/**
 * Per-person price text for a stop. Amounts from the source are references; the unit caveat stays visible.
 * admission: "Vé: 200.000 ₫/người (tham khảo) [DATA]"; meal: "… ₫/người (tham khảo, đơn vị chưa rõ)".
 */
export function describePoiCost(item: CostItem | undefined, people: number): string {
  if (!item || item.price_kind === "UNKNOWN" || item.amount_vnd === null) return "giá chưa rõ";
  if (item.code === "admission" && item.amount_vnd === 0) return "miễn phí theo nguồn";
  const low = perPerson(item.amount_vnd, people);
  const high = perPerson(item.amount_max_vnd, people);
  if (low === null) return "giá chưa rõ";
  const amount = `${formatVndRange(low, high)}/người`;
  if (item.code === "admission") return `Vé: ${amount} (tham khảo) [${sourceTag(item).text}]`;
  return `${amount} (tham khảo, đơn vị chưa rõ)`;
}
