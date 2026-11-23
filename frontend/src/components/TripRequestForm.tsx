import { useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import type { PlaceCategory } from "../api/types";
import { Notice, buttonClass } from "./ui";
import { formatVnd } from "../lib/format";
import { CATEGORY_OPTIONS } from "../lib/labels";
import {
  MAX_PEOPLE,
  MAX_PREFERENCES,
  MAX_ROOMS,
  missingFormFields,
  validateValues,
  type FieldErrors,
  type FormField,
  type FormValues,
} from "../lib/tripForm";

interface TripRequestFormProps {
  initial: FormValues;
  /** API names from the parser's missing_fields; these fields are highlighted until they are valid. */
  missing?: string[];
  submitLabel: string;
  pending?: boolean;
  onSubmit: (values: FormValues) => void;
}

const INPUT =
  "mt-1 w-full rounded-xl border bg-nga px-3 py-2 text-base text-muc focus:outline-none focus:ring-2 focus:ring-son/30 disabled:bg-giay";
const INPUT_OK = `${INPUT} border-vien focus:border-son`;
const INPUT_BAD = `${INPUT} border-son focus:border-son`;

interface FieldProps {
  id: string;
  label: string;
  error?: string;
  hint?: ReactNode;
  children: ReactNode;
}

function Field({ id, label, error, hint, children }: FieldProps) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-muc">
        {label}
      </label>
      {children}
      {error ? (
        <p id={`${id}-error`} className="mt-1 text-sm font-medium text-son">
          {error}
        </p>
      ) : hint ? (
        <p className="mt-1 text-xs text-muc-soft">{hint}</p>
      ) : null}
    </div>
  );
}

/**
 * The trip form used on the request screen and, in step 4, to edit a plan. Errors show for a
 * field once it is touched, or immediately when the parser reported it missing.
 */
