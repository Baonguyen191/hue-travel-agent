import type { WarningSummary } from "../lib/plan";
import { Notice } from "./ui";

interface WarningsPanelProps {
  summary: WarningSummary;
}

/** Always visible on the plan page: nothing here is hidden, even when the list is empty. */
export function WarningsPanel({ summary }: WarningsPanelProps) {
  return (
    <Notice variant="warning" role="region" aria-labelledby="warnings-heading" className="space-y-3">
      <h2 id="warnings-heading" className="font-serif text-base font-semibold text-son">Cảnh báo và kiểm tra</h2>
      <p className={`text-sm font-medium ${summary.validationValid ? "text-reu" : "text-son"}`}>
        Kiểm tra lịch trình: {summary.validationValid ? "đạt" : "chưa đạt"}
      </p>
      {summary.validationMessages.length > 0 ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-son">
          {summary.validationMessages.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      ) : null}
      <p className="text-sm text-muc">
        Loại trừ: {summary.excluded} địa điểm · Gộp: {summary.merged} địa điểm · Chưa xếp: {summary.unplanned} địa điểm
      </p>
      {summary.messages.length > 0 ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-muc">
          {summary.messages.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muc">Máy chủ không báo cảnh báo nào.</p>
      )}
    </Notice>
  );
}
