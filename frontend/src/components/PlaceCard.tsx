import { Link } from "react-router-dom";
import type { Place } from "../api/types";
import { describePrice, describeRating } from "../lib/format";
import { CONFIDENCE_LABEL } from "../lib/labels";
import { CategoryChip, PlacePhoto, LINK, cardClass, isIllustrative } from "./ui";

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
    <article className={cardClass("flex flex-col")}>
      <PlacePhoto poiId={place.id} name={place.name} category={place.category} size="md" illustrative={isIllustrative(place)} />
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div className="flex items-start justify-between gap-2">
          <h2 className="font-serif text-base font-semibold leading-snug text-son">
            <Link to={placeDetailPath(place.id)} className="decoration-kim hover:underline">
              {place.name}
            </Link>
          </h2>
          <CategoryChip category={place.category} className="shrink-0" />
        </div>
        <dl className="grid grid-cols-[6.5rem_1fr] gap-x-2 gap-y-1 text-sm text-muc">
          <dt className="text-muc-soft">Đánh giá</dt>
          <dd>{describeRating(place.rating_value, place.rating_count)}</dd>
          <dt className="text-muc-soft">Giá</dt>
          <dd>{describePrice(place)}</dd>
          <dt className="text-muc-soft">Giờ mở cửa</dt>
          <dd>{openingHoursText(place)}</dd>
        </dl>
        <div className="mt-auto flex items-center justify-between gap-2 pt-1 text-xs text-muc-soft">
          <span>Nguồn: {place.source}</span>
          {place.source_url ? (
            <a href={place.source_url} target="_blank" rel="noopener noreferrer" className={LINK}>
              Trang nguồn
            </a>
          ) : null}
        </div>
      </div>
    </article>
  );
}
