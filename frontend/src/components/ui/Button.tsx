import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "outline";
export type ButtonSize = "sm" | "md";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-son text-on-son hover:bg-son-dark",
  secondary: "bg-kim text-muc hover:brightness-95",
  outline: "border-[1.5px] border-son bg-transparent text-son hover:bg-son-soft",
};

const SIZE: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5 text-sm",
  md: "px-5 py-2.5 text-base",
};

/** Class string for anything that should look like a button (buttons, links, NavLinks). */
export function buttonClass(variant: ButtonVariant = "primary", size: ButtonSize = "md"): string {
  return [
    "inline-flex items-center justify-center gap-2 rounded-full font-semibold transition-colors",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-son",
    "disabled:cursor-not-allowed disabled:opacity-50",
    VARIANT[variant],
    SIZE[size],
  ].join(" ");
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function Button({ variant = "primary", size = "md", className = "", type = "button", ...rest }: ButtonProps) {
  return <button type={type} className={`${buttonClass(variant, size)} ${className}`.trim()} {...rest} />;
}
