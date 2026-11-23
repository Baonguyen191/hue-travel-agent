import "leaflet/dist/leaflet.css";
import { latLngBounds, type LatLngTuple } from "leaflet";
import { useEffect, useMemo } from "react";
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";
import { Link } from "react-router-dom";
import type { Place } from "../api/types";
import { CATEGORY_COLOR, CATEGORY_LABEL, CATEGORY_OPTIONS } from "../lib/labels";
import { placeDetailPath } from "./PlaceCard";

const HUE_CENTER: LatLngTuple = [16.4637, 107.5909];
const OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

/**
 * Fits the map view to the given points; does nothing when there are none.
 * Refits only when the coordinates change (callers pass a new array each render), and without
 * animation: a zoom animation still running when the map unmounts (day or tab switch) makes
 * Leaflet throw "Cannot read properties of undefined (reading '_leaflet_pos')".
 */
export function FitToPoints({ points }: { points: LatLngTuple[] }) {
  const map = useMap();
  const signature = points.map(([lat, lon]) => `${lat},${lon}`).join(";");
  useEffect(() => {
    if (points.length === 0) return;
    map.fitBounds(latLngBounds(points), { padding: [24, 24], maxZoom: 15, animate: false });
    // `signature` stands for `points`: same coordinates, same view.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, signature]);
  return null;
}

interface PlacesMapProps {
  places: Place[];
  heightClass?: string;
}

/**
 * Map of POIs coloured by category. Markers are CircleMarkers, so no image icons are bundled.
 * Positions come from the source dataset; a straight-line view is not a route.
 */
export function PlacesMap({ places, heightClass = "h-72 md:h-[480px]" }: PlacesMapProps) {
  const points = useMemo(() => places.map((place): LatLngTuple => [place.lat, place.lon]), [places]);
  const legend = useMemo(
    () => CATEGORY_OPTIONS.filter((option) => places.some((place) => place.category === option.value)),
    [places],
  );

  return (
    <div className="space-y-2">
      <div role="region" aria-label="Bản đồ địa điểm" className="overflow-hidden rounded-2xl border border-vien">
        <MapContainer
          center={HUE_CENTER}
          zoom={13}
          scrollWheelZoom={false}
          className={`${heightClass} w-full`}
        >
          <TileLayer attribution={OSM_ATTRIBUTION} url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
          {places.map((place) => (
            <CircleMarker
              key={place.id}
              center={[place.lat, place.lon]}
              radius={8}
              pathOptions={{ color: "#fffaf0", weight: 1.5, fillColor: CATEGORY_COLOR[place.category], fillOpacity: 0.95 }}
            >
              <Popup>
                <Link to={placeDetailPath(place.id)} className="font-semibold text-son underline">
                  {place.name}
                </Link>
                <div className="text-xs text-muc-soft">{CATEGORY_LABEL[place.category]}</div>
              </Popup>
            </CircleMarker>
          ))}
          <FitToPoints points={points} />
        </MapContainer>
      </div>
      {legend.length > 0 ? (
        <ul aria-label="Chú giải bản đồ" className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muc-soft">
          {legend.map((option) => (
            <li key={option.value} className="flex items-center gap-1">
              <span aria-hidden="true" className="inline-block size-2.5 rounded-full" style={{ backgroundColor: option.color }} />
              {option.label}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
