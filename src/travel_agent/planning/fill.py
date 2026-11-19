"""Lấp khoảng trống của lịch đã xếp giờ: bổ sung bữa ăn còn thiếu và điểm vào quãng trống dài.

Chạy sau lần xếp giờ cuối trong `plan_trip` (chỉ khi xếp giờ bật). Hàm thuần, xác định: không gọi
model, không ngẫu nhiên, không mạng ngoài `travel`.

Quy tắc, theo thứ tự:

1. Bữa ăn: ngày nào có khung bữa (MEAL_WINDOWS) nằm trọn trong khung ngày mà không có nhà hàng
   chồng lên khung đó thì chèn nhà hàng chưa dùng, ở vị trí và giờ làm tăng ít đường đi nhất, sao
   cho lượt ăn nằm trọn trong khung bữa. Không có nhà hàng nào vừa thì bỏ qua.
2. Quãng trống: khi còn khoảng trống >= 120 phút giữa hai điểm liên tiếp, hoặc giữa điểm cuối và
   day_end - 60 phút, thì chèn điểm không phải nhà hàng chưa dùng: ưu tiên điểm khớp sở thích,
   rồi tới điểm làm tăng ít đường đi nhất. Lượt thăm phải vừa giờ mở cửa và kết thúc trước
   day_end. Khoảng trống giữa điểm và bữa ăn đã có (điểm cuối không phải bữa tới bữa ăn) là một
   trong các khoảng liên tiếp, vì các điểm đã xếp giờ theo thứ tự thời gian.
   Mọi lần chèn, kể cả bữa ăn, đều không được làm ngày vượt mức điểm của nhịp (xem `_day_cap`).
3. Mỗi lần chèn được thử: xếp lại giờ (giữ giờ của điểm đã có làm sàn), rồi kiểm lại. Nếu xếp
   giờ bỏ thêm điểm hoặc validator báo ERROR mới (cùng mã và địa điểm chưa có ở lịch trước) thì
   hoàn tác lần chèn đó và thử ứng viên kế tiếp.

Không đổi giờ của điểm đã có: chỉ điểm mới được thêm vào, nên lịch sau khi lấp không bớt điểm nào.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from travel_agent.data.place_repository import InMemoryPlaceRepository
from travel_agent.domain.models import (
    Itinerary,
    Place,
    PlannedDay,
    PlannedStop,
    PlanRequest,
)
from travel_agent.planning.candidates import preferred_categories
from travel_agent.planning.durations import visit_minutes
from travel_agent.planning.hours import (
    MINUTES_PER_DAY,
    Interval,
    day_bounds,
    minute_floor,
    open_ranges,
    time_of,
)
from travel_agent.planning.schedule import retime
from travel_agent.planning.solver import STOPS_PER_DAY
from travel_agent.routing.travel_time import TravelTimeProvider
from travel_agent.validation.report import ValidationReport
from travel_agent.validation.validator import (
    MAX_STOPS_PER_DAY,
    MEAL_CATEGORIES,
    MEAL_WINDOWS,
    validate_itinerary,
)

GAP_MIN_MINUTES = 120  # khoảng trống tối thiểu được lấp
TRAILING_END_MARGIN_MINUTES = 60  # khoảng sau điểm cuối được tính tới day_end trừ mức này
GAP_REASON = "lấp khoảng trống buổi chiều"  # dùng cho mọi khoảng trống, không chỉ buổi chiều


@dataclass(frozen=True)
class AddedStop:
    day_index: int
    place_id: str
    reason: str  # tiếng Việt, hiển thị cho người dùng


# Một cách chèn: (đi thêm phút, id, vị trí trong ngày, giờ đến tuyệt đối).
_Placement = tuple[float, str, int, int]


def fill_gaps(
    request: PlanRequest,
    itinerary: Itinerary,
    candidates: Sequence[Place],
    travel: TravelTimeProvider,
) -> tuple[Itinerary, list[AddedStop]]:
    """Lịch đã lấp và danh sách điểm đã thêm. Không thêm gì thì trả đúng `itinerary` và []."""
    filler = _Filler(request, itinerary, candidates, travel)
    for day_index in range(len(filler.days)):
        filler.fill_meals(day_index)
    for day_index in range(len(filler.days)):
        filler.fill_gaps(day_index)
    if not filler.added:
        return itinerary, []
    return filler.result(), filler.added


class _Filler:
    def __init__(
        self,
        request: PlanRequest,
        itinerary: Itinerary,
        candidates: Sequence[Place],
        travel: TravelTimeProvider,
    ) -> None:
        self.request = request
        self.travel = travel
        self.lookup = InMemoryPlaceRepository(candidates)
        self.places = list(candidates)
        self.dates = [day.date for day in itinerary.days]
        self.days: list[list[PlannedStop]] = [list(day.stops) for day in itinerary.days]
        self.used: set[str] = {stop.place_id for day in self.days for stop in day}
        self.preferred = preferred_categories(request.interests)
        self.cap = min(MAX_STOPS_PER_DAY[request.pace], STOPS_PER_DAY[request.pace][1])
        # Mốc để so sánh: lỗi và điểm bị bỏ đã có trước khi lấp. Chỉ tính lỗi/bỏ mới.
        base = validate_itinerary(request, itinerary, self.lookup, travel)
        self.base_errors = _error_keys(base)
        baseline = retime(request, itinerary, self.lookup, travel)
        self.base_drops = {(drop.day_index, drop.place_id) for drop in baseline.dropped}
        self.added: list[AddedStop] = []

    def result(self) -> Itinerary:
        return Itinerary(
            days=[
                PlannedDay(date=date, stops=stops)
                for date, stops in zip(self.dates, self.days, strict=True)
            ]
        )

    # Bữa ăn

    def fill_meals(self, day_index: int) -> None:
        base = day_index * MINUTES_PER_DAY
        for meal, window_start, window_end in MEAL_WINDOWS:
            if self._has_meal(day_index, window_start, window_end):
                continue
            if not self._covers_window(window_start, window_end):
                continue
            lo = base + minute_floor(window_start)
            hi = base + minute_floor(window_end)
            placements = sorted(self._restaurant_placements(day_index, (lo, hi)))
            reason = f"bổ sung {meal}"
            self._try_placements(day_index, placements, reason)

    def _covers_window(self, window_start: dt.time, window_end: dt.time) -> bool:
        return self.request.day_start <= window_start and self.request.day_end >= window_end

    def _has_meal(self, day_index: int, window_start: dt.time, window_end: dt.time) -> bool:
        """Cùng điều kiện với validator: nhà hàng chồng lên khung bữa."""
        base = day_index * MINUTES_PER_DAY
        lo, hi = base + minute_floor(window_start), base + minute_floor(window_end)
        for stop in self.days[day_index]:
            place = self.lookup.get(stop.place_id)
            if place is None or place.category not in MEAL_CATEGORIES:
                continue
            start, end = base + minute_floor(stop.arrive), base + minute_floor(stop.depart)
            if start < hi and end > lo:
                return True
        return False

    def _restaurant_placements(self, day_index: int, window: Interval) -> list[_Placement]:
        found: list[_Placement] = []
        for place in self.places:
            if place.category not in MEAL_CATEGORIES or place.id in self.used:
                continue
            found.extend(self._placements_in(day_index, place, window))
        return found

    # Quãng trống

    def fill_gaps(self, day_index: int) -> None:
        """Lặp: tìm khoảng trống đầu tiên còn chèn được điểm, rồi tìm tiếp; dừng khi không còn."""
        while len(self.days[day_index]) < self.cap:
            if not self._fill_first_gap(day_index):
                return

    def _fill_first_gap(self, day_index: int) -> bool:
        stops = self.days[day_index]
        base = day_index * MINUTES_PER_DAY
        _, day_end = day_bounds(self.request, day_index)
        for pos in range(1, len(stops) + 1):
            prev = stops[pos - 1]
            prev_end = base + minute_floor(prev.depart)
            if pos < len(stops):
                gap_end = base + minute_floor(stops[pos].arrive)
            else:
                gap_end = day_end - TRAILING_END_MARGIN_MINUTES
            if gap_end - prev_end < GAP_MIN_MINUTES:
                continue
            placements = self._gap_placements(day_index, pos)
            if self._try_placements(day_index, placements, GAP_REASON):
                return True
        return False

    def _gap_placements(self, day_index: int, pos: int) -> list[_Placement]:
        """Điểm không phải nhà hàng chưa dùng vừa vào vị trí `pos`; khớp sở thích xếp trước."""
        bound = day_bounds(self.request, day_index)
        ranked: list[tuple[int, _Placement]] = []
        for place in self.places:
            if place.category in MEAL_CATEGORIES or place.id in self.used:
                continue
            for placement in self._placements_in(day_index, place, bound, only_pos=pos):
                matches = place.category in self.preferred
                ranked.append((0 if matches else 1, placement))
        ranked.sort(key=lambda item: (item[0], item[1][0], item[1][1]))
        return [placement for _, placement in ranked]

    # Chèn chung

    def _placements_in(
        self,
        day_index: int,
        place: Place,
        window: Interval,
        only_pos: int | None = None,
    ) -> list[_Placement]:
        """Mọi vị trí (hoặc chỉ `only_pos`) mà `place` vừa được chèn trong `window` của ngày."""
        stops = self.days[day_index]
        positions = range(len(stops) + 1) if only_pos is None else [only_pos]
        found: list[_Placement] = []
        for pos in positions:
            fit = self._fit_at(day_index, place, pos, window)
            if fit is None:
                continue
            arrive, detour = fit
            found.append((detour, place.id, pos, arrive))
        return found

    def _fit_at(
        self, day_index: int, place: Place, pos: int, window: Interval
    ) -> tuple[int, float] | None:
        """Giờ đến sớm nhất và đường đi thêm nếu chèn `place` vào `pos`; None nếu không vừa.

        Điểm kề cạnh phải có tọa độ (có trong `lookup`); điểm lạ thì không xét vị trí đó.
        """
        stops = self.days[day_index]
        base = day_index * MINUTES_PER_DAY
        prev = stops[pos - 1] if pos > 0 else None
        nxt = stops[pos] if pos < len(stops) else None
        prev_place = self._known(prev)
        nxt_place = self._known(nxt)
        if (prev is not None and prev_place is None) or (nxt is not None and nxt_place is None):
            return None

        ready, latest = window
        if prev is not None and prev_place is not None:
            ready = max(ready, base + minute_floor(prev.depart) + self._minutes(prev_place, place))
        if nxt is not None and nxt_place is not None:
            latest = min(latest, base + minute_floor(nxt.arrive) - self._minutes(place, nxt_place))
        visit = visit_minutes(place, 0)
        arrive = _earliest_arrival(
            open_ranges(self.request, place, day_index), ready, latest, visit
        )
        if arrive is None:
            return None
        detour = 0.0
        if prev_place is not None:
            detour += self._leg(prev_place, place)
        if nxt_place is not None:
            detour += self._leg(place, nxt_place)
        if prev_place is not None and nxt_place is not None:
            detour -= self._leg(prev_place, nxt_place)
        return arrive, detour

    def _known(self, stop: PlannedStop | None) -> Place | None:
        return None if stop is None else self.lookup.get(stop.place_id)

    def _leg(self, origin: Place, destination: Place) -> float:
        return self.travel.travel_leg(
            origin.coords, destination.coords, self.request.travel_mode
        ).minutes

    def _minutes(self, origin: Place, destination: Place) -> int:
        """Làm tròn lên như retime và validator, để chỗ trống tính ra khớp với lúc xếp giờ lại."""
        return math.ceil(self._leg(origin, destination))

    def _try_placements(self, day_index: int, placements: list[_Placement], reason: str) -> bool:
        """Thử từng cách chèn theo đúng thứ tự của `placements`; nhận cách đầu qua được kiểm tra.

        Bữa ăn truyền danh sách đã sắp theo đường đi thêm; quãng trống truyền theo sở thích trước.
        """
        if len(self.days[day_index]) >= self.cap:
            return False
        for _, place_id, pos, arrive in placements:
            if self._accept(day_index, place_id, pos, arrive, reason):
                return True
        return False

    def _accept(self, day_index: int, place_id: str, pos: int, arrive: int, reason: str) -> bool:
        place = self.lookup.get(place_id)
        if place is None:  # không xảy ra: placements chỉ lấy điểm trong candidates
            return False
        visit = visit_minutes(place, 0)
        stop = PlannedStop(
            place_id=place_id, arrive=time_of(arrive), depart=time_of(arrive + visit)
        )
        days = [list(stops) for stops in self.days]
        days[day_index].insert(pos, stop)
        trial = Itinerary(
            days=[
                PlannedDay(date=date, stops=stops)
                for date, stops in zip(self.dates, days, strict=True)
            ]
        )
        retimed = retime(self.request, trial, self.lookup, self.travel)
        drops = {(drop.day_index, drop.place_id) for drop in retimed.dropped}
        if drops - self.base_drops:
            return False
        report: ValidationReport = validate_itinerary(
            self.request, retimed.itinerary, self.lookup, self.travel
        )
        errors = _error_keys(report)
        if errors - self.base_errors:
            return False
        self.days = [list(day.stops) for day in retimed.itinerary.days]
        self.base_errors = errors
        self.used.add(place_id)
        self.added.append(AddedStop(day_index=day_index, place_id=place_id, reason=reason))
        return True


def _earliest_arrival(
    ranges: list[Interval], ready: int, latest_depart: int, visit: int
) -> int | None:
    """Giờ đến sớm nhất >= ready để lượt thăm nằm gọn trong một khoảng mở cửa và kết thúc trước
    `latest_depart`. Cùng logic với `_earliest_fit` của xếp giờ, nhưng nhận cận rõ ràng."""
    for start, end in sorted(ranges):
        arrive = max(start, ready)
        if arrive + visit <= min(end, latest_depart):
            return arrive
    return None


def _error_keys(report: ValidationReport) -> Counter[tuple[str, str | None]]:
    """Khóa so sánh ERROR: mã và địa điểm (không gồm chỉ số ngày/điểm, vì chèn làm chúng dịch)."""
    return Counter((issue.code.value, issue.place_id) for issue in report.errors())
