import { Link } from "react-router-dom";
import type { BookingItem, ChatBookingCard, ChatCard, ChatPlaceCard, ChatPlanCard } from "../../api/types";
import { budgetStatusLabel, optionLabelText } from "../../lib/budget";
import { bookingStatusLabel, bookingStatusTone } from "../../lib/booking";
import { formatDate, formatVnd, formatVndRange } from "../../lib/format";
import { CATEGORY_LABEL } from "../../lib/labels";
import { statusLabel, statusTone, type StatusTone } from "../../lib/plan";
import { approvable } from "../../lib/chat";

const TONE_CLASS: Record<StatusTone, string> = {
  approved: "bg-emerald-100 text-emerald-900 ring-emerald-300",
  waiting: "bg-amber-100 text-amber-900 ring-amber-300",
  failed: "bg-red-100 text-red-900 ring-red-300",
  neutral: "bg-slate-100 text-slate-800 ring-slate-300",
};

const PILL = "inline-block rounded-full px-2 py-0.5 text-xs font-semibold ring-1";
const CARD = "mt-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm";
const SIMULATED_BADGE = "rounded bg-violet-100 px-1.5 py-0.5 text-[11px] font-semibold text-violet-900 ring-1 ring-violet-300";

const KIND_LABEL: Record<string, string> = {
  VISIT: "Tham quan",
  MEAL_BREAK: "Nghỉ ăn trưa",
};
const MEAL_LABEL: Record<string, string> = {
  LUNCH: "Ăn trưa",
  DINNER: "Ăn tối",
  CAFE: "Cà phê",
};
const BOOKING_KIND_LABEL: Record<BookingItem["kind"], string> = {
  TRANSPORT: "Xe",
  HOTEL: "Khách sạn",
  POI: "Điểm tham quan",
};

/** "Tham quan", "Ăn trưa", "Ăn tối", "Cà phê"; other kinds keep their code. */
export function planItemKindLabel(kind: string, meal: string | null): string {
  if (kind === "MEAL") return (meal && MEAL_LABEL[meal]) || "Ăn";
  return KIND_LABEL[kind] ?? kind;
}

interface ChatCardViewProps {
  card: ChatCard;
  /** Whether the approve buttons of a plan card may be used (only the last bot message). */
  live: boolean;
  disabled: boolean;
  onSend: (text: string) => void;
}

/** One card under a bot reply. Every field is copied from the API; nothing is computed here except labels. */
export function ChatCardView({ card, live, disabled, onSend }: ChatCardViewProps) {
  if (card.kind === "plan_summary") {
    return <PlanCardView card={card} live={live} disabled={disabled} onSend={onSend} />;
  }
  if (card.kind === "place") return <PlaceCardView card={card} />;
  return <BookingCardView card={card} />;
}

