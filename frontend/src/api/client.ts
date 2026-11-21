import { getUserId } from "../lib/userId";
import type {
  ApprovalRequest,
  ApprovalResult,
  BookingRequest,
  BookingResult,
  CheckpointState,
  ErrorBody,
  ParsedTrip,
  Place,
  PlacePage,
  PlaceCategory,
  PlaceSearchPage,
  PlanRecord,
  TripRequest,
  ValidationIssue,
} from "./types";

export const API_BASE = "/api/v1";
const NETWORK_MESSAGE = "Không kết nối được máy chủ. Kiểm tra backend đang chạy.";

/** A failed API call. `status` is 0 when the request never reached the server. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | ValidationIssue[];

  constructor(status: number, detail: string | ValidationIssue[]) {
    super(errorText(detail, status));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function errorText(detail: string | ValidationIssue[], status: number): string {
  if (typeof detail === "string") return detail;
  if (detail.length > 0) return detail.map((issue) => issue.msg).join("; ");
  return status === 0 ? NETWORK_MESSAGE : `Lỗi ${status}`;
}

export const isStale = (error: unknown): boolean => error instanceof ApiError && error.status === 409;
export const isForbidden = (error: unknown): boolean => error instanceof ApiError && error.status === 403;
export const isNotFound = (error: unknown): boolean => error instanceof ApiError && error.status === 404;

/** Message to show in a banner: the API detail when there is one, else a generic Vietnamese text. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Đã có lỗi xảy ra.";
}

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  signal?: AbortSignal;
}

async function readDetail(response: Response): Promise<string | ValidationIssue[]> {
  try {
    const body = (await response.json()) as Partial<ErrorBody>;
    if (typeof body.detail === "string" || Array.isArray(body.detail)) return body.detail;
  } catch {
    // Non-JSON error body: fall through to the status text.
  }
  return response.statusText || `Lỗi ${response.status}`;
}

/** Calls the API with X-User-Id and JSON. Any non-2xx response or network failure throws ApiError. */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "X-User-Id": getUserId(),
  };
  const init: RequestInit = { method: options.method ?? "GET", headers, signal: options.signal };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json; charset=utf-8";
    init.body = JSON.stringify(options.body);
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, NETWORK_MESSAGE);
  }
  if (!response.ok) {
    throw new ApiError(response.status, await readDetail(response));
  }
  return (await response.json()) as T;
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** Typed endpoints used by the screens. Paths are relative to /api/v1. */
export const api = {
  parseTrip: (text: string, signal?: AbortSignal) =>
    apiRequest<ParsedTrip>("/plans/parse", { method: "POST", body: { text }, signal }),

  /** Starts a plan, or edits the one waiting for approval (which creates the next version). */
  createOrEditPlan: (threadId: string, request: TripRequest) =>
    apiRequest<CheckpointState>(`/plans/${threadId}`, { method: "POST", body: request }),

  getPlan: (threadId: string, signal?: AbortSignal) => apiRequest<PlanRecord>(`/plans/${threadId}`, { signal }),

  approvePlan: (threadId: string, body: ApprovalRequest) =>
    apiRequest<ApprovalResult>(`/plans/${threadId}/approve`, { method: "POST", body }),

  bookPlan: (threadId: string, body: BookingRequest) =>
    apiRequest<BookingResult>(`/plans/${threadId}/book`, { method: "POST", body }),

  searchPlaces: (params: { q: string; category?: PlaceCategory; limit?: number; offset?: number }, signal?: AbortSignal) =>
    apiRequest<PlaceSearchPage>(`/places/search${query(params)}`, { signal }),

  listPlaces: (params: { category?: PlaceCategory; limit?: number; offset?: number }, signal?: AbortSignal) =>
    apiRequest<PlacePage>(`/places${query(params)}`, { signal }),

  getPlace: (poiId: string, signal?: AbortSignal) =>
    apiRequest<Place>(`/places/${encodeURIComponent(poiId)}`, { signal }),
};
