import type { PlaceCategory } from "../api/types";
import { CATEGORY_OPTIONS } from "../lib/labels";

interface CategoryChipsProps {
  value: PlaceCategory | null;
  onChange: (category: PlaceCategory | null) => void;
}

function chipClass(pressed: boolean): string {
  const base = "rounded-full border px-3 py-1.5 text-sm font-medium transition-colors";
  return pressed
    ? `${base} border-teal-700 bg-teal-700 text-white`
    : `${base} border-slate-300 bg-white text-slate-700 hover:border-teal-600`;
}

/** Single-choice category filter; "Tất cả" clears it. Each chip exposes aria-pressed. */
export function CategoryChips({ value, onChange }: CategoryChipsProps) {
  return (
    <div role="group" aria-label="Loại địa điểm" className="flex flex-wrap gap-2">
      <button
        type="button"
        aria-pressed={value === null}
        className={chipClass(value === null)}
        onClick={() => onChange(null)}
      >
        Tất cả
      </button>
      {CATEGORY_OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          className={chipClass(value === option.value)}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
