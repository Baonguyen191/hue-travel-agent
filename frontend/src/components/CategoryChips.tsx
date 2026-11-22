import type { PlaceCategory } from "../api/types";
import { CATEGORY_OPTIONS } from "../lib/labels";

interface CategoryChipsProps {
  value: PlaceCategory | null;
  onChange: (category: PlaceCategory | null) => void;
}

function chipClass(pressed: boolean): string {
  const base = "rounded-full px-3 py-1.5 text-sm font-medium ring-1 transition-colors";
  return pressed ? `${base} bg-son text-on-son ring-son` : `${base} bg-nga text-son ring-vien hover:ring-kim`;
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
