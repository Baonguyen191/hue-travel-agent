"""Phá có chủ đích một plan hợp lệ để tạo mẫu repair. Hàm thuần, xác định theo seed.

Mỗi kiểu phá sinh ra vài phương án; phương án được trộn theo seed rồi chạy qua validator. Ưu tiên
phương án mà validator chỉ báo đúng một mã ERROR mong muốn; không có thì nhận phương án có mã đó
kèm lỗi khác; không có phương án nào thì kiểu phá đó không áp dụng được cho plan này (trả None).
"""

from __future__ import annotations

import datetime as dt
import math
import random
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from travel_agent.data.place_repository import InMemoryPlaceRepository
from travel_agent.domain.models import Itinerary, Place, PlannedStop, PlanRequest
from travel_agent.domain.opening_hours import parse_opening_hours
from travel_agent.routing.travel_time import TravelTimeProvider
from travel_agent.validation.report import IssueCode, ValidationReport
from travel_agent.validation.validator import validate_itinerary


class CorruptionKind(StrEnum):
    UNKNOWN_PLACE = "unknown_place"  # đổi một place_id sang id không có trong candidate
    OVERLAP = "overlap"  # hai điểm liên tiếp chồng giờ
    CLOSED = "closed"  # dời một điểm có giờ mở cửa sang lúc đóng cửa
    TRAVEL_GAP = "travel_gap"  # khoảng trống giữa hai điểm nhỏ hơn thời gian di chuyển


EXPECTED_CODE: dict[CorruptionKind, IssueCode] = {
    CorruptionKind.UNKNOWN_PLACE: IssueCode.UNKNOWN_PLACE,
    CorruptionKind.OVERLAP: IssueCode.STOP_OVERLAP,
    CorruptionKind.CLOSED: IssueCode.CLOSED_DURING_VISIT,
    CorruptionKind.TRAVEL_GAP: IssueCode.TRAVEL_TIME_INSUFFICIENT,
}

# Số phút dời giờ khi phá; heuristic, chỉ cần tạo lỗi trông giống lỗi model hay mắc.
SHIFT_MINUTES = (10, 20, 45)
MAX_OPTIONS = 40  # đủ để tìm phương án sạch, không tốn quá nhiều lần chạy validator
_ID_DIGITS = re.compile(r"^(.*?)(\d+)$")


@dataclass(frozen=True)
class Corruption:
    kind: CorruptionKind
    itinerary: Itinerary
    report: ValidationReport  # validator chạy trên plan đã phá, với cùng candidate

    @property
    def clean(self) -> bool:
        """True khi validator chỉ báo đúng mã ERROR của kiểu phá."""
        return {issue.code for issue in self.report.errors()} == {EXPECTED_CODE[self.kind]}


def corrupt(
    request: PlanRequest,
    itinerary: Itinerary,
    candidates: Sequence[Place],
    travel: TravelTimeProvider,
    kind: CorruptionKind,
    seed: int,
) -> Corruption | None:
    """Plan đã phá theo `kind`, hoặc None nếu kiểu phá này không áp dụng được cho plan."""
    rng = random.Random(f"{seed}:{kind.value}")
    by_id = {place.id: place for place in candidates}
    options = list(_OPTION_MAKERS[kind](request, itinerary, by_id, travel, rng))
    rng.shuffle(options)
    lookup = InMemoryPlaceRepository(candidates)
    expected = EXPECTED_CODE[kind]
    fallback: Corruption | None = None
    fallback_score = (0, 0)
    for option in options[:MAX_OPTIONS]:
        report = validate_itinerary(request, option, lookup, travel)
        errors = report.errors()
        codes = {issue.code for issue in errors}
        if expected not in codes:
            continue
        result = Corruption(kind, option, report)
        if result.clean:
            return result
        # Không có phương án sạch: lấy phương án ít lỗi lạ nhất, để plan hỏng vẫn giống lỗi thật.
        score = (len(codes), len(errors))
        if fallback is None or score < fallback_score:
            fallback, fallback_score = result, score
    return fallback


def _minutes(value: dt.time) -> int:
    return value.hour * 60 + value.minute


