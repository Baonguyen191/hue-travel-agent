import { Link } from "react-router-dom";
import type { Place } from "../api/types";
import { describePrice, describeRating } from "../lib/format";
import { CATEGORY_LABEL, CONFIDENCE_LABEL } from "../lib/labels";

export function placeDetailPath(poiId: string): string {
  return `/explore/${encodeURIComponent(poiId)}`;
}

export function openingHoursText(place: Place): string {
  const hours = place.opening_hours_raw ?? "chưa có thông tin";
  return `${hours} (${CONFIDENCE_LABEL[place.opening_hours_confidence]})`;
}

interface PlaceCardProps {
  place: Place;
}

/** Summary card for one POI. Prices are reference values from the source; the unit is not stated. */
export function PlaceCard({ place }: PlaceCardProps) {
  return (
    <article className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-base font-semibold leading-snug">
          <Link to={placeDetailPath(place.id)} className="hover:text-teal-800 hover:underline">
            {place.name}
          </Link>
        </h2>
        <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
          {CATEGORY_LABEL[place.category]}
        </span>
      </div>
      <dl className="grid grid-cols-[6.5rem_1fr] gap-x-2 gap-y-1 text-sm">
        <dt className="text-slate-500">Đánh giá</dt>
        <dd>{describeRating(place.rating_value, place.rating_count)}</dd>
        <dt className="text-slate-500">Giá</dt>
        <dd>{describePrice(place)}</dd>
        <dt className="text-slate-500">Giờ mở cửa</dt>
        <dd>{openingHoursText(place)}</dd>
      </dl>
      <div className="mt-auto flex items-center justify-between gap-2 pt-1 text-xs text-slate-500">
        <span>Nguồn: {place.source}</span>
        {place.source_url ? (
          <a
            href={place.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-teal-700 underline"
          >
            Trang nguồn
          </a>
        ) : null}
      </div>
    </article>
  );
}
