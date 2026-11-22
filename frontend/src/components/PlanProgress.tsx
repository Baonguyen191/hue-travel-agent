import { useEffect, useState } from "react";
import { cardClass } from "./ui";

/** The graph nodes in run order (backend/app/agents/orchestrator.py). */
export const PIPELINE_STEPS: ReadonlyArray<{ node: string; label: string }> = [
  { node: "search", label: "Tìm địa điểm và phương tiện" },
  { node: "itinerary", label: "Xếp lịch trình theo ngày" },
  { node: "budget", label: "Tính ngân sách các phương án" },
  { node: "validate", label: "Kiểm tra lịch trình" },
  { node: "approval", label: "Lưu phiên bản chờ duyệt" },
];

const TRACE_LABEL: Record<string, string> = Object.fromEntries([
  ...PIPELINE_STEPS.map((step) => [step.node, step.label]),
  ["failed", "Dừng vì chưa đạt yêu cầu"],
]);

const STEP_INTERVAL_MS = 1200;

interface PlanProgressProps {
  /** True while the request is in flight; the step list animates only then. */
  active: boolean;
}

/** Loading panel: a static list of the graph steps, highlighted in turn while the plan is built. */
export function PlanProgress({ active }: PlanProgressProps) {
  const [current, setCurrent] = useState(0);

  useEffect(() => {
    if (!active) {
      setCurrent(0);
      return;
    }
    const timer = window.setInterval(() => {
      setCurrent((step) => Math.min(step + 1, PIPELINE_STEPS.length - 1));
    }, STEP_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [active]);

  if (!active) return null;

  return (
    <section aria-labelledby="progress-heading" role="status" className={cardClass("p-4")}>
      <h2 id="progress-heading" className="font-serif text-base font-semibold text-son">
        Đang tạo lịch trình…
      </h2>
      <p className="mt-1 text-sm text-muc-soft">Quá trình thường mất vài giây.</p>
      <ol className="mt-3 space-y-2 text-sm">
        {PIPELINE_STEPS.map((step, index) => {
          const done = index < current;
          const running = index === current;
          return (
            <li key={step.node} className="flex items-center gap-2" aria-current={running ? "step" : undefined}>
              <span
                aria-hidden="true"
                className={`flex size-5 items-center justify-center rounded-full text-xs font-bold ${
                  done ? "bg-kim text-muc" : running ? "animate-pulse bg-son text-on-son ring-2 ring-kim" : "bg-vien text-muc-soft"
                }`}
              >
                {done ? "✓" : index + 1}
              </span>
              <span className={running ? "font-semibold text-son" : "text-muc-soft"}>
                {step.label}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/** The steps the graph actually ran, from the server's trace (repeats appear on retries). */
export function TraceList({ trace }: { trace: string[] }) {
  if (trace.length === 0) return <p className="text-sm text-muc-soft">Máy chủ không trả về các bước đã chạy.</p>;
  return (
    <ol aria-label="Các bước đã chạy" className="flex flex-wrap items-center gap-1 text-sm text-muc-soft">
      {trace.map((node, index) => (
        <li key={`${node}-${index}`} className="flex items-center gap-1">
          {index > 0 ? <span aria-hidden="true" className="text-muc-soft">→</span> : null}
          <span className="rounded bg-nga px-2 py-0.5 ring-1 ring-vien">{TRACE_LABEL[node] ?? node}</span>
        </li>
      ))}
    </ol>
  );
}
