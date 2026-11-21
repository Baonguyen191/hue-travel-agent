import { vi } from "vitest";

export interface RouteReply {
  status?: number;
  body: unknown;
}

/**
 * Replaces global fetch with a router keyed by the request URL (path and query included).
 * Each call gets a fresh Response, so bodies are never read twice.
 */
export function routeFetch(handler: (url: string) => RouteReply) {
  const mock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const reply = handler(url);
    return new Response(JSON.stringify(reply.body), {
      status: reply.status ?? 200,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

/** Every URL the mock was called with, in order. */
export function calledUrls(mock: ReturnType<typeof routeFetch>): string[] {
  return mock.mock.calls.map(([input]) => (typeof input === "string" ? input : String(input)));
}
