import { useEffect } from "react";

interface ToastProps {
  message: string;
  onDismiss: () => void;
  durationMs?: number;
}

/** Short confirmation that disappears by itself and can also be closed. */
export function Toast({ message, onDismiss, durationMs = 4000 }: ToastProps) {
  useEffect(() => {
    const timer = window.setTimeout(onDismiss, durationMs);
    return () => window.clearTimeout(timer);
  }, [message, onDismiss, durationMs]);

  return (
    <div
      role="status"
      className="fixed bottom-4 left-1/2 z-50 flex max-w-[calc(100vw-2rem)] -translate-x-1/2 items-center gap-3 rounded-full bg-muc px-4 py-2 text-sm text-on-son shadow-lg"
    >
      <span>{message}</span>
      <button type="button" onClick={onDismiss} aria-label="Đóng thông báo" className="rounded px-1 text-kim-soft hover:text-on-son">
        ×
      </button>
    </div>
  );
}
