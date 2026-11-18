"""Solver sinh nhãn SFT: chọn điểm và xếp giờ cho một PlanRequest. Hàm thuần, xác định theo seed.

Mô hình OR-Tools Routing, mỗi ngày là một xe, thời gian tính bằng phút tuyệt đối
(ngày d chiếm [d*1440 + day_start, d*1440 + day_end]) để giờ mở cửa theo thứ trong tuần
gắn được vào từng ngày.

- Điểm thường: một node tùy chọn (disjunction một phần tử, phạt lớn nếu bỏ) với time window là
  hợp các khung mở cửa của mọi ngày; giờ chưa rõ thì lấy khung ngày.
- Bữa ăn: mỗi (ngày, bữa) bắt buộc là một "slot". Mỗi nhà hàng mở được trong slot thì có một
  bản sao node riêng cho slot đó, window nằm gọn trong khung bữa ăn và chỉ xe của ngày đó được
  đi. Một disjunction mỗi slot (tối đa một nhà hàng) và một disjunction mỗi nhà hàng (dùng tối
  đa một lần). Nhà hàng không được xếp ngoài slot bữa ăn.
- Số điểm thường mỗi ngày bị chặn trên bằng một dimension đếm (chỗ cho bữa ăn giữ riêng); mục
  tiêu mỗi ngày bốc ngẫu nhiên trong khoảng của pace, sàn của pace là cận dưới mềm. Sàn số điểm
  và việc đủ bữa được kiểm lại sau khi giải; thiếu thì trả INFEASIBLE.
- Nhiễu có seed nằm trong chi phí vào mỗi node, nên seed khác cho plan khác.
- Thời gian chờ giữa hai điểm bị phạt nhẹ, và mỗi phút đến muộn cũng bị phạt nhẹ, để buổi sáng
  được dùng trước; quãng trống (nếu có) dồn về trước bữa tối hoặc cuối ngày.

Giờ đến lấy từ cumul của dimension thời gian trong lời giải OR-Tools, rồi chạy
`validate_itinerary`. Plan có ERROR bị trả về như một thất bại, không bao giờ trả plan dở hoặc sai.
"""

from __future__ import annotations

import datetime as dt
import itertools
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from travel_agent.data.place_repository import InMemoryPlaceRepository
from travel_agent.domain.models import (
    Category,
    Itinerary,
    Pace,
    Place,
    PlannedDay,
    PlannedStop,
    PlanRequest,
)
from travel_agent.planning.candidates import preferred_categories
from travel_agent.planning.hours import (
    MINUTES_PER_DAY,
    Interval,
    day_bounds,
    minute_ceil,
    minute_floor,
    open_ranges,
    time_of,
)
from travel_agent.routing.travel_time import TravelTimeProvider
from travel_agent.validation.report import ValidationReport
from travel_agent.validation.validator import MEAL_CATEGORIES, MEAL_WINDOWS, validate_itinerary

# Số điểm mỗi ngày (min, max). Max khớp ngưỡng `overloaded_day` của validator; cả khoảng nằm
# trong quy tắc 7 của prompt (prompt cho moderate từ 4, packed từ 6; solver chọn hẹp hơn).
STOPS_PER_DAY: dict[Pace, tuple[int, int]] = {
    Pace.RELAXED: (3, 4),
    Pace.MODERATE: (5, 6),
    Pace.PACKED: (7, 8),
}

# Thời lượng tham quan theo loại, tính bằng phút. HEURISTIC SẢN PHẨM, CHƯA KIỂM CHỨNG:
# không lấy từ dữ liệu khách thật, chỉnh lại khi có phản hồi người dùng.
VISIT_MINUTES: dict[Category, int] = {
    Category.ATTRACTION: 60,
    Category.MUSEUM: 75,
    Category.HISTORIC: 60,
    Category.VIEWPOINT: 30,
    Category.RESTAURANT: 60,
    Category.CAFE: 45,
    Category.MARKET: 45,
    Category.PARK: 45,
    Category.RELIGIOUS: 45,
}

