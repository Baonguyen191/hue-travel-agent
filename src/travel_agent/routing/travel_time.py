"""Travel time providers. Domain logic chỉ phụ thuộc `TravelTimeProvider`."""

from __future__ import annotations

import math
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from travel_agent.domain.models import Coordinates, TravelMode

EARTH_RADIUS_M = 6_371_000.0


class TravelLeg(BaseModel):
    model_config = ConfigDict(frozen=True)

    distance_m: float
    minutes: float
    estimated: bool
    source: str


class TravelTimeProvider(Protocol):
    def travel_leg(
        self, origin: Coordinates, destination: Coordinates, mode: TravelMode
    ) -> TravelLeg: ...


def haversine_m(a: Coordinates, b: Coordinates) -> float:
    phi1, phi2 = math.radians(a.lat), math.radians(b.lat)
    d_phi = phi2 - phi1
    d_lambda = math.radians(b.lon - a.lon)
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


class HaversineEstimator:
    """Ước tính thô từ khoảng cách đường chim bay. KHÔNG phải dữ liệu routing.

    Tốc độ, hệ số đường vòng và thời gian khởi hành là giả định nội bộ cho đô thị Huế,
    chưa được đo. Kết quả luôn có `estimated=True` để validator và UI gắn nhãn ước tính.
    """

    SOURCE = "haversine_estimate"
    DETOUR_FACTOR = 1.3
    SPEED_KMH: dict[TravelMode, float] = {
        TravelMode.WALK: 4.5,
        TravelMode.MOTORBIKE: 22.0,
        TravelMode.CAR: 20.0,
    }
    START_OVERHEAD_MIN: dict[TravelMode, float] = {
        TravelMode.WALK: 0.0,
        TravelMode.MOTORBIKE: 5.0,
        TravelMode.CAR: 8.0,
    }

    def travel_leg(
        self, origin: Coordinates, destination: Coordinates, mode: TravelMode
    ) -> TravelLeg:
        road_m = haversine_m(origin, destination) * self.DETOUR_FACTOR
        if road_m == 0:
            return TravelLeg(distance_m=0.0, minutes=0.0, estimated=True, source=self.SOURCE)
        minutes = road_m / 1000 / self.SPEED_KMH[mode] * 60 + self.START_OVERHEAD_MIN[mode]
        return TravelLeg(distance_m=road_m, minutes=minutes, estimated=True, source=self.SOURCE)
