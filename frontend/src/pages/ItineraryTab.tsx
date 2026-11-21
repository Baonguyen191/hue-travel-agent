import { useState } from "react";
import { Link } from "react-router-dom";
import type { ItineraryEvent, Place } from "../api/types";
import { ItineraryMap, type ItineraryPoint } from "../components/ItineraryMap";
import { placeDetailPath, openingHoursText } from "../components/PlaceCard";
import { describePrice, formatMinutes } from "../lib/format";
import { describePoiCost, poiCostIndex } from "../lib/poiCost";
import { CATEGORY_COLOR } from "../lib/labels";
import {
  categoryLabel,
  dayTitle,
  eventKindLabel,
  placesById,
  timeRange,
  travelText,
} from "../lib/plan";
import { translateWarnings } from "../lib/warnings";
import { usePlan } from "./PlanLayout";

/** Notes that appear on at least two stops of the day: shown once above the timeline instead of on each card. */
function sharedNotes(events: ItineraryEvent[]): Set<string> {
  const counts = new Map<string, number>();
  for (const event of events) {
    for (const note of new Set(translateWarnings(event.warnings))) counts.set(note, (counts.get(note) ?? 0) + 1);
  }
  return new Set([...counts].filter(([, count]) => count >= 2).map(([note]) => note));
}

const FALLBACK_COLOR = "#475569";

function markerColor(event: ItineraryEvent): string {
  if (event.category && event.category in CATEGORY_COLOR) {
    return CATEGORY_COLOR[event.category as keyof typeof CATEGORY_COLOR];
  }
  return FALLBACK_COLOR;
}

function EventItem({ event, place, priceText, shared }: { event: ItineraryEvent; place: Place | undefined; priceText: string; shared: Set<string> }) {
  const ownNotes = translateWarnings(event.warnings).filter((note) => !shared.has(note));
  const isPlace = event.kind === "VISIT" || event.kind === "MEAL";
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <time className="text-sm font-semibold text-slate-800">{timeRange(event)}</time>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">{eventKindLabel(event)}</span>
      </div>
      <h3 className="mt-1 text-base font-semibold leading-snug">
        {event.poi_id ? (
          <Link to={placeDetailPath(event.poi_id)} className="hover:text-teal-800 hover:underline">
            {event.name}
          </Link>
        ) : (
          event.name
        )}
      </h3>
      <dl className="mt-2 grid grid-cols-[7.5rem_1fr] gap-x-2 gap-y-1 text-sm">
        <dt className="text-slate-500">Loại</dt>
        <dd>{categoryLabel(event.category)}</dd>
        <dt className="text-slate-500">Di chuyển</dt>
        <dd>{travelText(event)}</dd>
        {event.kind === "VISIT" ? (
          <>
            <dt className="text-slate-500">Thời gian tham quan</dt>
            <dd>{formatMinutes(event.visit_minutes)}</dd>
          </>
        ) : null}
        {isPlace ? (
          <>
            <dt className="text-slate-500">Giá tham khảo</dt>
            <dd>{priceText}</dd>
            <dt className="text-slate-500">Giờ mở cửa</dt>
            <dd>{place ? openingHoursText(place) : "chưa xác minh"}</dd>
          </>
        ) : null}
      </dl>
      {ownNotes.length > 0 ? (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-amber-900">
          {ownNotes.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function ItineraryTab() {
  const { record } = usePlan();
  const days = record.payload.itinerary.days;
  const [selected, setSelected] = useState(0);
  const places = placesById(record.payload.search);
  const costs = poiCostIndex(record);
  const people = record.payload.request.people;

  if (days.length === 0) {
    return <p className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-600">Kế hoạch chưa có ngày nào.</p>;
  }

  const index = Math.min(selected, days.length - 1);
  const day = days[index];
  // Buffers are travel gaps, not stops: they stay out of the timeline and the map.
  const events = day.events.filter((event) => event.kind !== "BUFFER");
  const points: ItineraryPoint[] = events
    .filter((event) => event.lat !== null && event.lon !== null)
    .map((event, position) => ({
      key: `${position}-${event.name}`,
      name: event.name,
      lat: event.lat as number,
      lon: event.lon as number,
      color: markerColor(event),
    }));

  const shared = sharedNotes(events);
  const priceFor = (event: ItineraryEvent): string => {
    if (event.poi_id && costs.has(event.poi_id)) return describePoiCost(costs.get(event.poi_id), people);
    const place = event.poi_id ? places.get(event.poi_id) : undefined;
    return place ? describePrice(place) : "chưa có thông tin giá";
  };

  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Chọn ngày" className="flex gap-2 overflow-x-auto pb-1">
        {days.map((item, position) => (
          <button
            key={item.date}
            type="button"
            role="tab"
            id={`day-tab-${position}`}
            aria-selected={position === index}
            aria-controls="day-panel"
            onClick={() => setSelected(position)}
            className={`shrink-0 rounded-full border px-3 py-1.5 text-sm font-medium ${
              position === index ? "border-teal-700 bg-teal-700 text-white" : "border-slate-300 bg-white text-slate-700"
            }`}
          >
            {dayTitle(position, item.date)}
          </button>
        ))}
      </div>

      <div
        id="day-panel"
        role="tabpanel"
        aria-labelledby={`day-tab-${index}`}
        className="gap-6 md:grid md:grid-cols-[minmax(0,1fr)_minmax(260px,380px)]"
      >
        <div className="min-w-0 space-y-4">
          {shared.size > 0 ? (
            <ul aria-label="Ghi chú chung cho ngày" className="list-disc space-y-1 rounded-md bg-amber-50 p-3 pl-7 text-xs text-amber-900">
              {[...shared].map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          ) : null}
          {events.length === 0 ? (
            <p className="text-sm text-slate-600">Ngày này chưa có điểm đến.</p>
          ) : (
            <ol className="space-y-3">
              {events.map((event, position) => (
                <EventItem
                  key={`${event.start_at}-${position}`}
                  event={event}
                  place={event.poi_id ? places.get(event.poi_id) : undefined}
                  priceText={priceFor(event)}
                  shared={shared}
                />
              ))}
            </ol>
          )}
        </div>
        <aside className="mt-6 md:sticky md:top-4 md:mt-0 md:self-start">
          <ItineraryMap points={points} />
        </aside>
      </div>
    </div>
  );
}
