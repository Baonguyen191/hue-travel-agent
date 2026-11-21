import { useState } from "react";
import { api, errorMessage, isStale } from "../api/client";
import type { ApprovalResult, BudgetOption, CostItem, OptionLabel, TransportOffer, HotelOffer } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { formatVnd, formatVndRange } from "../lib/format";
import {
  SOURCE_TAG_CLASS,
  anyOptionFits,
  budgetStatusLabel,
  budgetStatusTone,
  budgetWarnings,
  optionLabelText,
  sourceTag,
  unitText,
} from "../lib/budget";
import { isApproved, isWaiting, type StatusTone } from "../lib/plan";
import { usePlan } from "./PlanLayout";

const TONE_CLASS: Record<StatusTone, string> = {
  approved: "bg-emerald-100 text-emerald-900 ring-emerald-300",
  waiting: "bg-amber-100 text-amber-900 ring-amber-300",
  failed: "bg-red-100 text-red-900 ring-red-300",
  neutral: "bg-slate-100 text-slate-800 ring-slate-300",
};

function transportText(offer: TransportOffer | null): string {
  return offer ? `${offer.provider} · ${formatVnd(offer.price_vnd)}` : "—";
}

function hotelText(hotel: HotelOffer | null): string {
  return hotel ? `${hotel.hotel_name} · ${formatVnd(hotel.price_per_room_night_vnd)}/đêm` : "—";
}

function remainingText(option: BudgetOption): string {
  if (option.budget_remaining_vnd === null) return "chưa rõ ngân sách";
  if (option.budget_remaining_vnd >= 0) return `còn ${formatVnd(option.budget_remaining_vnd)}`;
  return `vượt ${formatVnd(-option.budget_remaining_vnd)}`;
}