export function TripRequestForm({ initial, missing = [], submitLabel, pending = false, onSubmit }: TripRequestFormProps) {
  const [values, setValues] = useState<FormValues>(initial);
  const [touched, setTouched] = useState<Partial<Record<FormField, boolean>>>({});
  const [preferenceDraft, setPreferenceDraft] = useState("");
  const errors: FieldErrors = validateValues(values);
  const missingSet = new Set<FormField>(missingFormFields(missing));
  const valid = Object.keys(errors).length === 0;

  function update<K extends keyof FormValues>(key: K, value: FormValues[K]) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  function touch(field: FormField) {
    setTouched((current) => (current[field] ? current : { ...current, [field]: true }));
  }

  /** An error is shown when the field was touched or the parser said it was missing. */
  function shownError(field: FormField): string | undefined {
    const error = errors[field];
    if (!error) return undefined;
    return touched[field] || missingSet.has(field) ? error : undefined;
  }

  function invalid(field: FormField): boolean {
    return shownError(field) !== undefined;
  }

  function addPreference() {
    const text = preferenceDraft.trim();
    setPreferenceDraft("");
    if (text === "" || values.preferences.includes(text) || values.preferences.length >= MAX_PREFERENCES) return;
    update("preferences", [...values.preferences, text]);
  }

  function onPreferenceKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      addPreference();
    }
  }

  function toggleCategory(category: PlaceCategory) {
    const next = values.categories.includes(category)
      ? values.categories.filter((item) => item !== category)
      : [...values.categories, category];
    update("categories", next);
  }

  const missingLabels = (["origin", "startDate", "endDate", "people", "rooms", "budget"] as FormField[])
    .filter((field) => missingSet.has(field) && errors[field])
    .map((field) => FIELD_NAMES[field]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid || pending) return;
    onSubmit(values);
  }

  const budgetNumber = Number(values.budget);
  const budgetHint =
    values.budget.trim() !== "" && Number.isInteger(budgetNumber) && budgetNumber > 0
      ? `Tương đương ${formatVnd(budgetNumber)}. Ngân sách là ước tính để so sánh các phương án.`
      : "Có thể để trống nếu chưa có ngân sách.";

  return (
    <form onSubmit={submit} noValidate className="space-y-6">
      <fieldset disabled={pending} className="space-y-6">
        <legend className="sr-only">Thông tin chuyến đi</legend>

        {missingLabels.length > 0 ? (
          <Notice variant="error" role="note">
            Còn thiếu: {missingLabels.join(", ")}. Hãy điền các mục này trước khi tạo lịch trình.
          </Notice>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="trip-origin" label="Điểm xuất phát" error={shownError("origin")}>
            <input
              id="trip-origin"
              type="text"
              value={values.origin}
              maxLength={120}
              autoComplete="off"
              aria-invalid={invalid("origin")}
              aria-describedby={shownError("origin") ? "trip-origin-error" : undefined}
              onChange={(event) => update("origin", event.target.value)}
              onBlur={() => touch("origin")}
              className={invalid("origin") ? INPUT_BAD : INPUT_OK}
            />
          </Field>

          <Field id="trip-destination" label="Điểm đến" error={shownError("destination")}>
            <input
              id="trip-destination"
              type="text"
              value={values.destination}
              maxLength={120}
              autoComplete="off"
              aria-invalid={invalid("destination")}
              onChange={(event) => update("destination", event.target.value)}
              onBlur={() => touch("destination")}
              className={invalid("destination") ? INPUT_BAD : INPUT_OK}
            />
          </Field>

          <Field id="trip-start" label="Ngày đi" error={shownError("startDate")}>
            <input
              id="trip-start"
              type="date"
              value={values.startDate}
              aria-invalid={invalid("startDate")}
              onChange={(event) => update("startDate", event.target.value)}
              onBlur={() => touch("startDate")}
              className={invalid("startDate") ? INPUT_BAD : INPUT_OK}
            />
          </Field>

          <Field id="trip-end" label="Ngày về" error={shownError("endDate")}>
            <input
              id="trip-end"
              type="date"
              value={values.endDate}
              aria-invalid={invalid("endDate")}
              onChange={(event) => update("endDate", event.target.value)}
              onBlur={() => touch("endDate")}
              className={invalid("endDate") ? INPUT_BAD : INPUT_OK}
            />
          </Field>

          <Field id="trip-people" label="Số người" error={shownError("people")} hint={`Từ 1 đến ${MAX_PEOPLE} người.`}>
            <input
              id="trip-people"
              type="number"
              inputMode="numeric"
              min={1}
              max={MAX_PEOPLE}
              value={values.people}
              aria-invalid={invalid("people")}
              onChange={(event) => update("people", event.target.value)}
              onBlur={() => touch("people")}
              className={invalid("people") ? INPUT_BAD : INPUT_OK}
            />
          </Field>

          <Field id="trip-rooms" label="Số phòng" error={shownError("rooms")} hint={`Từ 1 đến ${MAX_ROOMS} phòng.`}>
            <input
              id="trip-rooms"
              type="number"
              inputMode="numeric"
              min={1}
              max={MAX_ROOMS}
              value={values.rooms}
              aria-invalid={invalid("rooms")}
              onChange={(event) => update("rooms", event.target.value)}
              onBlur={() => touch("rooms")}
              className={invalid("rooms") ? INPUT_BAD : INPUT_OK}
            />
          </Field>

          <div className="sm:col-span-2">
            <Field id="trip-budget" label="Ngân sách (VND)" error={shownError("budget")} hint={budgetHint}>
              <input
                id="trip-budget"
                type="number"
                inputMode="numeric"
                min={1}
                step={100000}
                value={values.budget}
                aria-invalid={invalid("budget")}
                onChange={(event) => update("budget", event.target.value)}
                onBlur={() => touch("budget")}
                className={invalid("budget") ? INPUT_BAD : INPUT_OK}
              />
            </Field>
          </div>
        </div>

        <div className="space-y-2">
          <label htmlFor="trip-preference" className="block text-sm font-medium text-muc">
            Sở thích
          </label>
          <div className="flex gap-2">
            <input
              id="trip-preference"
              type="text"
              value={preferenceDraft}
              placeholder="ví dụ: di tích, đặc sản"
              onChange={(event) => setPreferenceDraft(event.target.value)}
              onKeyDown={onPreferenceKey}
              className={INPUT_OK}
            />
            <button
              type="button"
              onClick={addPreference}
              disabled={values.preferences.length >= MAX_PREFERENCES}
              className={`${buttonClass("outline", "sm")} mt-1 shrink-0`}
            >
              Thêm
            </button>
          </div>
          {values.preferences.length > 0 ? (
            <ul aria-label="Sở thích đã chọn" className="flex flex-wrap gap-2">
              {values.preferences.map((preference) => (
                <li
                  key={preference}
                  className="flex items-center gap-1 rounded-full bg-kim-soft py-1 pl-3 pr-1 text-sm text-son"
                >
                  {preference}
                  <button
                    type="button"
                    aria-label={`Xóa sở thích ${preference}`}
                    onClick={() => update("preferences", values.preferences.filter((item) => item !== preference))}
                    className="flex size-6 items-center justify-center rounded-full hover:bg-vien"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          {shownError("preferences") ? (
            <p className="text-sm font-medium text-son">{shownError("preferences")}</p>
          ) : null}
        </div>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-muc">Loại địa điểm ưu tiên (tùy chọn)</legend>
          <div className="flex flex-wrap gap-2">
            {CATEGORY_OPTIONS.map((option) => {
              const checked = values.categories.includes(option.value);
              return (
                <label
                  key={option.value}
                  className={`cursor-pointer rounded-full border px-3 py-1.5 text-sm font-medium has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-kim ${
                    checked ? "border-kim bg-kim text-muc" : "border-vien bg-nga text-muc-soft"
                  }`}
                >
                  <input
                    type="checkbox"
                    className="sr-only"
                    checked={checked}
                    onChange={() => toggleCategory(option.value)}
                  />
                  {option.label}
                </label>
              );
            })}
          </div>
        </fieldset>

        <div className="flex flex-col gap-2 border-t border-vien pt-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-muc-soft">
            {valid ? "Sẵn sàng tạo lịch trình." : "Nhập đủ thông tin bắt buộc để tạo lịch trình."}
          </p>
          <button
            type="submit"
            disabled={!valid || pending}
            className={buttonClass("primary")}
          >
            {submitLabel}
          </button>
        </div>
      </fieldset>
    </form>
  );
}

const FIELD_NAMES: Record<FormField, string> = {
  origin: "điểm xuất phát",
  destination: "điểm đến",
  startDate: "ngày đi",
  endDate: "ngày về",
  people: "số người",
  rooms: "số phòng",
  budget: "ngân sách",
  preferences: "sở thích",
};