def _time(minutes: int) -> dt.time | None:
    if not 0 <= minutes < 24 * 60:
        return None
    return dt.time(minutes // 60, minutes % 60)


def _with_stop(
    itinerary: Itinerary, d_idx: int, s_idx: int, arrive: int, depart: int
) -> Itinerary | None:
    start, end = _time(arrive), _time(depart)
    if start is None or end is None or end <= start:
        return None
    copy = itinerary.model_copy(deep=True)
    stop = copy.days[d_idx].stops[s_idx]
    copy.days[d_idx].stops[s_idx] = stop.model_copy(update={"arrive": start, "depart": end})
    return copy


def _shift_block(itinerary: Itinerary, d_idx: int, indices: range, delta: int) -> Itinerary | None:
    copy: Itinerary | None = itinerary
    for s_idx in indices:
        if copy is None:
            return None
        arrive, depart = _span(copy.days[d_idx].stops[s_idx])
        copy = _with_stop(copy, d_idx, s_idx, arrive + delta, depart + delta)
    return copy


def _span(stop: PlannedStop) -> tuple[int, int]:
    return _minutes(stop.arrive), _minutes(stop.depart)


Options = Iterator[Itinerary]
OptionMaker = Callable[
    [PlanRequest, Itinerary, Mapping[str, Place], TravelTimeProvider, random.Random], Options
]


def _unknown_place(
    request: PlanRequest,
    itinerary: Itinerary,
    by_id: Mapping[str, Place],
    travel: TravelTimeProvider,
    rng: random.Random,
) -> Options:
    """Id giả cùng dạng với id thật (cùng tiền tố, cùng số chữ số), như id model hay bịa."""
    for d_idx, day in enumerate(itinerary.days):
        for s_idx, stop in enumerate(day.stops):
            fake = _fake_id(stop.place_id, by_id, rng)
            copy = itinerary.model_copy(deep=True)
            copy.days[d_idx].stops[s_idx] = stop.model_copy(update={"place_id": fake})
            yield copy


def _fake_id(real: str, taken: Mapping[str, Place], rng: random.Random) -> str:
    match = _ID_DIGITS.match(real)
    prefix, width = (match.group(1), len(match.group(2))) if match else (f"{real}-", 4)
    while True:
        low = 10 ** (width - 1) if width > 1 else 0
        fake = f"{prefix}{rng.randint(low, 10**width - 1)}"
        if fake not in taken and fake != real:
            return fake


def _overlap(
    request: PlanRequest,
    itinerary: Itinerary,
    by_id: Mapping[str, Place],
    travel: TravelTimeProvider,
    rng: random.Random,
) -> Options:
    for d_idx, day in enumerate(itinerary.days):
        for s_idx in range(1, len(day.stops)):
            prev_arrive, prev_depart = _span(day.stops[s_idx - 1])
            arrive, depart = _span(day.stops[s_idx])
            for shift in SHIFT_MINUTES:
                # Điểm sau đến trước khi điểm trước kết thúc (giữ thời lượng thăm).
                early = prev_depart - shift
                if early > prev_arrive:
                    option = _with_stop(itinerary, d_idx, s_idx, early, early + depart - arrive)
                    if option is not None:
                        yield option
                # Điểm trước ở lố sang giờ đến của điểm sau.
                option = _with_stop(itinerary, d_idx, s_idx - 1, prev_arrive, arrive + shift)
                if option is not None:
                    yield option


def _closed(
    request: PlanRequest,
    itinerary: Itinerary,
    by_id: Mapping[str, Place],
    travel: TravelTimeProvider,
    rng: random.Random,
) -> Options:
    """Dời hoặc kéo dài lượt thăm cho lố giờ đóng cửa, hoặc bắt đầu trước giờ mở cửa."""
    for d_idx, day in enumerate(itinerary.days):
        weekday = day.date.weekday()
        for s_idx, stop in enumerate(day.stops):
            place = by_id.get(stop.place_id)
            hours = None if place is None else parse_opening_hours(place.opening_hours_raw)
            if hours is None:
                continue  # giờ chưa rõ: validator không thể báo đóng cửa
            arrive, depart = _span(stop)
            length = depart - arrive
            for opening in hours.by_weekday.get(weekday, ()):
                opens, closes = _minutes(opening.start), _minutes(opening.end)
                if not (opens <= arrive and depart <= closes):
                    continue  # không phải khung giờ đang chứa lượt thăm
                for shift in SHIFT_MINUTES:
                    later = closes + shift - length - arrive  # dời muộn, lố giờ đóng
                    earlier = opens - shift - arrive  # đến trước giờ mở
                    for option in (
                        _with_stop(itinerary, d_idx, s_idx, arrive + later, depart + later),
                        _with_stop(itinerary, d_idx, s_idx, arrive, closes + shift),
                        _with_stop(itinerary, d_idx, s_idx, arrive + earlier, depart + earlier),
                        # Dời cả các điểm sau (hoặc trước) cùng lượng, để lỗi chỉ nằm ở giờ mở cửa
                        # chứ không kéo theo chồng giờ với điểm bên cạnh.
                        _shift_block(itinerary, d_idx, range(s_idx, len(day.stops)), later),
                        _shift_block(itinerary, d_idx, range(0, s_idx + 1), earlier),
                    ):
                        if option is not None:
                            yield option


def _travel_gap(
    request: PlanRequest,
    itinerary: Itinerary,
    by_id: Mapping[str, Place],
    travel: TravelTimeProvider,
    rng: random.Random,
) -> Options:
    """Rút khoảng trống giữa hai điểm xuống dưới thời gian di chuyển nhưng không âm."""
    for d_idx, day in enumerate(itinerary.days):
        for s_idx in range(1, len(day.stops)):
            prev, cur = day.stops[s_idx - 1], day.stops[s_idx]
            origin, destination = by_id.get(prev.place_id), by_id.get(cur.place_id)
            if origin is None or destination is None:
                continue
            leg = travel.travel_leg(origin.coords, destination.coords, request.travel_mode)
            longest = math.ceil(leg.minutes) - 1  # khoảng trống nguyên lớn nhất vẫn còn thiếu
            if longest < 0:
                continue
            prev_arrive, prev_depart = _span(prev)
            arrive, depart = _span(cur)
            for gap in sorted({0, longest // 2, longest}):
                # Điểm sau đến sớm hơn, giữ thời lượng thăm.
                start = prev_depart + gap
                option = _with_stop(itinerary, d_idx, s_idx, start, start + depart - arrive)
                if option is not None:
                    yield option
                # Điểm trước ở lâu hơn.
                option = _with_stop(itinerary, d_idx, s_idx - 1, prev_arrive, arrive - gap)
                if option is not None:
                    yield option


_OPTION_MAKERS: dict[CorruptionKind, OptionMaker] = {
    CorruptionKind.UNKNOWN_PLACE: _unknown_place,
    CorruptionKind.OVERLAP: _overlap,
    CorruptionKind.CLOSED: _closed,
    CorruptionKind.TRAVEL_GAP: _travel_gap,
}
