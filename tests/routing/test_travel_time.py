import pytest

from travel_agent.domain.models import Coordinates, TravelMode
from travel_agent.routing.travel_time import HaversineEstimator, haversine_m

A = Coordinates(lat=16.47, lon=107.58)
B = Coordinates(lat=16.48, lon=107.58)


def test_one_degree_latitude_is_about_111_km() -> None:
    distance = haversine_m(Coordinates(lat=0, lon=0), Coordinates(lat=1, lon=0))
    assert distance == pytest.approx(111_195, abs=1)


def test_same_point_takes_no_time() -> None:
    leg = HaversineEstimator().travel_leg(A, A, TravelMode.MOTORBIKE)
    assert leg.minutes == 0
    assert leg.estimated


def test_walking_leg_uses_detour_factor_and_speed() -> None:
    leg = HaversineEstimator().travel_leg(A, B, TravelMode.WALK)
    road = haversine_m(A, B) * 1.3
    assert leg.distance_m == pytest.approx(road)
    assert leg.minutes == pytest.approx(road / 1000 / 4.5 * 60)
    assert leg.estimated
    assert leg.source == "haversine_estimate"


def test_motorbike_adds_start_overhead() -> None:
    leg = HaversineEstimator().travel_leg(A, B, TravelMode.MOTORBIKE)
    road = haversine_m(A, B) * 1.3
    assert leg.minutes == pytest.approx(road / 1000 / 22.0 * 60 + 5.0)
