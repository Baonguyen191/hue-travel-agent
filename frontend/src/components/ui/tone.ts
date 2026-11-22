import type { StatusTone } from "../../lib/plan";

/** Status pill colours shared by the chat cards, plan header, budget and booking tabs. */
export const TONE_CLASS: Record<StatusTone, string> = {
  approved: "bg-reu-soft text-reu ring-reu/30",
  waiting: "bg-canh-bao text-muc ring-kim/50",
  failed: "bg-son-soft text-son ring-son/30",
  neutral: "bg-nga text-muc-soft ring-vien",
};

export const PILL = "inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1";

/** Inline text link: son text, kim underline. */
export const LINK = "font-medium text-son underline decoration-kim underline-offset-2 hover:text-son-dark";
