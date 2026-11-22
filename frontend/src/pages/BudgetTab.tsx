import { useState } from "react";
import { api, errorMessage, isStale } from "../api/client";
import type { ApprovalResult, BudgetOption, CostItem, OptionLabel, TransportOffer, HotelOffer } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { LINK, Notice, PILL, TONE_CLASS, buttonClass, cardClass } from "../components/ui";
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
import { isApproved, isWaiting } from "../lib/plan";
import { translateWarning, translateWarnings } from "../lib/warnings";
import { usePlan } from "./PlanLayout";

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
    <li className="flex flex-col gap-1 py-2 text-sm sm:flex-row sm:items-start sm:justify-between sm:gap-3">
      <div className="min-w-0">
        <p className="font-medium text-muc">{item.label}</p>
        <p className="text-xs text-muc-soft">
          {item.quantity} × {unitText(item.price_unit)}
        </p>
        {item.note ? <p className="text-xs text-muc-soft">{translateWarning(item.note)}</p> : null}
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

  /** Approve only labelled options while waiting; unlabelled options are for comparison only. */
  function approveControl(option: BudgetOption) {
    if (option.label !== null && waiting) {
      return (
        <button
          type="button"
          disabled={approving !== null}
          onClick={() => approve(option.label as OptionLabel)}
          className={buttonClass("primary", "sm")}
        >
          {approving === option.label ? "Đang duyệt…" : `Duyệt ${optionLabelText(option.label)}`}
        </button>
      );
    }
    return (
      <span className="text-xs text-muc-soft">{option.label === null ? "Không thể duyệt" : approved ? "" : "Không chờ duyệt"}</span>
    );
  }

  return (
    <div className="space-y-6">
      {!fits && budget.options.length > 0 ? (
        <Notice variant="error" role="alert" aria-labelledby="shortfall-heading" className="space-y-2">
          <h2 id="shortfall-heading" className="font-serif text-base font-semibold text-son">
            Không phương án nào nằm trong ngân sách
          </h2>
          {budget.shortfall_vnd !== null ? (
            <p className="text-sm font-medium text-muc">
              Thiếu {formatVnd(budget.shortfall_vnd)} so với ngân sách {formatVnd(record.payload.request.budget_vnd)}.
            </p>
          ) : null}
          {warnings.length > 0 ? (
            <ul className="list-disc space-y-1 pl-5 text-sm text-muc">
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}
        </Notice>
      ) : null}

      {approved && approval ? (
        <Notice variant="success" role="region" aria-labelledby="approved-heading" className="space-y-2">
          <h2 id="approved-heading" className="font-serif text-base font-semibold text-reu">
            Đã duyệt phương án {optionLabelText(approval.option)}
          </h2>
          <p className="text-sm text-muc">
            Phiên bản {approval.version} · mã báo giá <code className="break-all">{approval.quote_hash.slice(0, 16)}</code>
          </p>
          <ul className="text-sm text-muc">
            {approval.selected_offers.map((offer) => (
              <li key={`${offer.kind}-${offer.id}-${offer.leg ?? ""}`}>
                {offer.kind === "TRANSPORT" ? `Xe ${offer.leg === "RETURN" ? "về" : "đi"}` : "Khách sạn"}: {offer.name} ·{" "}
                {formatVnd(offer.price)} ({unitText(offer.unit)})
              </li>
            ))}
          </ul>
        </Notice>
      ) : null}

      {waiting ? (
        <p className="text-sm text-muc-soft">
          Chỉ phương án có nhãn mới duyệt được. Các phương án chưa có nhãn để bạn so sánh.
        </p>
      ) : null}

      {approveError ? (
        <div className="space-y-2">
          <ErrorBanner message={approveError.stale ? "Kế hoạch đã có phiên bản mới — tải lại để xem." : approveError.message} />
          {approveError.stale ? (
            <button type="button" onClick={reload} className={`text-sm ${LINK}`}>
              Tải lại kế hoạch
            </button>
          ) : null}
        </div>
      ) : null}

      {/* Below md: one card per option, with the approve control always in view. */}
      <ul aria-label="Các phương án ngân sách" className="grid gap-3 md:hidden">
        {budget.options.map((option, index) => (
          <li key={`card-${option.label ?? "none"}-${index}`} className={`space-y-3 ${cardClass("p-4")}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-serif font-semibold text-son">Phương án {optionLabelText(option.label)}</p>
              <span className={`${PILL} ${TONE_CLASS[budgetStatusTone(option.budget_status)]}`}>
                {budgetStatusLabel(option.budget_status)}
              </span>
            </div>
            <div>
              <p className="text-xs text-muc-soft">Tổng (tham khảo)</p>
              <p className="font-medium">{formatVndRange(option.known_total_vnd, option.known_total_max_vnd)}</p>
              <p className="text-xs text-muc-soft">
                {remainingText(option)} · {option.unknown_item_count} mục chưa rõ
              </p>
            </div>
            <dl className="space-y-1 text-sm">
              <div>
                <dt className="inline text-muc-soft">Xe đi: </dt>
                <dd className="inline">{transportText(option.transport_outbound)}</dd>
              </div>
              <div>
                <dt className="inline text-muc-soft">Xe về: </dt>
                <dd className="inline">{transportText(option.transport_return)}</dd>
              </div>
              <div>
                <dt className="inline text-muc-soft">Khách sạn: </dt>
                <dd className="inline">{hotelText(option.hotel)}</dd>
              </div>
            </dl>
            <div>{approveControl(option)}</div>
          </li>
        ))}
      </ul>

      {/* md and up: the comparison table. */}
      <div className="hidden md:block">
        <table className="w-full border-separate border-spacing-0 text-left text-sm">
          <caption className="sr-only">Các phương án ngân sách</caption>
          <thead>
            <tr className="text-xs uppercase tracking-wide text-muc-soft">
              <th scope="col" className="border-b border-vien py-2 pr-3 font-semibold">Phương án</th>
              <th scope="col" className="border-b border-vien py-2 pr-3 font-semibold">Xe đi</th>
              <th scope="col" className="border-b border-vien py-2 pr-3 font-semibold">Xe về</th>
              <th scope="col" className="border-b border-vien py-2 pr-3 font-semibold">Khách sạn</th>
              <th scope="col" className="border-b border-vien py-2 pr-3 font-semibold">Tổng (tham khảo)</th>
              <th scope="col" className="border-b border-vien py-2 pr-3 font-semibold">Trạng thái</th>
              <th scope="col" className="border-b border-vien py-2 font-semibold">Duyệt</th>
            </tr>
          </thead>
          <tbody>
            {budget.options.map((option, index) => (
              <tr key={`${option.label ?? "none"}-${index}`} className="align-top">
                <td className="border-b border-vien py-3 pr-3">
                  <p className="font-semibold">{optionLabelText(option.label)}</p>
                  {option.label === null ? <p className="text-xs text-muc-soft">chưa có nhãn</p> : null}
                </td>
                <td className="border-b border-vien py-3 pr-3">{transportText(option.transport_outbound)}</td>
                <td className="border-b border-vien py-3 pr-3">{transportText(option.transport_return)}</td>
                <td className="border-b border-vien py-3 pr-3">{hotelText(option.hotel)}</td>
                <td className="border-b border-vien py-3 pr-3">
                  <p className="font-medium">{formatVndRange(option.known_total_vnd, option.known_total_max_vnd)}</p>
                  <p className="text-xs text-muc-soft">
                    {remainingText(option)} · {option.unknown_item_count} mục chưa rõ
                  </p>
                </td>
                <td className="border-b border-vien py-3 pr-3">
                  <span className={`${PILL} ${TONE_CLASS[budgetStatusTone(option.budget_status)]}`}>
                    {budgetStatusLabel(option.budget_status)}
                  </span>
                </td>
                <td className="border-b border-vien py-3">{approveControl(option)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section aria-labelledby="items-heading" className="space-y-3">
        <h2 id="items-heading" className="font-serif text-base font-semibold text-son">
          Chi tiết chi phí
        </h2>
        {budget.options.map((option, index) => (
          <details key={`items-${index}`} className={cardClass("p-4")}>
            <summary className="cursor-pointer text-sm font-semibold text-muc">
              Phương án {optionLabelText(option.label)} · {option.items.length} mục
            </summary>
            {option.items.length === 0 ? (
              <p className="pt-2 text-sm text-muc-soft">Không có mục chi phí.</p>
            ) : (
              <ul className="divide-y divide-vien pt-2">
                {option.items.map((item, itemIndex) => (
                  <CostItemRow key={`${item.code}-${itemIndex}`} item={item} />
                ))}
              </ul>
            )}
            {option.warnings.length > 0 ? (
              <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-muc-soft">
                {translateWarnings(option.warnings).map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}
          </details>
        ))}
      </section>

      <p className="text-xs text-muc-soft">
        Mọi giá là tham khảo; đơn vị của giá nguồn chưa rõ. Mục MOCK là đặt chỗ mô phỏng.
      </p>
    </div>
  );
}
