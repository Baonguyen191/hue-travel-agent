import { afterEach, describe, expect, it, vi } from "vitest";
import { USER_ID_KEY, getUserId, shortUserId } from "./userId";

describe("getUserId", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("creates an id once and reuses it from localStorage", () => {
    const first = getUserId();
    const second = getUserId();

    expect(first).toMatch(/^[0-9a-f-]{36}$/);
    expect(second).toBe(first);
    expect(window.localStorage.getItem(USER_ID_KEY)).toBe(first);
  });

  it("uses a stored id as it is", () => {
    window.localStorage.setItem(USER_ID_KEY, "stored-id-123");

    expect(getUserId()).toBe("stored-id-123");
  });

  it("still returns an id when localStorage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    const id = getUserId();

    expect(id.length).toBeGreaterThan(0);
    expect(getUserId()).toBe(id);
  });
});

describe("shortUserId", () => {
  it("keeps the first eight characters for display", () => {
    expect(shortUserId("1a2b3c4d-5e6f-7890-abcd-ef1234567890")).toBe("1a2b3c4d");
  });
});