DEFAULT_TIME_LIMIT_S = 10.0

# Trọng số hàm mục tiêu (đơn vị chi phí nguyên). Phạt bỏ điểm lớn hơn mọi chi phí đi lại để
# solver luôn lấp đủ mục tiêu số điểm khi khả thi; phạt thiếu bữa còn lớn hơn nữa.
TRAVEL_COST_PER_MINUTE = 10
INTEREST_BONUS = 200  # tương đương 20 phút đi lại
NOISE_MAX = 150  # tương đương 15 phút đi lại
IDLE_COST_PER_MINUTE = 3  # 10 phút chờ tương đương 3 phút đi lại
EARLY_COST_PER_MINUTE = 1  # mỗi phút giờ đến muộn hơn; nhỏ hơn mọi trọng số khác
STOP_PENALTY = 100_000
SHORT_DAY_PENALTY = 500_000  # mỗi điểm thiếu so với sàn của pace
MEAL_PENALTY = 1_000_000


class SolveStatus(StrEnum):
    SOLVED = "solved"
    INFEASIBLE = "infeasible"  # không có plan thỏa mọi ràng buộc (số điểm, bữa ăn, giờ mở cửa)
    TIMED_OUT = "timed_out"  # hết giờ trước khi tới tối ưu cục bộ; bỏ để giữ tính xác định
    INVALID = "invalid"  # lưới an toàn: plan dựng ra bị validator báo ERROR


@dataclass(frozen=True)
class SolveResult:
    """`itinerary` khác None khi và chỉ khi `status` là SOLVED."""

    status: SolveStatus
    itinerary: Itinerary | None = None
    report: ValidationReport | None = None  # báo cáo validator của plan dựng ra, nếu đã dựng
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status is SolveStatus.SOLVED


@dataclass(frozen=True)
class _Slot:
    day: int
    start: int  # phút tuyệt đối
    end: int


@dataclass(frozen=True)
class _Visit:
    node: int  # chỉ số trong danh sách _Node
    arrive: int  # phút tuyệt đối


@dataclass(frozen=True)
class _Node:
    place: int  # vị trí trong danh sách place đã khử trùng
    arrivals: dict[int, list[Interval]]  # ngày -> các khoảng giờ đến hợp lệ
    slot: int | None = None  # chỉ số slot bữa ăn, None với điểm thường


def solve(
    request: PlanRequest,
    candidates: Sequence[Place],
    travel: TravelTimeProvider,
    seed: int,
    *,
    time_limit_s: float = DEFAULT_TIME_LIMIT_S,
) -> SolveResult:
    """Lịch trình chỉ dùng `candidates`, note luôn None. Cùng đầu vào và seed cho cùng kết quả.

    Thất bại (INFEASIBLE, TIMED_OUT, INVALID) không bao giờ kèm itinerary.
    """
    places = _unique(candidates)
    rng = random.Random(seed)
    slots = _meal_slots(request)
    nodes = _build_nodes(request, places, slots)
    missing = [i for i in range(len(slots)) if not any(n.slot == i for n in nodes)]
    if missing:
        slot = slots[missing[0]]
        return SolveResult(
            SolveStatus.INFEASIBLE,
            detail=f"ngày {slot.day + 1}: không có nhà hàng mở trong khung bữa "
            f"{_clock(slot.start)}-{_clock(slot.end)}",
        )
    targets = [rng.randint(*STOPS_PER_DAY[request.pace]) for _ in range(request.num_days)]
    travel_min = _travel_matrix(request, places, travel)
    preferred = preferred_categories(request.interests)
    bias = [
        INTEREST_BONUS
        - (INTEREST_BONUS if place.category in preferred else 0)
        + rng.randint(0, NOISE_MAX)
        for place in places
    ]
    routes, status, detail = _route(
        request, places, nodes, slots, targets, travel_min, bias, time_limit_s
    )
    if routes is None:
        return SolveResult(status, detail=detail)
    shortfall = _check_routes(request, nodes, slots, routes)
    if shortfall:
        return SolveResult(SolveStatus.INFEASIBLE, detail=shortfall)
    itinerary = _schedule(request, places, nodes, routes)
    if itinerary is None:
        return SolveResult(SolveStatus.INVALID, detail="không dựng lại được giờ từ route")
    report = validate_itinerary(request, itinerary, InMemoryPlaceRepository(places), travel)
    if not report.is_valid:
        return SolveResult(SolveStatus.INVALID, report=report, detail="validator báo ERROR")
    return SolveResult(SolveStatus.SOLVED, itinerary=itinerary, report=report)


