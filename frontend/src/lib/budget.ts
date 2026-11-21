// Budget presentation rules. Amounts are reference values; the API never sums money on the client.
import type { BudgetOption, BudgetResult, CostItem } from "../api/types";
import type { StatusTone } from "./plan";
import { translateWarnings } from "./warnings";

const STATUS_VN: Record<string, { label: string; tone: StatusTone }> = {
  WITHIN_BUDGET: { label: "Trong ngân sách", tone: "approved" },
  WITHIN_BUDGET_EXCLUDING_UNKNOWN: { label: "Trong ngân sách (chưa tính mục chưa rõ)", tone: "waiting" },
  OVER_BUDGET: { label: "Vượt ngân sách", tone: "failed" },
  UNKNOWN: { label: "Chưa đủ dữ liệu", tone: "neutral" },
};

export function budgetStatusLabel(status: string): string {
  return STATUS_VN[status]?.label ?? status;
}

export function budgetStatusTone(status: string): StatusTone {
  return STATUS_VN[status]?.tone ?? "neutral";
}

const OPTION_VN: Record<string, string> = { BUDGET: "Tiết kiệm", BALANCED: "Cân bằng", COMFORT: "Thoải mái" };

/** "Tiết kiệm", "Cân bằng" or "Thoải mái"; an unlabelled option shows a dash. */
export function optionLabelText(label: string | null): string {
  return (label && OPTION_VN[label]) || "—";
}

const UNIT_VN: Record<string, string> = {
  VND_PER_PERSON_PER_LEG: "mỗi người, mỗi lượt",
  VND_PER_ROOM_PER_NIGHT: "mỗi phòng, mỗi đêm",
  VND_PER_GROUP_PER_DAY: "cả nhóm, mỗi ngày",
  VND_PER_PERSON_PER_MEAL_ASSUMED: "mỗi người, mỗi bữa (giả định)",
};

export function unitText(unit: string): string {
  return UNIT_VN[unit] ?? unit;
}

export interface SourceTag {
  text: string;
  tone: "mock" | "data" | "estimate" | "unknown";
}

/** MOCK / DATA / ƯỚC TÍNH / CHƯA RÕ. An unknown price is always CHƯA RÕ, whatever its source. */
export function sourceTag(item: CostItem): SourceTag {
  if (item.price_kind === "UNKNOWN") return { text: "CHƯA RÕ", tone: "unknown" };
  if (item.source === "MOCK") return { text: "MOCK", tone: "mock" };
  if (item.source === "HUE_POI_SOURCE") return { text: "DATA", tone: "data" };
  return { text: "ƯỚC TÍNH", tone: "estimate" };
}

export const SOURCE_TAG_CLASS: Record<SourceTag["tone"], string> = {
  mock: "bg-violet-100 text-violet-900 ring-violet-300",
  data: "bg-sky-100 text-sky-900 ring-sky-300",
  estimate: "bg-amber-100 text-amber-900 ring-amber-300",
  unknown: "bg-slate-200 text-slate-800 ring-slate-400",
};

/** An option fits when its status is within budget, including the version that excludes unknown items. */
export function optionFits(option: BudgetOption): boolean {
  return option.budget_status === "WITHIN_BUDGET" || option.budget_status === "WITHIN_BUDGET_EXCLUDING_UNKNOWN";
}

export function anyOptionFits(budget: BudgetResult): boolean {
  return budget.options.some(optionFits);
}

/** Every warning on the budget, without repeats, for the shortfall banner. */
export function budgetWarnings(budget: BudgetResult): string[] {
  const all = [...budget.warnings, ...budget.options.flatMap((option) => option.warnings)];
  return translateWarnings(all);
}
