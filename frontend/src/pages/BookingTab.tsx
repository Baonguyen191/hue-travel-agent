import { useState } from "react";
import { api, errorMessage } from "../api/client";
import type { BookingItem, BookingResult } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { LINK, MockBadge, Notice, PILL, TONE_CLASS, buttonClass, cardClass } from "../components/ui";
import { formatVnd } from "../lib/format";
import {
  bookingStatusLabel,
  bookingStatusTone,
  idempotencyKeyFor,
  loadStoredResult,
  needsRecheck,
  saveStoredResult,
} from "../lib/booking";
import { effectiveStatus, isApproved, poiNameIndex, statusLabel } from "../lib/plan";
import { usePlan } from "./PlanLayout";

const KIND_VN: Record<BookingItem["kind"], string> = { TRANSPORT: "Xe", HOTEL: "Khách sạn", POI: "Điểm đến" };

function ServiceRow({ item, offerName }: { item: BookingItem; offerName: string }) {
  return (
    <tr className="align-top">
      <th scope="row" className="border-b border-vien py-2 pr-3 text-left font-medium">
        {KIND_VN[item.kind]}
        <p className="text-xs font-normal text-muc-soft">{offerName}</p>
      </th>
      <td className="border-b border-vien py-2 pr-3">
        <span className={`${PILL} ${TONE_CLASS[bookingStatusTone(item.status)]}`}>
          {bookingStatusLabel(item.status)}
        </span>
      </td>
      <td className="border-b border-vien py-2 pr-3">
        {item.reference ? (
          <span className="flex flex-wrap items-center gap-1">
            <code className="break-all text-xs">{item.reference}</code>
            {item.source === "MOCK" ? (
              <MockBadge />
            ) : null}
          </span>
        ) : (
          <span className="text-xs text-muc-soft">chưa có mã</span>
        )}
      </td>
      <td className="border-b border-vien py-2 pr-3">{item.price_vnd === null ? "—" : formatVnd(item.price_vnd)}</td>
      <td className="border-b border-vien py-2 text-xs text-muc-soft">{item.message ?? ""}</td>
    </tr>
  );
}

