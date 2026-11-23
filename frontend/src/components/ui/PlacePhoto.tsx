import { useState } from "react";
import { API_BASE } from "../../api/client";
import type { Place } from "../../api/types";
import { PlaceIllustration } from "./PlaceIllustration";

export type PhotoSize = "sm" | "md" | "lg";
export type PhotoAspect = "4/3" | "16/9" | "1/1" | "banner";

export const PHOTO_WIDTH: Record<PhotoSize, number> = { sm: 160, md: 480, lg: 960 };

const ASPECT: Record<PhotoAspect, string> = {
  "4/3": "aspect-[4/3]",
  "16/9": "aspect-video",
  "1/1": "aspect-square",
  banner: "h-48 w-full sm:h-64 md:h-80",
};

export function photoUrl(poiId: string, size: PhotoSize): string {
  return `${API_BASE}/places/${encodeURIComponent(poiId)}/photo?w=${PHOTO_WIDTH[size]}`;
}

/** True when the photo is a generic Commons picture of the category rather than this place. */
export function isIllustrative(place: Pick<Place, "photo">): boolean {
  return place.photo?.kind === "commons_illustrative";
}

interface PlacePhotoProps {
  poiId: string | null;
  name: string;
  category: string | null;
  size: PhotoSize;
  aspect?: PhotoAspect;
  className?: string;
  /** Labels the real image as "Ảnh minh hoạ" (generic category picture). Ignored for the illustration. */
  illustrative?: boolean;
}

/** The place photo from the backend proxy, in a fixed-ratio box; the category illustration when there is none. */
export function PlacePhoto({ poiId, name, category, size, aspect = "4/3", className = "", illustrative = false }: PlacePhotoProps) {
  const src = poiId ? photoUrl(poiId, size) : null;
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const showImage = src !== null && failedSrc !== src;
  return (
    <div className={`relative overflow-hidden bg-kim-soft ${ASPECT[aspect]} ${className}`.trim()}>
      {showImage ? (
        <img
          key={src}
          src={src}
          alt={name}
          loading="lazy"
          decoding="async"
          onLoad={() => setLoadedSrc(src)}
          onError={() => setFailedSrc(src)}
          className={`h-full w-full object-cover transition-opacity duration-300 ${loadedSrc === src ? "opacity-100" : "opacity-0"}`}
        />
      ) : (
        <>
          <PlaceIllustration category={category} className="absolute inset-0" />
          <span className="sr-only">{name}</span>
        </>
      )}
      {showImage && illustrative ? (
        <span className="absolute right-2 top-2 rounded-full bg-muc/75 px-2 py-0.5 text-xs font-medium text-nga">Ảnh minh hoạ</span>
      ) : null}
    </div>
  );
}
