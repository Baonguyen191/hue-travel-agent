import "leaflet/dist/leaflet.css";
import type { LatLngTuple } from "leaflet";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, Tooltip } from "react-leaflet";
import { FitToPoints } from "./PlacesMap";

const HUE_CENTER: LatLngTuple = [16.4637, 107.5909];
const OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

export interface ItineraryPoint {
  key: string;
  name: string;
  lat: number;
  lon: number;
  color: string;
}

interface ItineraryMapProps {
  points: ItineraryPoint[];
}

/** One day's stops in visiting order. Straight lines between stops are estimates, not routes. */
export function ItineraryMap({ points }: ItineraryMapProps) {
  const latlngs = points.map((point): LatLngTuple => [point.lat, point.lon]);
  return (
    <div className="space-y-2">
      <div role="region" aria-label="Bản đồ ngày đã chọn" className="overflow-hidden rounded-2xl border border-vien">
        <MapContainer center={HUE_CENTER} zoom={13} scrollWheelZoom={false} className="h-72 w-full md:h-[420px]">
          <TileLayer attribution={OSM_ATTRIBUTION} url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
          {latlngs.length > 1 ? (
            <Polyline positions={latlngs} pathOptions={{ color: "#b8913f", weight: 3, dashArray: "6 8" }}>
              <Tooltip sticky>đường chim bay (ước lượng)</Tooltip>
            </Polyline>
          ) : null}
          {points.map((point) => (
            <CircleMarker
              key={point.key}
              center={[point.lat, point.lon]}
              radius={9}
              pathOptions={{ color: "#b8913f", weight: 2, fillColor: point.color, fillOpacity: 0.95 }}
            >
              <Popup>{point.name}</Popup>
            </CircleMarker>
          ))}
          <FitToPoints points={latlngs} />
        </MapContainer>
      </div>
      <p className="text-xs text-muc-soft">Đường nối là đường chim bay (ước lượng), không phải đường đi thực tế.</p>
    </div>
  );
}