function PlanCardView({ card, live, disabled, onSend }: { card: ChatPlanCard; live: boolean; disabled: boolean; onSend: (text: string) => void }) {
  const showApprove = live && approvable(card.status, card.budget_options.length);
  return (
    <section aria-label="Lịch trình" className={CARD}>
      <h3 className="font-semibold text-slate-900">
        Lịch trình {card.days.length} ngày · version {card.version}
      </h3>
      <p className="mt-1">
        <span className={`${PILL} ${TONE_CLASS[statusTone(card.status)]}`}>{statusLabel(card.status)}</span>
      </p>
      <div className="mt-3 flex flex-col gap-3">
        {card.days.map((day, index) => (
          <div key={day.date}>
            <h4 className="font-medium text-slate-800">
              Ngày {index + 1} · {formatDate(day.date)}
            </h4>
            <ol className="mt-1 flex flex-col gap-1">
              {day.items.map((item, itemIndex) => (
                <li key={`${day.date}-${itemIndex}`} className="flex flex-wrap gap-x-2">
                  <span className="font-mono text-xs text-slate-600">{item.time}</span>
                  <span>{item.name}</span>
                  <span className="text-xs text-slate-500">({planItemKindLabel(item.kind, item.meal)})</span>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
      <p className="mt-3">
        <Link to={`/plan/${encodeURIComponent(card.thread_id)}`} className="font-medium text-teal-700 underline">
          Xem chi tiết
        </Link>
      </p>
      {card.budget_options.length > 0 ? (
        <div className="mt-3">
          <h4 className="font-medium text-slate-800">Ngân sách</h4>
          <ul className="mt-1 flex flex-col gap-2">
            {card.budget_options.map((option) => (
              <li key={option.label} className="flex flex-col gap-1 rounded-md bg-white p-2 ring-1 ring-slate-200">
                <span>
                  <strong>{optionLabelText(option.label)}</strong>: {formatVndRange(option.known_total_vnd, option.known_total_max_vnd)}{" "}
                  <span className="text-xs text-slate-600">({budgetStatusLabel(option.budget_status)})</span>
                </span>
                {showApprove ? (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onSend(`Duyệt ${option.label}`)}
                    className="self-start rounded-md bg-teal-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-teal-800 disabled:opacity-50"
                  >
                    Duyệt {optionLabelText(option.label)}
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function PlaceCardView({ card }: { card: ChatPlaceCard }) {
  const price =
    card.price_min_vnd === null && card.price_max_vnd === null
      ? "giá chưa rõ"
      : `${formatVndRange(card.price_min_vnd, card.price_max_vnd)} (tham khảo, đơn vị chưa rõ)`;
  return (
    <section aria-label={`Địa điểm: ${card.name}`} className={CARD}>
      <h3 className="font-semibold text-slate-900">{card.name}</h3>
      <p className="text-xs text-slate-600">{CATEGORY_LABEL[card.category as keyof typeof CATEGORY_LABEL] ?? card.category}</p>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt className="text-slate-600">Địa chỉ</dt>
        <dd>{card.address ?? "chưa có dữ liệu"}</dd>
        <dt className="text-slate-600">Giờ mở cửa</dt>
        <dd>
          {card.opening_hours_raw ?? "chưa có dữ liệu"} <span className="text-xs text-slate-600">({card.opening_hours_note})</span>
        </dd>
        <dt className="text-slate-600">Giá</dt>
        <dd>{price}</dd>
        <dt className="text-slate-600">Điện thoại</dt>
        <dd>{card.phone ?? "chưa có dữ liệu"}</dd>
      </dl>
      <p className="mt-2 flex flex-wrap gap-3">
        <Link to={`/explore/${encodeURIComponent(card.poi_id)}`} className="font-medium text-teal-700 underline">
          Xem trên trang khám phá
        </Link>
        {card.source_url ? (
          <a href={card.source_url} target="_blank" rel="noopener noreferrer" className="font-medium text-teal-700 underline">
            Nguồn dữ liệu
          </a>
        ) : null}
      </p>
    </section>
  );
}

function BookingCardView({ card }: { card: ChatBookingCard }) {
  const { result } = card;
  const offers = result.items.filter((item) => item.kind !== "POI");
  const contacts = result.items.filter((item) => item.kind === "POI");
  return (
    <section aria-label="Kết quả đặt chỗ" className={CARD}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold text-slate-900">Đặt chỗ</h3>
        <span className={SIMULATED_BADGE}>MÔ PHỎNG</span>
        <span className={`${PILL} ${TONE_CLASS[bookingStatusTone(result.status)]}`}>{bookingStatusLabel(result.status)}</span>
      </div>
      {offers.length > 0 ? (
        <ul className="mt-2 flex flex-col gap-2">
          {offers.map((item, index) => (
            <li key={`${item.kind}-${item.offer_id ?? index}`} className="rounded-md bg-white p-2 ring-1 ring-slate-200">
              <div className="flex flex-wrap items-center gap-2">
                <strong>{BOOKING_KIND_LABEL[item.kind]}</strong>
                <span className={`${PILL} ${TONE_CLASS[bookingStatusTone(item.status)]}`}>{bookingStatusLabel(item.status)}</span>
                {item.source === "MOCK" ? <span className={SIMULATED_BADGE}>MÔ PHỎNG</span> : null}
              </div>
              <p className="mt-1 text-xs text-slate-700">
                {item.reference ? <code className="break-all">{item.reference}</code> : "chưa có mã"}
                {item.price_vnd === null ? null : <span> · {formatVnd(item.price_vnd)}</span>}
              </p>
              {item.message ? <p className="mt-1 text-xs text-slate-600">{item.message}</p> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {contacts.length > 0 ? (
        <div className="mt-3">
          <h4 className="font-medium text-slate-800">Tự liên hệ</h4>
          <ul className="mt-1 flex flex-col gap-2">
            {contacts.map((item, index) => (
              <li key={`contact-${item.poi_id ?? index}`} className="rounded-md bg-white p-2 ring-1 ring-slate-200">
                <p>{item.contact_address ?? "chưa có địa chỉ"}</p>
                <p className="text-xs text-slate-700">Điện thoại: {item.contact_phone ?? "chưa có dữ liệu"}</p>
                {item.contact_url ? (
                  <a href={item.contact_url} target="_blank" rel="noopener noreferrer" className="text-xs font-medium text-teal-700 underline">
                    Nguồn dữ liệu
                  </a>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
