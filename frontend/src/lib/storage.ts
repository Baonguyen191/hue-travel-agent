// localStorage with a fallback. Storage can be blocked, full or disabled (private windows, site
// data cleared). Every access is wrapped; when it fails, values live in memory for this page only.

const memory = new Map<string, string>();

export function safeGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return memory.get(key) ?? null;
  }
}

export function safeSet(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    memory.set(key, value);
  }
}

export function safeRemove(key: string): void {
  memory.delete(key);
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Nothing else to do: the in-memory copy is already gone.
  }
}

/** JSON read that returns null for missing, corrupt or unexpected data instead of throwing. */
export function readJson<T>(key: string, isValid: (value: unknown) => value is T): T | null {
  const raw = safeGet(key);
  if (raw === null) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    return isValid(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function writeJson(key: string, value: unknown): void {
  safeSet(key, JSON.stringify(value));
}
