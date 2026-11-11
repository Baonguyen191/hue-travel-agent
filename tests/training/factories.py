"""Dữ liệu giả cho test eval. Không phải dữ liệu thật của Huế."""

import json

from tests.planning.factories import make_place, make_request
from travel_agent.domain.models import Category

PLACES = [
    make_place("t:museum", Category.MUSEUM),
    make_place("t:lunch", Category.RESTAURANT),
    make_place("t:dinner", Category.RESTAURANT),
    make_place("t:cafe", Category.CAFE),
]

REQUEST = make_request()  # 1 ngày, 2026-12-01, moderate, 08:00-21:00


def _raw(lunch_id: str) -> str:
    stops = [
        {"place_id": "t:museum", "arrive": "08:30", "depart": "10:30"},
        {"place_id": lunch_id, "arrive": "11:30", "depart": "12:30"},
        {"place_id": "t:dinner", "arrive": "18:00", "depart": "19:00"},
    ]
    return json.dumps({"days": [{"date": "2026-12-01", "stops": stops}]})


VALID_RAW = _raw("t:lunch")
UNKNOWN_PLACE_RAW = _raw("x:404")