def _unique(candidates: Sequence[Place]) -> list[Place]:
    seen: set[str] = set()
    unique: list[Place] = []
    for place in candidates:
        if place.id not in seen:
            seen.add(place.id)
            unique.append(place)
    return unique


def _clock(absolute: int) -> str:
    minute = absolute % MINUTES_PER_DAY
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _meal_slots(request: PlanRequest) -> list[_Slot]:
    """Cùng điều kiện với validator: chỉ bắt bữa khi khung ngày bao trọn khung bữa."""
    slots: list[_Slot] = []
    for day in range(request.num_days):
        base = day * MINUTES_PER_DAY
        for _, start, end in MEAL_WINDOWS:
            if request.day_start <= start and request.day_end >= end:
                slots.append(_Slot(day, base + minute_ceil(start), base + minute_floor(end)))
    return slots


def _arrivals(ranges: Sequence[Interval], bound: Interval, visit: int) -> list[Interval]:
    """Giờ đến sao cho cả lượt thăm nằm gọn trong một khoảng mở cửa và trong `bound`."""
    found: list[Interval] = []
    for start, end in ranges:
        earliest, latest = max(start, bound[0]), min(end, bound[1]) - visit
        if earliest <= latest:
            found.append((earliest, latest))
    return sorted(found)


def _build_nodes(
    request: PlanRequest, places: Sequence[Place], slots: Sequence[_Slot]
) -> list[_Node]:
    nodes: list[_Node] = []
    for index, place in enumerate(places):
        visit = VISIT_MINUTES[place.category]
        if place.category in MEAL_CATEGORIES:
            for slot_index, slot in enumerate(slots):
                ranges = open_ranges(request, place, slot.day)
                day_start, day_end = day_bounds(request, slot.day)
                bound = (max(slot.start, day_start), min(slot.end, day_end))
                found = _arrivals(ranges, bound, visit)
                if found:
                    nodes.append(_Node(index, {slot.day: found}, slot_index))
            continue
        by_day = {
            day: found
            for day in range(request.num_days)
            if (
                found := _arrivals(
                    open_ranges(request, place, day), day_bounds(request, day), visit
                )
            )
        }
        if by_day:
            nodes.append(_Node(index, by_day))
    return nodes


def _travel_matrix(
    request: PlanRequest, places: Sequence[Place], travel: TravelTimeProvider
) -> list[list[int]]:
    """Phút đi lại làm tròn lên, để khoảng trống nguyên luôn >= số phút validator đòi."""
    return [
        [
            0
            if i == j
            else math.ceil(travel.travel_leg(a.coords, b.coords, request.travel_mode).minutes)
            for j, b in enumerate(places)
        ]
        for i, a in enumerate(places)
    ]


_SUCCESS = (
    routing_enums_pb2.RoutingSearchStatus.ROUTING_SUCCESS,
    routing_enums_pb2.RoutingSearchStatus.ROUTING_OPTIMAL,
)
_TIMEOUT = (
    routing_enums_pb2.RoutingSearchStatus.ROUTING_FAIL_TIMEOUT,
    routing_enums_pb2.RoutingSearchStatus.ROUTING_PARTIAL_SUCCESS_LOCAL_OPTIMUM_NOT_REACHED,
)


