// Derived views of a plan record. The API keeps two statuses: the stored trip status (which is not
// updated after approval) and the checkpoint status (the live graph state). The checkpoint wins when present.
import type { ItineraryEvent, PlanRecord, Place, SearchResult } from "../api/types";
import { formatDate, formatKm, formatMinutes, formatTime } from "./format";
import { translateWarnings } from "./warnings";
import { CATEGORY_LABEL } from "./labels";

export function effectiveStatus(record: PlanRecord): string {
  return record.checkpoint?.status ?? record.status;
}

export function isWaiting(record: PlanRecord): boolean {
  return record.checkpoint?.waiting === true;
}

export function isApproved(record: PlanRecord): boolean {
  return effectiveStatus(record) === "APPROVED";
}

export const STATUS_LABEL: Record<string, string> = {
  AWAITING_APPROVAL: "Chờ duyệt",
  APPROVED: "Đã duyệt",
  EDITING: "Đang sửa",
  RUNNING: "Đang tạo",
  FAILED_VALIDATION: "Chưa hợp lệ",
};

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

export type StatusTone = "approved" | "waiting" | "failed" | "neutral";

export function statusTone(status: string): StatusTone {
  if (status === "APPROVED") return "approved";
  if (status === "AWAITING_APPROVAL") return "waiting";
  if (status === "FAILED_VALIDATION") return "failed";
  return "neutral";
}

export function placesById(search: SearchResult): Map<string, Place> {
  return new Map(search.poi_candidates.map((candidate) => [candidate.place.id, candidate.place]));
}

const MEAL_LABEL: Record<string, string> = { LUNCH: "Bữa trưa", DINNER: "Bữa tối", CAFE: "Cà phê, nghỉ" };

export function eventKindLabel(event: ItineraryEvent): string {
  if (event.kind === "VISIT") return "Tham quan";
  if (event.kind === "MEAL") return (event.meal && MEAL_LABEL[event.meal]) || "Ăn uống";
  return event.kind;
}

export function categoryLabel(category: string | null): string {
  if (!category) return "—";
  return (CATEGORY_LABEL as Record<string, string>)[category] ?? category;
}

/** "1,2 km · 4 phút (ước lượng)", or "—" when the itinerary has no distance for this stop. */
export function travelText(event: ItineraryEvent): string {
  if (event.travel_distance_km === null) return "—";
  return `${formatKm(event.travel_distance_km)} · ${formatMinutes(event.travel_minutes_estimated)} (ước lượng)`;
}

export function timeRange(event: ItineraryEvent): string {
  return `${formatTime(event.start_at)}–${formatTime(event.end_at)}`;
}

export function dayTitle(index: number, date: string): string {
  return `Ngày ${index + 1} · ${formatDate(date)}`;
}

export interface WarningSummary {
  /** Every warning from itinerary, days, search, budget options and the checkpoint, without repeats. */
  messages: string[];
  validationValid: boolean;
  validationMessages: string[];
  excluded: number;
  merged: number;
  unplanned: number;
}

export function summarizeWarnings(record: PlanRecord): WarningSummary {
  const { itinerary, search, budget } = record.payload;
  const dayWarnings = itinerary.days.flatMap((day) => day.warnings);
  const optionWarnings = budget.options.flatMap((option) => option.warnings);
  return {
    messages: translateWarnings([
      ...itinerary.warnings,
      ...dayWarnings,
      ...itinerary.validation.warnings,
      ...search.warnings,
      ...budget.warnings,
      ...optionWarnings,
      ...(record.checkpoint?.warnings ?? []),
    ]),
    validationValid: itinerary.validation.valid,
    validationMessages: translateWarnings(itinerary.validation.warnings),
    excluded: itinerary.excluded_poi_ids.length,
    merged: itinerary.merged_poi_ids.length,
    unplanned: itinerary.unplanned_poi_ids.length,
  };
}

/** Names for POI ids: the search candidates first, then the itinerary's own event names. */
export function poiNameIndex(record: PlanRecord): Map<string, string> {
  const names = new Map<string, string>();
  for (const day of record.payload.itinerary.days) {
    for (const event of day.events) {
      if (event.poi_id) names.set(event.poi_id, event.name);
    }
  }
  for (const [id, place] of placesById(record.payload.search)) names.set(id, place.name);
  return names;
}
