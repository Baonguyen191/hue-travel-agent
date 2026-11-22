import type { ReactNode } from "react";
import { CATEGORY_LABEL } from "../../lib/labels";

export type ChipTone = "son" | "soft" | "reu" | "neutral";

const TONE: Record<ChipTone, string> = {
  son: "bg-son text-on-son",
  soft: "bg-kim-soft text-son",
  reu: "bg-reu-soft text-reu",
  neutral: "bg-nga text-muc-soft ring-1 ring-vien",
};

export function Chip({ tone = "soft", children, className = "" }: { tone?: ChipTone; children: ReactNode; className?: string }) {
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${TONE[tone]} ${className}`.trim()}>
      {children}
    </span>
  );
}

const CATEGORY_TONE: Record<string, ChipTone> = {
  historic: "son",
  religious: "son",
  museum: "son",
  restaurant: "soft",
  cafe: "soft",
  market: "soft",
  park: "reu",
  attraction: "reu",
};

/** A chip with the Vietnamese category label; unknown categories show their code. */
export function CategoryChip({ category, className }: { category: string | null; className?: string }) {
  if (!category) return null;
  const label = CATEGORY_LABEL[category as keyof typeof CATEGORY_LABEL] ?? category;
  return (
    <Chip tone={CATEGORY_TONE[category] ?? "neutral"} className={className}>
      {label}
    </Chip>
  );
}