def _route(
    request: PlanRequest,
    places: Sequence[Place],
    nodes: Sequence[_Node],
    slots: Sequence[_Slot],
    targets: Sequence[int],
    travel_min: Sequence[Sequence[int]],
    bias: Sequence[int],
    time_limit_s: float,
) -> tuple[list[list[_Visit]] | None, SolveStatus, str]:
    """Giải bằng OR-Tools. Trả về (route mỗi ngày, status, chi tiết).

    Node 0 của OR-Tools là depot ảo (không có khách sạn): đi tới/từ depot mất 0 phút.
    Node k+1 ứng với `nodes[k]`.
    """
    if not nodes:
        return None, SolveStatus.INFEASIBLE, "không có địa điểm nào mở trong khung ngày"
    size = len(nodes) + 1
    num_days = request.num_days

    def leg(a: int, b: int) -> int:
        if a == 0 or b == 0:
            return 0
        return travel_min[nodes[a - 1].place][nodes[b - 1].place]

    service = [0, *(VISIT_MINUTES[places[n.place].category] for n in nodes)]
    transit = [[service[a] + leg(a, b) for b in range(size)] for a in range(size)]
    cost = [
        [
            0 if b == 0 else leg(a, b) * TRAVEL_COST_PER_MINUTE + bias[nodes[b - 1].place]
            for b in range(size)
        ]
        for a in range(size)
    ]

    manager = pywrapcp.RoutingIndexManager(size, num_days, 0)
    routing = pywrapcp.RoutingModel(manager)
    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitMatrix(cost))

    time_cb = routing.RegisterTransitMatrix(transit)
    routing.AddDimension(time_cb, MINUTES_PER_DAY, num_days * MINUTES_PER_DAY, False, "time")
    time_dim = routing.GetDimensionOrDie("time")
    # Phạt thời gian chờ; xe xuất phát đúng day_start. Khi ngày có bữa tối cố định, tổng thời gian
    # chờ trước bữa tối không đổi theo thứ tự, nên cần thêm phạt giờ đến (dưới) để buổi sáng được
    # dùng trước thay vì để trống rồi dồn điểm vào buổi chiều.
    time_dim.SetSlackCostCoefficientForAllVehicles(IDLE_COST_PER_MINUTE)
    for day in range(num_days):
        low, high = day_bounds(request, day)
        time_dim.CumulVar(routing.Start(day)).SetRange(low, low)
        time_dim.CumulVar(routing.End(day)).SetRange(low, high)

    # Chỉ đếm điểm thường; chỗ cho bữa ăn được giữ riêng để điểm thường không chiếm mất.
    meals = [sum(1 for slot in slots if slot.day == day) for day in range(num_days)]
    count_cb = routing.RegisterUnaryTransitVector([0, *(int(n.slot is None) for n in nodes)])
    capacities = [max(0, target - meal) for target, meal in zip(targets, meals, strict=True)]
    routing.AddDimensionWithVehicleCapacity(count_cb, 0, capacities, True, "sights")
    # Sàn mềm: thiếu điểm ở một ngày bị phạt nặng hơn bỏ điểm, nên solver chia đều điểm giữa
    # các ngày thay vì lấp đầy ngày đầu rồi để ngày cuối dưới sàn.
    sights_dim = routing.GetDimensionOrDie("sights")
    floor = STOPS_PER_DAY[request.pace][0]
    for day in range(num_days):
        wanted = min(capacities[day], max(0, floor - meals[day]))
        sights_dim.SetCumulVarSoftLowerBound(routing.End(day), wanted, SHORT_DAY_PENALTY)

    by_slot: dict[int, list[int]] = {}
    by_place: dict[int, list[int]] = {}
    for k, node in enumerate(nodes):
        index = manager.NodeToIndex(k + 1)
        windows = [w for day in sorted(node.arrivals) for w in node.arrivals[day]]
        cumul = time_dim.CumulVar(index)
        cumul.SetRange(windows[0][0], windows[-1][1])
        if node.slot is None:
            # Chi phí = giờ đến. Không áp cho bữa ăn, để giờ ăn theo lịch tham quan quanh nó thay
            # vì luôn dính vào đầu khung bữa (11:00, 17:30).
            time_dim.SetCumulVarSoftUpperBound(index, 0, EARLY_COST_PER_MINUTE)
        for (_, prev_end), (next_start, _) in itertools.pairwise(windows):
            if next_start > prev_end + 1:
                cumul.RemoveInterval(prev_end + 1, next_start - 1)
        # SetAllowedVehiclesForIndex hỏng binding Python ở OR-Tools 9.15; -1 = không được xếp.
        routing.VehicleVar(index).SetValues([-1, *sorted(node.arrivals)])
        if node.slot is None:
            routing.AddDisjunction([index], STOP_PENALTY)
        else:
            by_slot.setdefault(node.slot, []).append(index)
            by_place.setdefault(node.place, []).append(index)
    for indices in by_slot.values():
        routing.AddDisjunction(indices, MEAL_PENALTY, 1)
    for indices in by_place.values():
        if len(indices) > 1:
            routing.AddDisjunction(indices, 0, 1)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    )
    # Chỉ hạ dốc tới tối ưu cục bộ: kết quả không phụ thuộc tốc độ máy, nên cùng seed cùng plan.
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GREEDY_DESCENT
    params.time_limit.FromMicroseconds(max(1, int(time_limit_s * 1_000_000)))
    solution = routing.SolveWithParameters(params)
    status = routing.status()
    if status in _TIMEOUT:
        return None, SolveStatus.TIMED_OUT, f"hết {time_limit_s:g} giây trước khi hội tụ"
    if solution is None or status not in _SUCCESS:
        return None, SolveStatus.INFEASIBLE, f"OR-Tools không tìm được lời giải (status {status})"
    routes: list[list[_Visit]] = []
    for day in range(num_days):
        route: list[_Visit] = []
        index = solution.Value(routing.NextVar(routing.Start(day)))
        while not routing.IsEnd(index):
            arrive = int(solution.Value(time_dim.CumulVar(index)))
            route.append(_Visit(int(manager.IndexToNode(index)) - 1, arrive))
            index = solution.Value(routing.NextVar(index))
        routes.append(route)
    return routes, SolveStatus.SOLVED, ""


