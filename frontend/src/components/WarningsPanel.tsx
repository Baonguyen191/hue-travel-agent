import type { WarningSummary } from "../lib/plan";

interface WarningsPanelProps {
  summary: WarningSummary;
}

/** Always visible on the plan page: nothing here is hidden, even when the list is empty. */
export function WarningsPanel({ summary }: WarningsPanelProps) {
  return (
    <section aria-label="Cảnh báo và kiểm tra" className="space-y-3 rounded-lg border border-amber-300 bg-amber-50 p-4">
      <h2 className="text-sm font-semibold text-amber-900">Cảnh báo và kiểm tra</h2>
      <p className={`text-sm font-medium ${summary.validationValid ? "text-emerald-800" : "text-red-800"}`}>
        Kiểm tra lịch trình: {summary.validationValid ? "đạt" : "chưa đạt"}
      </p>
      {summary.validationMessages.length > 0 ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-red-800">
          {summary.validationMessages.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      ) : null}
      <p className="text-sm text-amber-900">
        Loại trừ: {summary.excluded} địa điểm · Gộp: {summary.merged} địa điểm · Chưa xếp: {summary.unplanned} địa điểm
      </p>
      {summary.messages.length > 0 ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-amber-900">
          {summary.messages.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-amber-900">Máy chủ không báo cảnh báo nào.</p>
      )}
    </section>
  );
}