export function BookingTab() {
  const { threadId, record } = usePlan();
  const approved = isApproved(record);
  const approval = record.checkpoint?.approval ?? null;
  const quoteHash = approval?.quote_hash ?? null;
  const offerNames = new Map((approval?.selected_offers ?? []).map((offer) => [offer.id, offer.name]));
  const poiNames = poiNameIndex(record);
  const [stored, setStored] = useState<BookingResult | null>(() => loadStoredResult(threadId));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A stored result belongs to the quote it was made for; a newer approval shows nothing until booked again.
  const result = stored && quoteHash && stored.quote_hash === quoteHash ? stored : null;

  async function book() {
    if (!quoteHash) return;
    setBusy(true);
    setError(null);
    try {
      const key = idempotencyKeyFor(threadId, quoteHash);
      const next = await api.bookPlan(threadId, { idempotency_key: key });
      saveStoredResult(threadId, next);
      setStored(next);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  const disabledReason = approved ? null : "Chỉ đặt được sau khi phương án đã được duyệt.";

  return (
    <div className="space-y-6">
      <section aria-labelledby="book-heading" className={`space-y-3 ${cardClass("p-4 sm:p-6")}`}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 id="book-heading" className="font-serif text-base font-semibold text-son">
              Đặt chỗ mô phỏng
            </h2>
            <p className="text-sm text-muc-soft">
              Chỉ xe và khách sạn trong phương án đã duyệt được đặt, và đây là đặt chỗ MÔ PHỎNG. Trạng thái: {statusLabel(effectiveStatus(record))}.
            </p>
          </div>
          <button
            type="button"
            onClick={book}
            disabled={!approved || busy}
            title={disabledReason ?? "Đặt chỗ mô phỏng cho phương án đã duyệt"}
            className={`shrink-0 ${buttonClass("primary", "md")}`}
          >
            {busy ? "Đang đặt…" : "Đặt MÔ PHỎNG"}
          </button>
        </div>
        {disabledReason ? <p className="text-sm text-muc-soft">{disabledReason}</p> : null}
        {error ? <ErrorBanner message={error} /> : null}
      </section>

      {result ? (
        <section aria-labelledby="result-heading" className={`space-y-5 ${cardClass("p-4 sm:p-6")}`}>
          <div className="flex flex-wrap items-center gap-2">
            <h2 id="result-heading" className="font-serif text-base font-semibold text-son">
              Kết quả đặt chỗ
            </h2>
            <span className={`${PILL} ${TONE_CLASS[bookingStatusTone(result.status)]}`}>
              {bookingStatusLabel(result.status)}
            </span>
            <span className="text-xs text-muc-soft">
              Phiên bản {result.plan_version} · báo giá <code>{result.quote_hash.slice(0, 12)}</code>
            </span>
          </div>

          {/* Below md: one card per service. */}
          <ul aria-label="Xe và khách sạn đã đặt" className="space-y-3 md:hidden">
            {result.items
              .filter((item) => item.kind !== "POI")
              .map((item) => {
                const offerName = offerNames.get(item.offer_id ?? "") ?? item.offer_id ?? "";
                return (
                  <li key={`card-${item.kind}-${item.offer_id ?? ""}`} className="space-y-2 rounded-xl border border-vien bg-giay p-4 text-sm">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="font-semibold">
                        {KIND_VN[item.kind]}
                        <span className="block text-xs font-normal text-muc-soft">{offerName}</span>
                      </p>
                      <span className={`${PILL} ${TONE_CLASS[bookingStatusTone(item.status)]}`}>
                        {bookingStatusLabel(item.status)}
                      </span>
                    </div>
                    {item.reference ? (
                      <p className="flex flex-wrap items-center gap-1">
                        <code className="break-all text-xs">{item.reference}</code>
                        {item.source === "MOCK" ? (
                          <MockBadge />
                        ) : null}
                      </p>
                    ) : (
                      <p className="text-xs text-muc-soft">chưa có mã</p>
                    )}
                    <p>Giá: {item.price_vnd === null ? "—" : formatVnd(item.price_vnd)}</p>
                    {item.message ? <p className="text-xs text-muc-soft">{item.message}</p> : null}
                  </li>
                );
              })}
          </ul>
          <div className="hidden md:block -mx-4 overflow-x-auto px-4">
            <table className="w-full min-w-[40rem] text-left text-sm">
              <caption className="sr-only">Xe và khách sạn đã đặt</caption>
              <thead>
                <tr className="text-xs uppercase tracking-wide text-muc-soft">
                  <th scope="col" className="border-b border-vien py-2 pr-3 font-semibold">Dịch vụ</th>
                  <th scope="col" className="border-b border-vien py-2 pr-3 font-semibold">Trạng thái</th>
                  <th scope="col" className="border-b border-vien py-2 pr-3 font-semibold">Mã đặt chỗ</th>
                  <th scope="col" className="border-b border-vien py-2 pr-3 font-semibold">Giá</th>
                  <th scope="col" className="border-b border-vien py-2 font-semibold">Ghi chú</th>
                </tr>
              </thead>
              <tbody>
                {result.items
                  .filter((item) => item.kind !== "POI")
                  .map((item) => (
                    <ServiceRow
                      key={`${item.kind}-${item.offer_id ?? item.poi_id ?? ""}`}
                      item={item}
                      offerName={offerNames.get(item.offer_id ?? "") ?? item.offer_id ?? ""}
                    />
                  ))}
              </tbody>
            </table>
          </div>

          {needsRecheck(result) ? (
            <Notice variant="warning" className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <p>Có mục chưa rõ. Kiểm tra lại để lấy trạng thái mới nhất (dùng cùng mã yêu cầu, không đặt thêm).</p>
              <button type="button" onClick={book} disabled={busy} className={`shrink-0 ${buttonClass("outline", "sm")}`}>
                Kiểm tra lại trạng thái
              </button>
            </Notice>
          ) : null}

          {result.items.some((item) => item.kind === "POI") ? (
            <section aria-labelledby="contacts-heading" className="space-y-2">
              <h3 id="contacts-heading" className="font-serif text-sm font-semibold text-son">
                Tự liên hệ với các điểm đến
              </h3>
              <p className="text-xs text-muc-soft">Hệ thống không đặt các điểm này. Hãy liên hệ trực tiếp.</p>
              <ul className="grid gap-2 sm:grid-cols-2">
                {result.items
                  .filter((item) => item.kind === "POI")
                  .map((item) => (
                    <li key={item.poi_id ?? item.message} className="rounded-xl border border-vien bg-giay p-3 text-sm">
                      <p className="font-medium">{poiNames.get(item.poi_id ?? "") ?? item.poi_id}</p>
                      {item.contact_address ? <p className="text-muc-soft">{item.contact_address}</p> : null}
                      {item.contact_phone ? (
                        <p>
                          <a href={`tel:${item.contact_phone.replace(/[^+\d]/g, "")}`} className={LINK}>
                            {item.contact_phone}
                          </a>
                        </p>
                      ) : null}
                      {item.contact_url ? (
                        <a href={item.contact_url} target="_blank" rel="noopener noreferrer" className={`text-xs ${LINK}`}>
                          Trang nguồn
                        </a>
                      ) : null}
                    </li>
                  ))}
              </ul>
            </section>
          ) : null}

          {result.explanation.length > 0 ? (
            <ul className="list-disc space-y-1 pl-5 text-sm text-muc-soft">
              {result.explanation.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
