import type { ReactNode } from "react";

type Level = "h1" | "h2" | "h3" | "h4";

const SIZE: Record<Level, string> = {
  h1: "text-2xl md:text-3xl",
  h2: "text-lg md:text-xl",
  h3: "text-base md:text-lg",
  h4: "text-base",
};

export function SectionHeading({
  as = "h2",
  id,
  className = "",
  children,
}: {
  as?: Level;
  id?: string;
  className?: string;
  children: ReactNode;
}) {
  const Tag = as;
  return (
    <Tag id={id} className={`font-serif font-semibold leading-snug text-son ${SIZE[as]} ${className}`.trim()}>
      {children}
    </Tag>
  );
}
