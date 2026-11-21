// Pure form logic for the trip request: map API data to form values, validate, and build a TripRequest.
// Rules mirror backend/app/schemas/request.py (dates, people 1-20, rooms 1-10, at most 10 preferences).
import type { ParsedTrip, PlaceCategory, TripRequest } from "../api/types";
import { CATEGORY_OPTIONS } from "./labels";

export const DEFAULT_DESTINATION = "Huế";
export const MAX_PREFERENCES = 10;
export const MAX_PEOPLE = 20;
export const MAX_ROOMS = 10;
const MAX_CITY_LENGTH = 120;

/** Form state. Numbers stay as text so an empty input is a real state. */
export interface FormValues {
  origin: string;
  destination: string;
  startDate: string;
  endDate: string;
  people: string;
  rooms: string;
  budget: string;
  preferences: string[];
  categories: PlaceCategory[];
}

export type FormField = "origin" | "destination" | "startDate" | "endDate" | "people" | "rooms" | "budget" | "preferences";
export type FieldErrors = Partial<Record<FormField, string>>;

/** Field names used by the parser's `missing_fields` (API names), mapped to form fields. */
const API_FIELD_TO_FORM: Record<string, FormField> = {
  origin: "origin",
  destination: "destination",
  start_date: "startDate",
  end_date: "endDate",
  people: "people",
  rooms: "rooms",
  budget_vnd: "budget",
  preferences: "preferences",
};

export const EMPTY_VALUES: FormValues = {
  origin: "",
  destination: DEFAULT_DESTINATION,
  startDate: "",
  endDate: "",
  people: "",
  rooms: "1",
  budget: "",
  preferences: [],
  categories: [],
};

const KNOWN_CATEGORIES = new Set<string>(CATEGORY_OPTIONS.map((option) => option.value));

function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asNumberText(value: unknown, fallback: string): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : fallback;
}

function asTextList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string").map((item) => item.trim()).filter(Boolean);
}

function asCategories(value: unknown): PlaceCategory[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is PlaceCategory => typeof item === "string" && KNOWN_CATEGORIES.has(item));
}

/** Form values from a request object (a saved TripRequest or the parser's `fields`). */
export function valuesFromTrip(source: object): FormValues {
  const data = source as Record<string, unknown>;
  return {
    origin: asText(data.origin),
    destination: asText(data.destination) || DEFAULT_DESTINATION,
    startDate: asText(data.start_date),
    endDate: asText(data.end_date),
    people: asNumberText(data.people, ""),
    rooms: asNumberText(data.rooms, "1"),
    budget: asNumberText(data.budget_vnd, ""),
    preferences: asTextList(data.preferences).slice(0, MAX_PREFERENCES),
    categories: asCategories(data.categories),
  };
}

/** Prefill from a parse result: the complete request when present, else the fields the rules found. */
export function valuesFromParsed(parsed: ParsedTrip): FormValues {
  return valuesFromTrip(parsed.request ?? parsed.fields);
}

/** Maps the parser's missing_fields (API names) to form fields. Unknown names are ignored. */
export function missingFormFields(missing: string[]): FormField[] {
  return missing.map((name) => API_FIELD_TO_FORM[name]).filter((field): field is FormField => field !== undefined);
}

function isWholeNumberInRange(text: string, min: number, max: number): boolean {
  if (!/^\d+$/.test(text.trim())) return false;
  const value = Number(text);
  return value >= min && value <= max;
}

/** True only for a real calendar date in yyyy-mm-dd form (Date.parse rolls 02-31 over, so it is not used). */
function isIsoDate(text: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (!match) return false;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

/** Messages in Vietnamese for every invalid field. An empty object means the form can be submitted. */
export function validateValues(values: FormValues): FieldErrors {
  const errors: FieldErrors = {};
  const origin = values.origin.trim();
  if (origin === "" || origin.length > MAX_CITY_LENGTH) errors.origin = "Nhập điểm xuất phát.";
  const destination = values.destination.trim();
  if (destination === "" || destination.length > MAX_CITY_LENGTH) errors.destination = "Nhập điểm đến.";
  if (!isIsoDate(values.startDate)) errors.startDate = "Chọn ngày đi.";
  if (!isIsoDate(values.endDate)) {
    errors.endDate = "Chọn ngày về.";
  } else if (isIsoDate(values.startDate) && values.endDate <= values.startDate) {
    errors.endDate = "Ngày về phải sau ngày đi.";
  }
  if (!isWholeNumberInRange(values.people, 1, MAX_PEOPLE)) errors.people = `Số người từ 1 đến ${MAX_PEOPLE}.`;
  if (!isWholeNumberInRange(values.rooms, 1, MAX_ROOMS)) errors.rooms = `Số phòng từ 1 đến ${MAX_ROOMS}.`;
  if (values.budget.trim() !== "" && !(isWholeNumberInRange(values.budget, 1, Number.MAX_SAFE_INTEGER))) {
    errors.budget = "Ngân sách phải là số nguyên dương (VND).";
  }
  if (values.preferences.length > MAX_PREFERENCES) {
    errors.preferences = `Tối đa ${MAX_PREFERENCES} sở thích.`;
  }
  return errors;
}

/**
 * Builds the TripRequest. Fields the form does not edit (keyword, map centre, radius) are taken
 * from `base`, so an edit keeps what the parser or the saved plan already had.
 * Call only after validateValues returns no errors.
 */
export function toTripRequest(values: FormValues, base?: TripRequest | null): TripRequest {
  return {
    origin: values.origin.trim(),
    destination: values.destination.trim(),
    start_date: values.startDate,
    end_date: values.endDate,
    people: Number(values.people),
    rooms: Number(values.rooms),
    budget_vnd: values.budget.trim() === "" ? null : Number(values.budget),
    categories: values.categories,
    keyword: base?.keyword ?? null,
    preferences: values.preferences,
    center_lat: base?.center_lat ?? null,
    center_lon: base?.center_lon ?? null,
    radius_km: base?.radius_km ?? null,
  };
}
