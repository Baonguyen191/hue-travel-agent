import type { ReactNode } from "react";

const KIM = "var(--color-kim)";

/** Line art in son with kim accents, one per category; viewBox 96x72. */
const ART: Record<string, ReactNode> = {
  historic: (
    <>
      <path d="M8 64h80M14 64V40h68v24M10 40l38-20 38 20" />
      <path d="M38 64V52a10 10 0 0 1 20 0v12" />
      <path d="M34 24h28M40 18h16M48 18v-8" stroke={KIM} />
    </>
  ),
  religious: (
    <>
      <path d="M30 64h36M34 64V54h28v10M30 54l18-6 18 6M37 48v-8h22v8M33 40l15-5 15 5M40 35v-7h16v7M37 28l11-4 11 4" />
      <path d="M48 24V12" stroke={KIM} />
    </>
  ),
  restaurant: (
    <>
      <path d="M18 38h60a30 30 0 0 1-60 0z" />
      <path d="M60 10L46 38M70 12L52 38" stroke={KIM} />
      <path d="M36 28c-4-4 4-8 0-12M46 28c-4-4 4-8 0-12" />
    </>
  ),
  cafe: (
    <>
      <path d="M30 44h36v6a14 14 0 0 1-14 14h-8a14 14 0 0 1-14-14z" />
      <path d="M34 30h28l-4 14H38zM38 22h20v8H38z" />
      <path d="M22 66h52M66 48h4a6 6 0 0 1 0 12h-4" stroke={KIM} />
    </>
  ),
  market: (
    <>
      <path d="M14 50L48 18l34 32z" />
      <path d="M14 50q34 10 68 0M24 64h48" stroke={KIM} />
    </>
  ),
  park: (
    <>
      <path d="M6 50h84M10 50q12-18 24 0M34 50q14-18 28 0M62 50q12-18 24 0" />
      <path d="M8 62q6-4 12 0t12 0t12 0t12 0t12 0t12 0" stroke={KIM} />
    </>
  ),
  museum: (
    <>
      <path d="M14 30l34-16 34 16zM18 30h60M24 34v24M38 34v24M58 34v24M72 34v24M14 62h68" />
      <path d="M44 22h8" stroke={KIM} />
    </>
  ),
  default: (
    <>
      <path d="M48 58c-10-8-10-24 0-36 10 12 10 28 0 36zM48 58c-16-2-24-14-22-26 12 2 20 12 22 26zM48 58c16-2 24-14 22-26-12 2-20 12-22 26z" />
      <path d="M20 64h56" stroke={KIM} />
    </>
  ),
};

/** Decorative stand-in for a missing photo. Hidden from screen readers; callers add the name. */
export function PlaceIllustration({ category, className = "" }: { category: string | null; className?: string }) {
  const key = category && category in ART ? category : "default";
  return (
    <div
      aria-hidden="true"
      data-testid="place-illustration"
      data-category={key}
      className={`o-hoc flex items-center justify-center bg-kim-soft text-son ${className}`.trim()}
    >
      <svg
        viewBox="0 0 96 72"
        className="h-3/5 max-h-28 w-3/5"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {ART[key]}
      </svg>
    </div>
  );
}
