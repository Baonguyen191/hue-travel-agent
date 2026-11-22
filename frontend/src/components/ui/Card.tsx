import type { HTMLAttributes } from "react";
import { Ornament } from "./Ornament";

export function cardClass(extra = ""): string {
  return `overflow-hidden rounded-2xl border border-vien bg-nga shadow-[0_1px_3px_rgb(43_26_18/0.06)] ${extra}`.trim();
}

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Draw the hồi văn band along the top edge. */
  ornament?: boolean;
}

export function Card({ ornament = false, className = "", children, ...rest }: CardProps) {
  return (
    <div className={cardClass(className)} {...rest}>
      {ornament ? <Ornament /> : null}
      {children}
    </div>
  );
}
