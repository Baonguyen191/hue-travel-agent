import type { HTMLAttributes } from "react";

export type NoticeVariant = "warning" | "error" | "success";

const VARIANT: Record<NoticeVariant, string> = {
  warning: "border-kim bg-canh-bao",
  error: "border-son bg-son-soft",
  success: "border-reu bg-reu-soft",
};

interface NoticeProps extends HTMLAttributes<HTMLDivElement> {
  variant: NoticeVariant;
}

/** A bar notice: coloured left border, muc text. Pass role="alert" or role="status" where needed. */
export function Notice({ variant, className = "", children, ...rest }: NoticeProps) {
  return (
    <div className={`rounded-md border-l-4 px-4 py-3 text-sm text-muc ${VARIANT[variant]} ${className}`.trim()} {...rest}>
      {children}
    </div>
  );
}
