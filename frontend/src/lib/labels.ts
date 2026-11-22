import type { OpeningHoursConfidence, PlaceCategory } from "../api/types";

/** Category order and colours (Cung đình palette) for chips, markers and legends. */
export const CATEGORY_OPTIONS: ReadonlyArray<{ value: PlaceCategory; label: string; color: string }> = [
  { value: "restaurant", label: "Quán ăn", color: "#a23b2a" },
  { value: "cafe", label: "Cà phê", color: "#7b4f2c" },
  { value: "historic", label: "Di tích", color: "#7a1f1f" },
  { value: "attraction", label: "Điểm tham quan", color: "#2f6f73" },
  { value: "market", label: "Chợ", color: "#b8742f" },
  { value: "religious", label: "Tôn giáo", color: "#7b4a8e" },
  { value: "park", label: "Công viên", color: "#3f5a3a" },
  { value: "museum", label: "Bảo tàng", color: "#5b4636" },
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
