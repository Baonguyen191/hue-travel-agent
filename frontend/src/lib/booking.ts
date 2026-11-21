// Booking helpers: idempotency keys and last-result persistence per plan thread and quote.
// The booking API has no GET, so a repeat POST with the same key is how a status is re-checked.
import type { BookingResult, BookingStatus } from "../api/types";
import { newUuid } from "./ids";
import { readJson, safeGet, safeSet, writeJson } from "./storage";
import type { StatusTone } from "./plan";

const KEY_PREFIX = "hue.booking.key";
const RESULT_PREFIX = "hue.booking.result";

function keyFor(threadId: string, quoteHash: string): string {
  return `${KEY_PREFIX}.${threadId}.${quoteHash}`;
}

/**
 * The same key for the same thread and quote, so repeated clicks return the stored intent.
 * A new quote (a new approval) gets a new key.
 */
export function idempotencyKeyFor(threadId: string, quoteHash: string): string {
  const key = keyFor(threadId, quoteHash);
  const stored = safeGet(key);
  if (stored && stored.length >= 8) return stored;
  const created = newUuid();
  safeSet(key, created);
  return created;
}

interface StoredResult {
  quote_hash: string;
  result: BookingResult;
}

function isStoredResult(value: unknown): value is StoredResult {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<StoredResult>;
  return typeof candidate.quote_hash === "string" && typeof candidate.result === "object" && candidate.result !== null;
}

/** The last BookingResult for a thread, whatever its quote. The caller compares quote hashes. */
export function loadStoredResult(threadId: string): BookingResult | null {
  return readJson(`${RESULT_PREFIX}.${threadId}`, isStoredResult)?.result ?? null;
}

export function saveStoredResult(threadId: string, result: BookingResult): void {
  writeJson(`${RESULT_PREFIX}.${threadId}`, { quote_hash: result.quote_hash, result } satisfies StoredResult);
}

/** A result is worth re-checking when an item is unknown or the booking is only partly done. */
export function needsRecheck(result: BookingResult): boolean {
  return (
    result.status === "UNKNOWN" ||
    result.status === "PARTIALLY_BOOKED" ||
    result.items.some((item) => item.status === "UNKNOWN")
  );
}

const STATUS_VN: Record<BookingStatus, { label: string; tone: StatusTone }> = {
  BOOKED: { label: "Đã đặt (MÔ PHỎNG)", tone: "approved" },
  PARTIALLY_BOOKED: { label: "Đặt một phần", tone: "waiting" },
  FAILED: { label: "Thất bại", tone: "failed" },
  UNKNOWN: { label: "Chưa rõ, cần kiểm tra lại", tone: "waiting" },
  RECONFIRM_REQUIRED: { label: "Cần xác nhận lại giá", tone: "waiting" },
  PENDING: { label: "Đang chờ", tone: "neutral" },
  NOT_SUPPORTED_BY_DATASET: { label: "Tự liên hệ", tone: "neutral" },
};

export function bookingStatusLabel(status: BookingStatus): string {
  return STATUS_VN[status].label;
}

export function bookingStatusTone(status: BookingStatus): StatusTone {
  return STATUS_VN[status].tone;
}
