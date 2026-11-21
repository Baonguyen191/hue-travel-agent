// Identity for the MVP: a random id kept in localStorage and sent as X-User-Id.
// This is an ownership key, not a login. If storage is blocked, a per-page id is used instead.

export const USER_ID_KEY = "hue.userId";

let memoryFallback: string | null = null;

function newId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const random = (Math.random() * 16) | 0;
    return (char === "x" ? random : (random & 0x3) | 0x8).toString(16);
  });
}

export function getUserId(): string {
  try {
    const stored = window.localStorage.getItem(USER_ID_KEY);
    if (stored) return stored;
    const created = newId();
    window.localStorage.setItem(USER_ID_KEY, created);
    return created;
  } catch {
    memoryFallback ??= newId();
    return memoryFallback;
  }
}

/** First 8 characters, for display: "Người dùng thử: 1a2b3c4d". */
export function shortUserId(userId: string): string {
  return userId.slice(0, 8);
}
