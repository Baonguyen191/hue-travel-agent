import type { Place } from "../api/types";
import { describeRating, formatVndRange } from "./format";
import { CATEGORY_LABEL } from "./labels";

/** Splits text on line breaks into trimmed, non-empty paragraphs. */
export function splitParagraphs(text: string): string[] {
  const paragraphs = text
    .split(/\r?\n/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
  // The source's short summaries are often cut mid-sentence: mark the cut instead of ending abruptly.
  const last = paragraphs.length - 1;
  if (last >= 0 && !/[.!?…"”)]$/.test(paragraphs[last])) paragraphs[last] = `${paragraphs[last]}…`;
  return paragraphs;
}

/** Restaurants and cafés: a "visit time" reads oddly for a meal, so it is not shown for them. */
export function isFoodPlace(place: Place): boolean {
  return place.category === "restaurant" || place.category === "cafe";
}

function hasPriceRange(place: Place): boolean {
  return place.price_status === "REFERENCE_RANGE" && (place.price_min_vnd !== null || place.price_max_vnd !== null);
}

/**
 * One short note on the data's reliability, shown under the info card. Null when the source
 * says nothing that needs a caveat. Only facts already in the data are used.
 */
export function placeNote(place: Place): string | null {
  const hoursUnverified = place.opening_hours_raw !== null && place.opening_hours_confidence === "UNVERIFIED";
  const hoursPartial = place.opening_hours_raw !== null && place.opening_hours_confidence === "PARTIAL";
  const priceRef = place.price_status === "REFERENCE_RANGE";
  const free = place.price_status === "FREE_CLAIM";

  const sentences: string[] = [];
  if (hoursUnverified && priceRef) {
    sentences.push("Giờ mở cửa và giá lấy từ nguồn, chưa được xác minh; đơn vị giá chưa rõ, nên kiểm tra trước khi đi.");
  } else if (hoursUnverified) {
    sentences.push("Giờ mở cửa lấy từ nguồn, chưa được xác minh.");
  } else if (hoursPartial) {
    sentences.push("Giờ mở cửa mới xác minh một phần.");
  } else if (priceRef) {
    sentences.push("Giá là giá tham khảo; đơn vị chưa rõ, nên kiểm tra trước khi đi.");
  }
  if (free) sentences.push("Nguồn ghi là miễn phí; chưa kiểm chứng.");
  return sentences.length > 0 ? sentences.join(" ") : null;
}

/**
 * Factual paragraph built only from the POI's fields. Every clause is omitted when its data is missing.
 * Example: "Đại Nội Huế là di tích ở Đường 23 tháng 8. Nơi này được đánh giá 4,7/5 với 17 lượt trên Google. ..."
 */
export function factualParagraph(place: Place): string {
  const sentences: string[] = [];
  const category = place.category ? (CATEGORY_LABEL as Record<string, string | undefined>)[place.category] : undefined;
  const label = category?.toLowerCase();

  if (label && place.address) {
    sentences.push(`${place.name} là ${label} ở ${place.address}.`);
  } else if (label) {
    sentences.push(`${place.name} là ${label}.`);
  } else if (place.address) {
    sentences.push(`${place.name} nằm ở ${place.address}.`);
  } else {
    sentences.push(`${place.name}.`);
  }

  if (place.rating_value !== null) {
    const shown = describeRating(place.rating_value, null).replace("/5", "");
    const count = place.rating_count !== null ? ` với ${place.rating_count} lượt` : "";
    const source = place.rating_source ? ` trên ${place.rating_source}` : "";
    sentences.push(`Nơi này được đánh giá ${shown}/5${count}${source}.`);
  }

  if (place.visit_minutes !== null && !isFoodPlace(place)) {
    let sentence = `Thời gian tham quan trung bình khoảng ${place.visit_minutes} phút`;
    if (place.price_status === "FREE_CLAIM") {
      sentence += ", miễn phí theo nguồn";
    } else if (hasPriceRange(place)) {
      sentence += `, giá tham khảo ${formatVndRange(place.price_min_vnd, place.price_max_vnd)} (đơn vị chưa rõ)`;
    }
    sentences.push(`${sentence}.`);
  } else if (place.price_status === "FREE_CLAIM") {
    sentences.push("Miễn phí theo nguồn.");
  } else if (hasPriceRange(place)) {
    sentences.push(`Giá tham khảo ${formatVndRange(place.price_min_vnd, place.price_max_vnd)} (đơn vị chưa rõ).`);
  }

  if (place.opening_hours_raw) {
    sentences.push(`Giờ mở cửa theo nguồn: ${place.opening_hours_raw}.`);
  }

  return sentences.join(" ");
}

/** Contact number from the source's raw attributes (any key naming a phone). Null when absent. */
export function placePhone(place: Place): { display: string; tel: string; note: string | null } | null {
  const entry = Object.entries(place.raw_attributes).find(
    ([key, value]) => /điện thoại|sđt|phone/i.test(key) && typeof value === "string" && value.trim() !== "",
  );
  if (!entry) return null;
  const [number, ...rest] = String(entry[1]).split(" - ");
  const display = number.trim();
  const tel = display.replace(/[^\d+]/g, "");
  if (!tel) return null;
  const note = rest.join(" - ").trim();
  return { display, tel, note: note || null };
}

/** Centre of Huế, the reference point for the distance highlight. */
export const HUE_CENTRE = { lat: 16.4698, lon: 107.5786 };

/** Great-circle distance in km between two points (haversine). */
export function distanceKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const toRad = (degrees: number) => (degrees * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.min(1, Math.sqrt(a)));
}

/** Shortens text to at most `max` characters, cut at a word boundary, with "…" when it was cut. */
export function clip(text: string, max: number): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (flat.length <= max) return flat;
  let cut = flat.slice(0, max);
  const space = cut.lastIndexOf(" ");
  if (space > max * 0.6) cut = cut.slice(0, space);
  return `${cut.replace(/[\s,;:]+$/, "")}…`;
}

/** First sentence of a text, on one line. Falls back to the whole text when it has no full stop. */
export function firstSentence(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  const match = flat.match(/^.+?[.!?](?=\s|$)/);
  return match ? match[0] : flat;
}

/** Word that labels a score on the 5-point scale. */
export function ratingWord(value: number): string {
  if (value >= 4.5) return "Tuyệt vời";
  if (value >= 4.0) return "Rất tốt";
  if (value >= 3.5) return "Tốt";
  if (value >= 3.0) return "Khá";
  return "Trung bình";
}

/** Score with a decimal comma: 4.7 -> "4,7". */
export function ratingScore(value: number): string {
  return value.toFixed(1).replace(".", ",");
}

/**
 * Bullets for "Điểm nổi bật" (at most five). Each comes from the place data or the stored article;
 * a bullet is left out when its data is missing.
 */
export function highlights(place: Place): string[] {
  const items: string[] = [];

  const lead = place.guide ? place.guide.text : place.summary;
  if (lead && lead.trim()) items.push(clip(firstSentence(lead), 140));

  const km = distanceKm(place.lat, place.lon, HUE_CENTRE.lat, HUE_CENTRE.lon);
  items.push(km < 1 ? "Ngay trung tâm Huế" : `Cách trung tâm Huế khoảng ${ratingScore(km)} km`);

  if (place.price_status === "FREE_CLAIM") {
    items.push("Miễn phí theo nguồn");
  } else if (hasPriceRange(place)) {
    items.push(`Giá tham khảo ${formatVndRange(place.price_min_vnd, place.price_max_vnd)} (đơn vị chưa rõ)`);
  }

  if (place.opening_hours_raw) items.push(`Mở cửa ${place.opening_hours_raw} (chưa xác minh)`);

  if (place.visit_minutes !== null && !isFoodPlace(place)) items.push(`Nên dành khoảng ${place.visit_minutes} phút`);

  return items.slice(0, 5);
}

/** Opening words of the introduction, shown under the closed "Giới thiệu" summary. */
export function introTeaser(place: Place): string {
  const lead = (place.guide?.text || place.summary || factualParagraph(place)).trim();
  const short = clip(lead, 120);
  return short.endsWith("…") ? short : `${short}…`;
}