def _check_routes(
    request: PlanRequest,
    nodes: Sequence[_Node],
    slots: Sequence[_Slot],
    routes: Sequence[Sequence[_Visit]],
) -> str:
    """Kiểm phần mô hình chỉ phạt mềm: sàn số điểm và đủ bữa. Trả chuỗi lỗi, rỗng nếu đạt."""
    low = STOPS_PER_DAY[request.pace][0]
    for day, route in enumerate(routes):
        if len(route) < low:
            return f"ngày {day + 1} chỉ xếp được {len(route)} điểm, cần ít nhất {low}"
    served = {nodes[visit.node].slot for route in routes for visit in route}
    for index, slot in enumerate(slots):
        if index not in served:
            return (
                f"ngày {slot.day + 1}: không xếp được nhà hàng trong khung bữa "
                f"{_clock(slot.start)}-{_clock(slot.end)}"
            )
    return ""


def _schedule(
    request: PlanRequest,
    places: Sequence[Place],
    nodes: Sequence[_Node],
    routes: Sequence[Sequence[_Visit]],
) -> Itinerary | None:
    """Dựng Itinerary từ giờ đến OR-Tools đã chọn; kiểm lại window để bắt lỗi mô hình sớm."""
    days: list[PlannedDay] = []
    for day, route in enumerate(routes):
        stops: list[PlannedStop] = []
        for visit in route:
            node = nodes[visit.node]
            windows = node.arrivals.get(day, [])
            if not any(start <= visit.arrive <= end for start, end in windows):
                return None
            place = places[node.place]
            stops.append(
                PlannedStop(
                    place_id=place.id,
                    arrive=time_of(visit.arrive),
                    depart=time_of(visit.arrive + VISIT_MINUTES[place.category]),
                    note=None,
                )
            )
        if not stops:
            return None
        days.append(PlannedDay(date=request.start_date + dt.timedelta(days=day), stops=stops))
    return Itinerary(days=days)
