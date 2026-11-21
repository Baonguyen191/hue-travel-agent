import { afterEach, describe, expect, it, vi } from "vitest";
import type { BookingResult } from "../api/types";
import bookJson from "../test/fixtures/book.json";
import {
  bookingStatusLabel,
  idempotencyKeyFor,
  loadStoredResult,
  needsRecheck,
  saveStoredResult,
} from "./booking";

const book = bookJson as unknown as BookingResult;
const THREAD = "e9d95849-941d-422f-ae9c-8c7a69b74e4b";
const QUOTE = book.quote_hash;

describe("idempotency key", () => {
  it("is the same for the same thread and quote, and stored in localStorage", () => {
    const first = idempotencyKeyFor(THREAD, QUOTE);
    const second = idempotencyKeyFor(THREAD, QUOTE);

    expect(first.length).toBeGreaterThanOrEqual(8);
    expect(second).toBe(first);
    expect(window.localStorage.getItem(`hue.booking.key.${THREAD}.${QUOTE}`)).toBe(first);
  });

  it("is new for a different quote, so a new approval never reuses an old intent", () => {
    const first = idempotencyKeyFor(THREAD, QUOTE);

    expect(idempotencyKeyFor(THREAD, "another-quote")).not.toBe(first);
  });

  it("still gives a stable key when localStorage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    const key = idempotencyKeyFor("thread-blocked", "quote-blocked");

    expect(key.length).toBeGreaterThanOrEqual(8);
    expect(idempotencyKeyFor("thread-blocked", "quote-blocked")).toBe(key);
    vi.restoreAllMocks();
  });
});

describe("stored booking result", () => {
  afterEach(() => {
    window.localStorage.clear();
  });

  it("round-trips the last result for a thread", () => {
    saveStoredResult(THREAD, book);

    expect(loadStoredResult(THREAD)).toEqual(book);
  });

  it("returns null for corrupt or missing data instead of throwing", () => {
    window.localStorage.setItem(`hue.booking.result.${THREAD}`, "{not json");
    expect(loadStoredResult(THREAD)).toBeNull();

    window.localStorage.setItem(`hue.booking.result.${THREAD}`, JSON.stringify({ quote_hash: 1 }));
    expect(loadStoredResult(THREAD)).toBeNull();

    expect(loadStoredResult("never-saved")).toBeNull();
  });
});

describe("result rules", () => {
  it("asks for a re-check when any item is unknown or the booking is partial", () => {
    expect(needsRecheck(book)).toBe(false);
    expect(needsRecheck({ ...book, items: [{ ...book.items[0], status: "UNKNOWN" }, ...book.items.slice(1)] })).toBe(true);
    expect(needsRecheck({ ...book, status: "PARTIALLY_BOOKED" })).toBe(true);
  });

  it("labels the overall status in Vietnamese and marks it as simulated", () => {
    expect(bookingStatusLabel("BOOKED")).toBe("Đã đặt (MÔ PHỎNG)");
    expect(bookingStatusLabel("UNKNOWN")).toBe("Chưa rõ, cần kiểm tra lại");
  });
});
