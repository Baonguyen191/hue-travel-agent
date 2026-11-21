import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, errorMessage, isForbidden, isNotFound, isStale } from "./client";
import { USER_ID_KEY } from "../lib/userId";
import parseDod from "../test/fixtures/parse-dod.json";
import type { TripRequest } from "./types";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

describe("api client", () => {
  beforeEach(() => {
    window.localStorage.setItem(USER_ID_KEY, "user-under-test");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends X-User-Id and parses the JSON body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, parseDod));
    vi.stubGlobal("fetch", fetchMock);

    const parsed = await api.parseTrip("Tôi đi Huế");

    expect(parsed.source).toBe("RULES");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/plans/parse");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["X-User-Id"]).toBe("user-under-test");
  });

  it("sends a UTF-8 JSON body that keeps Vietnamese text", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, parseDod));
    vi.stubGlobal("fetch", fetchMock);

    await api.parseTrip("ngân sách 8 triệu, thích di tích");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ text: "ngân sách 8 triệu, thích di tích" });
    expect((init.headers as Record<string, string>)["Content-Type"]).toContain("charset=utf-8");
  });

  it("posts a trip request to the plan thread", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { thread_id: "t1", status: "AWAITING_APPROVAL" }));
    vi.stubGlobal("fetch", fetchMock);
    const request: TripRequest = {
      origin: "Hà Nội",
      destination: "Huế",
      start_date: "2026-12-05",
      end_date: "2026-12-07",
      people: 2,
      rooms: 1,
      budget_vnd: 8000000,
      categories: [],
      keyword: null,
      preferences: ["di tích"],
      center_lat: null,
      center_lon: null,
      radius_km: null,
    };

    await api.createOrEditPlan("thread-1", request);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/plans/thread-1");
    expect(JSON.parse(init.body as string)).toEqual(request);
  });

  it("turns a 409 with a string detail into a stale ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(409, { detail: "Plan version is stale; approve the latest version." })),
    );

    const error = await api.approvePlan("t", { version: 1, option: "BUDGET" }).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(isStale(error)).toBe(true);
    expect(isForbidden(error)).toBe(false);
    expect((error as ApiError).detail).toBe("Plan version is stale; approve the latest version.");
    expect(errorMessage(error)).toBe("Plan version is stale; approve the latest version.");
  });

  it("keeps FastAPI validation issues (422 list detail) and joins their messages", async () => {
    const issues = [{ type: "string_too_short", loc: ["body", "text"], msg: "String should have at least 1 character" }];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(422, { detail: issues })));

    const error = await api.parseTrip("").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(422);
    expect((error as ApiError).detail).toEqual(issues);
    expect(errorMessage(error)).toBe("String should have at least 1 character");
  });

  it("recognises 403 and 404 helpers", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(403, { detail: "Plan belongs to another user." })));
    const forbidden = await api.getPlan("t").catch((caught: unknown) => caught);
    expect(isForbidden(forbidden)).toBe(true);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(404, { detail: "POI was not found in the Hue source." })));
    const missing = await api.getPlace("huetripo:0").catch((caught: unknown) => caught);
    expect(isNotFound(missing)).toBe(true);
  });

  it("uses the status text when an error body is not JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502, statusText: "Bad Gateway" })));

    const error = await api.getPlan("t").catch((caught: unknown) => caught);

    expect((error as ApiError).status).toBe(502);
    expect((error as ApiError).detail).toBe("Bad Gateway");
  });

  it("wraps a network failure as ApiError with status 0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const error = await api.parseTrip("x").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(0);
    expect(errorMessage(error)).toContain("Không kết nối được máy chủ");
  });

  it("encodes POI ids and builds query strings without empty values", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => jsonResponse(200, { items: [], total: 0, limit: 24, offset: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await api.searchPlaces({ q: "dai noi", limit: 24, offset: 0, category: undefined });
    await api.getPlace("huetripo:531787");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/places/search?q=dai+noi&limit=24&offset=0");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/places/huetripo%3A531787");
  });
});

describe("ApiError", () => {
  it("is an Error with status and detail", () => {
    const error = new ApiError(404, "Plan thread was not found.");

    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe("ApiError");
    expect(error.message).toBe("Plan thread was not found.");
    expect(error.status).toBe(404);
  });
});
