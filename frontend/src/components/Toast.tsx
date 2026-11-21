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
      className="fixed bottom-4 left-1/2 z-50 flex max-w-[calc(100vw-2rem)] -translate-x-1/2 items-center gap-3 rounded-md bg-slate-900 px-4 py-3 text-sm text-white shadow-lg"
    >
      <span>{message}</span>
      <button type="button" onClick={onDismiss} aria-label="Đóng thông báo" className="rounded px-1 text-slate-300 hover:text-white">
        ×
      </button>
    </div>
  );
}
