// Display helpers for Vietnamese UI. Times are read by slicing the string, never through Date,
// because the API sends naive local times ("2026-12-05T08:01:00") that must not be shifted.

const UNKNOWN_AMOUNT = "chưa rõ";

function groupThousands(value: number): string {
  return String(Math.round(value)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

/** 1250000 -> "1.250.000 ₫". null or undefined -> "chưa rõ" (never shown as 0). */
export function formatVnd(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return UNKNOWN_AMOUNT;
  return `${groupThousands(amount)} ₫`;
}

/** (200000, 300000) -> "200.000 – 300.000 ₫"; equal or one-sided bounds collapse to one amount. */
export function formatVndRange(min: number | null | undefined, max: number | null | undefined): string {
  const low = min ?? max;
  const high = max ?? min;
  if (low === null || low === undefined || high === null || high === undefined) return UNKNOWN_AMOUNT;
  if (low === high) return formatVnd(low);
  return `${groupThousands(low)} – ${groupThousands(high)} ₫`;
}

/** "2026-12-05T08:01:00" or "...+07:00" -> "08:01". Anything else -> "—". */
export function formatTime(value: string | null | undefined): string {
  const match = value?.match(/T(\d{2}):(\d{2})/);
  return match ? `${match[1]}:${match[2]}` : "—";
}

/** "2026-12-05" -> "05/12/2026". Unparseable input is returned unchanged. */
export function formatDate(value: string | null | undefined): string {
  const match = value?.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? `${match[3]}/${match[2]}/${match[1]}` : (value ?? "—");
}

/** 1.25 -> "1,3 km" (Vietnamese decimal comma). */
export function formatKm(km: number | null | undefined): string {
  if (km === null || km === undefined) return "—";
  return `${km.toFixed(1).replace(".", ",")} km`;
}

/** Minutes as "45 phút"; null -> "—". */
export function formatMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "—";
  return `${minutes} phút`;
}

export interface PlacePriceFields {
  price_status: "REFERENCE_RANGE" | "FREE_CLAIM" | "UNKNOWN";
  price_min_vnd: number | null;
  price_max_vnd: number | null;
}

/**
 * Price line for a POI. Hue POI prices are reference values from the source; the unit is not
 * stated, so the note always says so.
 */
export function describePrice(place: PlacePriceFields): string {
  if (place.price_status === "FREE_CLAIM") return "miễn phí theo nguồn";
  if (place.price_status === "REFERENCE_RANGE" && (place.price_min_vnd !== null || place.price_max_vnd !== null)) {
    return `${formatVndRange(place.price_min_vnd, place.price_max_vnd)} (tham khảo, đơn vị chưa rõ)`;
  }
  return "giá chưa rõ";
}

/** Rating as "4,7/5 · 17 lượt" or "chưa có". */
export function describeRating(value: number | null, count: number | null): string {
  if (value === null) return "chưa có";
  const shown = value.toFixed(1).replace(".", ",");
  return count === null ? `${shown}/5` : `${shown}/5 · ${count} lượt`;
}
