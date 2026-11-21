import type { OpeningHoursConfidence, PlaceCategory } from "../api/types";

/** Category order and colours for chips, markers and legends. Colours are chosen to be distinct. */
export const CATEGORY_OPTIONS: ReadonlyArray<{ value: PlaceCategory; label: string; color: string }> = [
  { value: "restaurant", label: "Quán ăn", color: "#e11d48" },
  { value: "cafe", label: "Cà phê", color: "#a16207" },
  { value: "historic", label: "Di tích", color: "#7c3aed" },
  { value: "attraction", label: "Điểm tham quan", color: "#0891b2" },
  { value: "market", label: "Chợ", color: "#ea580c" },
  { value: "religious", label: "Tôn giáo", color: "#4f46e5" },
  { value: "park", label: "Công viên", color: "#16a34a" },
  { value: "museum", label: "Bảo tàng", color: "#0f766e" },
];

export const CATEGORY_LABEL: Record<PlaceCategory, string> = Object.fromEntries(
  CATEGORY_OPTIONS.map((option) => [option.value, option.label]),
) as Record<PlaceCategory, string>;

export const CATEGORY_COLOR: Record<PlaceCategory, string> = Object.fromEntries(
  CATEGORY_OPTIONS.map((option) => [option.value, option.color]),
) as Record<PlaceCategory, string>;

export const CONFIDENCE_LABEL: Record<OpeningHoursConfidence, string> = {
  UNVERIFIED: "chưa xác minh",
  PARTIAL: "xác minh một phần",
  UNKNOWN: "chưa rõ",
};
