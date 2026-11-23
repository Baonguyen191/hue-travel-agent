import { useState } from "react";
import { Link } from "react-router-dom";
import type { ItineraryEvent, Place, TravelLeg } from "../api/types";
import { Chip, MockBadge, Notice, PILL, PlacePhoto, cardClass, isIllustrative } from "../components/ui";
import { ItineraryMap, type ItineraryPoint } from "../components/ItineraryMap";
import { placeDetailPath, openingHoursText } from "../components/PlaceCard";
import { describePrice, formatMinutes } from "../lib/format";
import { describePoiCost, poiCostIndex } from "../lib/poiCost";
import {
  categoryLabel,
  dayTitle,
  eventKindLabel,
  findTravelLeg,
  placesById,
  slotLabel,
  timeRange,
  travelLegText,
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

/** Every stop is a burgundy marker on the day map; category colours stay on the explore map. */
function markerColor(_event: ItineraryEvent): string {
  return "#7a1f1f";
}

/** Stop number for the event at `position`; rest rows are not stops and do not count. */
function stopNumber(events: ItineraryEvent[], position: number): number {
  return events.slice(0, position + 1).filter((event) => event.kind !== "REST").length;
}

/** Compact muted row for a rest block: no photo, no card body. */
function RestRow({ event }: { event: ItineraryEvent }) {
  return (
    <li className="relative text-sm text-muc-soft">
      <span aria-hidden="true" className="absolute -left-[1.75rem] top-1/2 h-2 w-2 -translate-y-1/2 rounded-full bg-kim" />
      <p>
        <time>{timeRange(event)}</time> · {slotLabel(event.slot) ?? (event.name || "Nghỉ")}
      </p>
    </li>
  );
}

/** Outbound or return trip shown above day 1 or below the last day. */
function TravelLegRow({ leg }: { leg: TravelLeg }) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl bg-giay px-3 py-2 text-sm text-muc ring-1 ring-vien">
      <span className="min-w-0 break-words">{travelLegText(leg)}</span>
      {leg.mock ? <MockBadge /> : null}
    </div>
  );
}

function EventItem({ event, number, place, priceText, shared }: { event: ItineraryEvent; number: number; place: Place | undefined; priceText: string; shared: Set<string> }) {
  const ownNotes = translateWarnings(event.warnings).filter((note) => !shared.has(note));
  const isPlace = event.kind === "VISIT" || event.kind === "MEAL";
  const showPhoto = Boolean(event.poi_id) && isPlace;
  const slot = slotLabel(event.slot);
  return (
    <li className={cardClass("relative overflow-visible p-3 sm:flex sm:gap-4")}>
      <span
        aria-hidden="true"
        className="absolute -left-[2.3rem] top-4 flex h-6 w-6 items-center justify-center rounded-full bg-son text-xs font-bold text-on-son ring-2 ring-kim"
      >
        {number}
      </span>
      {showPhoto ? (
        <PlacePhoto
          poiId={event.poi_id}
          name={event.name}
          category={event.category}
          size="md"
          className="mb-3 w-full shrink-0 rounded-xl sm:mb-0 sm:w-44"
          illustrative={place ? isIllustrative(place) : false}
        />
      ) : (
        <div aria-hidden="true" className="mb-3 flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-kim-soft text-2xl sm:mb-0">
          {event.kind === "MEAL" || event.kind === "MEAL_BREAK" ? "🍜" : "•"}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
            <time className="font-semibold text-son">{timeRange(event)}</time>
            {event.slot === "sunset" ? <span className="text-xs text-muc-soft">(giờ hoàng hôn ước tính)</span> : null}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            {slot ? <span className={`${PILL} bg-kim-soft text-muc ring-kim`}>{slot}</span> : null}
            <Chip tone="soft">{eventKindLabel(event)}</Chip>
          </div>
        </div>
        <h3 className="mt-1 font-serif text-base font-semibold leading-snug text-muc">
          {event.poi_id ? (
            <Link to={placeDetailPath(event.poi_id)} className="hover:text-son hover:underline decoration-kim">
              {event.name}
            </Link>
          ) : (
            event.name
          )}
        </h3>
        {event.reason ? <p className="mt-1 text-xs text-muc-soft">Lý do: {event.reason}</p> : null}
        {event.intro ? (
          <p className="mt-1 line-clamp-2 text-xs italic text-muc-soft [overflow-wrap:anywhere]" title="Wikipedia tiếng Việt">
            {event.intro}
          </p>
        ) : null}
        <dl className="mt-2 grid grid-cols-[7.5rem_1fr] gap-x-2 gap-y-1 text-sm">
          <dt className="text-muc-soft">Loại</dt>
          <dd>{categoryLabel(event.category)}</dd>
          <dt className="text-muc-soft">Di chuyển</dt>
          <dd>{travelText(event)}</dd>
          {event.kind === "VISIT" ? (
            <>
              <dt className="text-muc-soft">Thời gian tham quan</dt>
              <dd>{formatMinutes(event.visit_minutes)}</dd>
            </>
          ) : null}
          {isPlace ? (
            <>
              <dt className="text-muc-soft">Giá tham khảo</dt>
              <dd>{priceText}</dd>
              <dt className="text-muc-soft">Giờ mở cửa</dt>
              <dd>{place ? openingHoursText(place) : "chưa xác minh"}</dd>
            </>
          ) : null}
        </dl>
        {ownNotes.length > 0 ? (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-muc marker:text-kim">
            {ownNotes.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        ) : null}
      </div>
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
    return <p className="rounded-2xl border border-dashed border-vien bg-nga p-6 text-sm text-muc-soft">Kế hoạch chưa có ngày nào.</p>;
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
  const outbound = index === 0 ? findTravelLeg(record.payload.itinerary.travel_legs, "OUTBOUND") : undefined;
  const isLastDay = index === days.length - 1;
  const inbound = isLastDay ? findTravelLeg(record.payload.itinerary.travel_legs, "RETURN") : undefined;
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
            className={`shrink-0 rounded-full px-4 py-1.5 text-sm font-semibold ring-1 ${
              position === index ? "bg-kim text-muc ring-kim" : "bg-nga text-son ring-vien"
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
            <Notice variant="warning">
              <ul aria-label="Ghi chú chung cho ngày" className="list-disc space-y-1 pl-5 text-xs">
                {[...shared].map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </Notice>
          ) : null}
          {outbound ? <TravelLegRow leg={outbound} /> : null}
          {events.length === 0 ? (
            <p className="text-sm text-muc-soft">Ngày này chưa có điểm đến.</p>
          ) : (
            <ol className="relative ml-3 space-y-3 border-l-2 border-dashed border-kim pl-6">
              {events.map((event, position) =>
                event.kind === "REST" ? (
                  <RestRow key={`${event.start_at}-${position}`} event={event} />
                ) : (
                  <EventItem
                    key={`${event.start_at}-${position}`}
                    event={event}
                    number={stopNumber(events, position)}
                    place={event.poi_id ? places.get(event.poi_id) : undefined}
                    priceText={priceFor(event)}
                    shared={shared}
                  />
                ),
              )}
            </ol>
          )}
          {inbound ? <TravelLegRow leg={inbound} /> : null}
        </div>
        <aside className="mt-6 md:sticky md:top-4 md:mt-0 md:self-start">
          <ItineraryMap points={points} />
        </aside>
      </div>
    </div>
  );
}
