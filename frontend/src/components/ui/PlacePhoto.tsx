import { useState } from "react";
import { API_BASE } from "../../api/client";
import { PlaceIllustration } from "./PlaceIllustration";

export type PhotoSize = "sm" | "md" | "lg";
export type PhotoAspect = "4/3" | "16/9" | "1/1";

export const PHOTO_WIDTH: Record<PhotoSize, number> = { sm: 160, md: 480, lg: 960 };

const ASPECT: Record<PhotoAspect, string> = {
  "4/3": "aspect-[4/3]",
  "16/9": "aspect-video",
  "1/1": "aspect-square",
};

export function photoUrl(poiId: string, size: PhotoSize): string {
  return `${API_BASE}/places/${encodeURIComponent(poiId)}/photo?w=${PHOTO_WIDTH[size]}`;
}

interface PlacePhotoProps {
  poiId: string | null;
  name: string;
  category: string | null;
  size: PhotoSize;
  aspect?: PhotoAspect;
  className?: string;
}

/** The place photo from the backend proxy, in a fixed-ratio box; the category illustration when there is none. */
export function PlacePhoto({ poiId, name, category, size, aspect = "4/3", className = "" }: PlacePhotoProps) {
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
    </div>
  );
}