function CostItemRow({ item }: { item: CostItem }) {
  const tag = sourceTag(item);
  return (
    <li className="flex flex-col gap-1 border-t border-slate-100 py-2 text-sm sm:flex-row sm:items-start sm:justify-between sm:gap-3">
      <div className="min-w-0">
        <p className="font-medium text-slate-800">{item.label}</p>
        <p className="text-xs text-slate-600">
          {item.quantity} × {unitText(item.price_unit)}
        </p>
        {item.note ? <p className="text-xs text-slate-600">{item.note}</p> : null}
      </div>
      <div className="flex shrink-0 items-center gap-2 sm:flex-col sm:items-end">
        <span className="font-medium">{formatVndRange(item.amount_vnd, item.amount_max_vnd)}</span>
        <span
          title={tag.text === "MOCK" ? "MÔ PHỎNG: không phải giá thật" : undefined}
          className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ring-1 ${SOURCE_TAG_CLASS[tag.tone]}`}
        >
          {tag.text}
          {tag.text === "MOCK" ? " · MÔ PHỎNG" : ""}
        </span>
      </div>
    </li>
  );
}

export function BudgetTab() {
  const { threadId, record, reload } = usePlan();
  const budget = record.payload.budget;
  const waiting = isWaiting(record);
  const approved = isApproved(record);
  const [approving, setApproving] = useState<OptionLabel | null>(null);
  const [approveError, setApproveError] = useState<{ message: string; stale: boolean } | null>(null);
  const [localApproval, setLocalApproval] = useState<ApprovalResult | null>(null);
  const approval = record.checkpoint?.approval ?? localApproval;
  const fits = anyOptionFits(budget);
  const warnings = budgetWarnings(budget);

  async function approve(label: OptionLabel) {
    setApproving(label);
    setApproveError(null);
    try {
      const result = await api.approvePlan(threadId, { version: record.version, option: label });
      setLocalApproval(result);
      reload();
    } catch (error) {
      setApproveError({ message: errorMessage(error), stale: isStale(error) });
    } finally {
      setApproving(null);
    }
  }

  return (
    <div className="space-y-6">
      {!fits && budget.options.length > 0 ? (
        <section role="alert" aria-labelledby="shortfall-heading" className="space-y-2 rounded-lg border border-red-300 bg-red-50 p-4">
          <h2 id="shortfall-heading" className="text-base font-semibold text-red-900">
            Không phương án nào nằm trong ngân sách
          </h2>
          {budget.shortfall_vnd !== null ? (
            <p className="text-sm font-medium text-red-900">
              Thiếu {formatVnd(budget.shortfall_vnd)} so với ngân sách {formatVnd(record.payload.request.budget_vnd)}.
            </p>
          ) : null}
          {warnings.length > 0 ? (
            <ul className="list-disc space-y-1 pl-5 text-sm text-red-900">
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}

      {approved && approval ? (
        <section aria-labelledby="approved-heading" className="space-y-2 rounded-lg border border-emerald-300 bg-emerald-50 p-4">
          <h2 id="approved-heading" className="text-base font-semibold text-emerald-900">
            Đã duyệt phương án {optionLabelText(approval.option)}
          </h2>
          <p className="text-sm text-emerald-900">
            Phiên bản {approval.version} · mã báo giá <code className="break-all">{approval.quote_hash.slice(0, 16)}</code>
          </p>
          <ul className="text-sm text-emerald-900">
            {approval.selected_offers.map((offer) => (
              <li key={`${offer.kind}-${offer.id}-${offer.leg ?? ""}`}>
                {offer.kind === "TRANSPORT" ? `Xe ${offer.leg === "RETURN" ? "về" : "đi"}` : "Khách sạn"}: {offer.name} ·{" "}
                {formatVnd(offer.price)} ({unitText(offer.unit)})
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {waiting ? (
        <p className="text-sm text-slate-700">
          Chỉ phương án có nhãn mới duyệt được. Các phương án chưa có nhãn để bạn so sánh.
        </p>
      ) : null}

      {approveError ? (
        <div className="space-y-2">
          <ErrorBanner message={approveError.stale ? "Kế hoạch đã có phiên bản mới — tải lại để xem." : approveError.message} />
          {approveError.stale ? (
            <button type="button" onClick={reload} className="text-sm font-medium text-teal-800 underline">
              Tải lại kế hoạch
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="-mx-4 overflow-x-auto px-4">
        <table className="w-full min-w-[46rem] border-separate border-spacing-0 text-left text-sm">
          <caption className="sr-only">Các phương án ngân sách</caption>
          <thead>
            <tr className="text-xs uppercase tracking-wide text-slate-600">
              <th scope="col" className="border-b border-slate-200 py-2 pr-3 font-semibold">Phương án</th>
              <th scope="col" className="border-b border-slate-200 py-2 pr-3 font-semibold">Xe đi</th>
              <th scope="col" className="border-b border-slate-200 py-2 pr-3 font-semibold">Xe về</th>
              <th scope="col" className="border-b border-slate-200 py-2 pr-3 font-semibold">Khách sạn</th>
              <th scope="col" className="border-b border-slate-200 py-2 pr-3 font-semibold">Tổng (tham khảo)</th>
              <th scope="col" className="border-b border-slate-200 py-2 pr-3 font-semibold">Trạng thái</th>
              <th scope="col" className="border-b border-slate-200 py-2 font-semibold">Duyệt</th>
            </tr>
          </thead>
          <tbody>
            {budget.options.map((option, index) => {
              const statusClass = TONE_CLASS[budgetStatusTone(option.budget_status)];
              return (
                <tr key={`${option.label ?? "none"}-${index}`} className="align-top">
                  <td className="border-b border-slate-100 py-3 pr-3">
                    <p className="font-semibold">{optionLabelText(option.label)}</p>
                    {option.label === null ? <p className="text-xs text-slate-500">chưa có nhãn</p> : null}
                  </td>
                  <td className="border-b border-slate-100 py-3 pr-3">{transportText(option.transport_outbound)}</td>
                  <td className="border-b border-slate-100 py-3 pr-3">{transportText(option.transport_return)}</td>
                  <td className="border-b border-slate-100 py-3 pr-3">{hotelText(option.hotel)}</td>
                  <td className="border-b border-slate-100 py-3 pr-3">
                    <p className="font-medium">{formatVndRange(option.known_total_vnd, option.known_total_max_vnd)}</p>
                    <p className="text-xs text-slate-600">
                      {remainingText(option)} · {option.unknown_item_count} mục chưa rõ
                    </p>
                  </td>
                  <td className="border-b border-slate-100 py-3 pr-3">
                    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ${statusClass}`}>
                      {budgetStatusLabel(option.budget_status)}
                    </span>
                  </td>
                  <td className="border-b border-slate-100 py-3">
                    {option.label !== null && waiting ? (
                      <button
                        type="button"
                        disabled={approving !== null}
                        onClick={() => approve(option.label as OptionLabel)}
                        className="rounded-md bg-teal-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-teal-800 disabled:opacity-50"
                      >
                        {approving === option.label ? "Đang duyệt…" : `Duyệt ${optionLabelText(option.label)}`}
                      </button>
                    ) : (
                      <span className="text-xs text-slate-500">
                        {option.label === null ? "Không thể duyệt" : approved ? "" : "Không chờ duyệt"}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <section aria-labelledby="items-heading" className="space-y-3">
        <h2 id="items-heading" className="text-base font-semibold">
          Chi tiết chi phí
        </h2>
        {budget.options.map((option, index) => (
          <details key={`items-${index}`} className="rounded-lg border border-slate-200 bg-white p-4">
            <summary className="cursor-pointer text-sm font-semibold">
              Phương án {optionLabelText(option.label)} · {option.items.length} mục
            </summary>
            {option.items.length === 0 ? (
              <p className="pt-2 text-sm text-slate-600">Không có mục chi phí.</p>
            ) : (
              <ul className="pt-2">
                {option.items.map((item, itemIndex) => (
                  <CostItemRow key={`${item.code}-${itemIndex}`} item={item} />
                ))}
              </ul>
            )}
            {option.warnings.length > 0 ? (
              <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-amber-900">
                {option.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}
          </details>
        ))}
      </section>

      <p className="text-xs text-slate-600">
        Mọi giá là tham khảo; đơn vị của giá nguồn chưa rõ. Mục MOCK là đặt chỗ mô phỏng.
      </p>
    </div>
  );
}
