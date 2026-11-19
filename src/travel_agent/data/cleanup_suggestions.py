"""Gợi ý dọn dữ liệu địa điểm. Chỉ đề xuất, không tự sửa DB.

Ba loại gợi ý:
- duplicate: cặp trùng tên (giống nhau hoặc tên này nằm trong tên kia), cùng nhóm loại,
  cách nhau dưới 300 m.
- category: tên chứa từ khóa không khớp loại hiện tại (cầu, lăng, nhà thờ, biển, cafe...).
- missing_data: địa điểm nhiều lượt đánh giá nhất thiếu giờ mở cửa hoặc thời lượng tham quan.

Mọi hàm ở đây là hàm thuần: nhận danh sách Place đã áp override của người duyệt, không đọc
hay ghi DB. Người duyệt xác nhận rồi mới sửa qua `travel-agent review`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from travel_agent.domain.models import Category, Place
from travel_agent.domain.opening_hours import parse_opening_hours
from travel_agent.planning.candidates import popularity_score
from travel_agent.routing.travel_time import haversine_m

DUPLICATE_RADIUS_M = 300.0
# 300 m tương ứng khoảng 0,0027 độ vĩ độ; dùng cửa sổ 0,003 để bỏ nhanh cặp xa nhau.
_LAT_WINDOW_DEG = 0.003
# Tên đã chuẩn hóa ngắn hơn ngưỡng này không được coi là "nằm trong" tên khác,
# tránh một từ ngắn như "cầu" khớp với mọi tên có chứa nó.
MIN_CONTAIN_CHARS = 6
# Từ bỏ qua khi so tên: "Chợ Đông Ba Huế" và "Chợ Đông Ba" là cùng một tên.
NOISE_WORDS = frozenset({"hue"})
REVIEW_KEY = "Đánh giá"
DURATION_KEY = "Thời gian trải nghiệm TB (phút)"
TOP_POPULAR = 100

KIND_DUPLICATE = "duplicate"
KIND_CATEGORY = "category"
KIND_MISSING = "missing_data"
KIND_ORDER = (KIND_DUPLICATE, KIND_CATEGORY, KIND_MISSING)

# Các nhóm loại coi là tương thích khi trùng tên: cùng nhóm nghĩa là cùng kiểu điểm đến.
_COMPATIBLE_GROUPS: tuple[frozenset[Category], ...] = (
    frozenset(
        {
            Category.ATTRACTION,
            Category.HISTORIC,
            Category.MUSEUM,
            Category.VIEWPOINT,
            Category.PARK,
            Category.RELIGIOUS,
        }
    ),
    frozenset({Category.RESTAURANT, Category.CAFE}),
)

_REVIEWS_RE = re.compile(r"\((\d[\d.,]*)\s*lượt")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def strip_diacritics(text: str) -> str:
    """Bỏ dấu tiếng Việt: "Đông Ba" thành "Dong Ba". Phải thay đ/Đ trước vì NFD không tách được."""
    composed = unicodedata.normalize("NFC", text).replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", composed)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def normalize_name(name: str) -> str:
    """Tên để so khớp: không dấu, chữ thường, bỏ dấu câu và từ "Huế"/"Hue", gọn khoảng trắng."""
    tokens = _NON_ALNUM_RE.sub(" ", strip_diacritics(name).lower()).split()
    return " ".join(token for token in tokens if token not in NOISE_WORDS)


def name_relation(a: str, b: str) -> str | None:
    """Quan hệ giữa hai tên đã chuẩn hóa: giống hệt, hoặc tên ngắn nằm trọn trong tên dài."""
    if not a or not b:
        return None
    if a == b:
        return "tên giống nhau sau chuẩn hóa"
    shorter, longer = sorted((a, b), key=len)
    if len(shorter) >= MIN_CONTAIN_CHARS and f" {shorter} " in f" {longer} ":
        return "tên này nằm trong tên kia"
    return None


def categories_compatible(a: Category, b: Category) -> bool:
    return a == b or any(a in group and b in group for group in _COMPATIBLE_GROUPS)


def review_count(place: Place) -> int:
    """Số lượt đánh giá đọc từ thuộc tính "Đánh giá" (vd "4.6/5 (60 lượt, Google)"); 0 nếu thiếu."""
    match = _REVIEWS_RE.search(place.attributes.get(REVIEW_KEY, ""))
    if match is None:
        return 0
    digits = re.sub(r"\D", "", match.group(1))
    return int(digits) if digits else 0


@dataclass(frozen=True)
class DuplicatePair:
    dropped: Place
    kept: Place
    distance_m: float
    reason: str


def choose_kept(a: Place, b: Place) -> tuple[Place, Place]:
    """Trả về (giữ, bỏ): nhiều thuộc tính hơn, rồi nhiều lượt đánh giá hơn, rồi id nhỏ hơn."""
    kept, dropped = sorted((a, b), key=lambda p: (-len(p.attributes), -review_count(p), p.id))
    return kept, dropped


def duplicate_pair(a: Place, b: Place, a_norm: str, b_norm: str) -> DuplicatePair | None:
    """Trả về cặp trùng nếu thỏa: quan hệ tên, loại tương thích, khoảng cách dưới 300 m."""
    relation = name_relation(a_norm, b_norm)
    if relation is None or not categories_compatible(a.category, b.category):
        return None
    distance = haversine_m(a.coords, b.coords)
    if distance >= DUPLICATE_RADIUS_M:
        return None
    kept, dropped = choose_kept(a, b)
    return DuplicatePair(dropped=dropped, kept=kept, distance_m=distance, reason=relation)


def find_duplicate_pairs(places: Sequence[Place]) -> list[DuplicatePair]:
    norms = {place.id: normalize_name(place.name) for place in places}
    ordered = sorted(places, key=lambda p: p.coords.lat)
    pairs: list[DuplicatePair] = []
    for i, a in enumerate(ordered):
        for b in ordered[i + 1 :]:
            if b.coords.lat - a.coords.lat >= _LAT_WINDOW_DEG:
                break
            pair = duplicate_pair(a, b, norms[a.id], norms[b.id])
            if pair is not None:
                pairs.append(pair)
    return pairs


@dataclass(frozen=True)
class KeywordRule:
    label: str
    # None: chỉ cảnh báo, người duyệt quyết định (không có loại phù hợp trong Category).
    suggested: Category | None
    # None: áp cho mọi loại, trừ loại đã bằng `suggested`.
    from_categories: frozenset[Category] | None
    # Khớp theo từ trên tên đã bỏ dấu.
    keywords: tuple[str, ...] = ()
    # Khớp theo từ trên tên đúng dấu: dùng cho từ dễ nhầm ("lăng" với "làng", "đồi" với "đôi").
    exact: tuple[str, ...] = ()
    # Tên đã bỏ dấu chứa cụm này thì không khớp ("Lăng Cô" là địa danh, không phải lăng mộ).
    exclude: tuple[str, ...] = ()


_SHOP_KEYWORDS = ("vincom", "aeon", "sieu thi", "mall", "cua hang", "keo", "dac san")

CATEGORY_RULES: tuple[KeywordRule, ...] = (
    KeywordRule(
        label="cầu nhưng xếp vào công viên",
        suggested=Category.VIEWPOINT,
        from_categories=frozenset({Category.PARK}),
        keywords=("cau",),
    ),
    KeywordRule(
        label="trung tâm thương mại, siêu thị hoặc cửa hàng, không phải chợ truyền thống",
        suggested=None,
        from_categories=frozenset({Category.MARKET}),
        keywords=_SHOP_KEYWORDS,
    ),
    KeywordRule(
        label="bãi biển nhưng xếp vào điểm tham quan",
        suggested=Category.PARK,
        from_categories=frozenset({Category.ATTRACTION}),
        keywords=("bien",),
    ),
    KeywordRule(
        label="phá hoặc đầm nhưng xếp vào điểm tham quan",
        suggested=Category.PARK,
        from_categories=frozenset({Category.ATTRACTION}),
        keywords=("pha", "dam"),
    ),
    KeywordRule(
        label="thác nước nhưng xếp vào điểm tham quan",
        suggested=Category.PARK,
        from_categories=frozenset({Category.ATTRACTION}),
        keywords=("thac",),
    ),
    KeywordRule(
        label="hồ nhưng xếp vào điểm tham quan",
        suggested=Category.PARK,
        from_categories=frozenset({Category.ATTRACTION}),
        exact=("hồ",),
    ),
    KeywordRule(
        label="đồi hoặc núi nhưng xếp vào điểm tham quan",
        suggested=Category.VIEWPOINT,
        from_categories=frozenset({Category.ATTRACTION}),
        exact=("đồi", "núi"),
    ),
    KeywordRule(
        label="nhà thờ phải xếp tôn giáo",
        suggested=Category.RELIGIOUS,
        from_categories=None,
        keywords=("nha tho",),
        # "Lăng mộ và nhà thờ ..." là khu lăng mộ có nhà thờ họ: vẫn là di tích, không đổi.
        exclude=("lang", "mo"),
    ),
    KeywordRule(
        label="lăng mộ phải xếp di tích lịch sử",
        suggested=Category.HISTORIC,
        from_categories=None,
        exact=("lăng",),
        exclude=("lang co",),
    ),
    KeywordRule(
        label="tên ghi cafe hoặc coffee nhưng xếp nhà hàng",
        suggested=Category.CAFE,
        from_categories=frozenset({Category.RESTAURANT}),
        keywords=("cafe", "coffee", "ca phe"),
        # "Nhà hàng & Café", "Restaurant & Café" vừa là nhà hàng vừa là cafe: không đổi.
        exclude=("nha hang", "restaurant"),
    ),
    KeywordRule(
        label="tên ghi nhà hàng nhưng xếp cafe (yếu, cần xem lại)",
        suggested=Category.RESTAURANT,
        from_categories=frozenset({Category.CAFE}),
        keywords=("nha hang",),
    ),
)


@dataclass(frozen=True)
class CategorySuspect:
    rule: KeywordRule
    keyword: str


def matched_keyword(rule: KeywordRule, name: str) -> str | None:
    normalized = f" {normalize_name(name)} "
    if any(f" {phrase} " in normalized for phrase in rule.exclude):
        return None
    for keyword in rule.keywords:
        if f" {keyword} " in normalized:
            return keyword
    exact_name = unicodedata.normalize("NFC", name).lower()
    for keyword in rule.exact:
        if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", exact_name):
            return keyword
    return None


def category_suspect(place: Place) -> CategorySuspect | None:
    """Quy tắc đầu tiên khớp (thứ tự trong CATEGORY_RULES từ cụ thể đến chung).

    Chỉ một gợi ý cho mỗi địa điểm: "Thác Nhị Hồ" là thác, không phải hồ.
    """
    for rule in CATEGORY_RULES:
        if rule.from_categories is None:
            if place.category == rule.suggested:
                continue
        elif place.category not in rule.from_categories:
            continue
        keyword = matched_keyword(rule, place.name)
        if keyword is not None:
            return CategorySuspect(rule=rule, keyword=keyword)
    return None


def missing_key_data(place: Place) -> list[str]:
    missing: list[str] = []
    if place.opening_hours_raw is None:
        missing.append("thiếu giờ mở cửa")
    elif parse_opening_hours(place.opening_hours_raw) is None:
        missing.append("giờ mở cửa không đọc được")
    if not place.attributes.get(DURATION_KEY, "").strip():
        missing.append("thiếu thời lượng tham quan")
    return missing


def top_popular(places: Sequence[Place], n: int) -> list[Place]:
    return sorted(places, key=lambda p: (-popularity_score(p), p.id))[:n]


CSV_FIELDS = (
    "kind",
    "place_id",
    "name",
    "category",
    "status",
    "other_place_id",
    "other_name",
    "distance_m",
    "suggested_category",
    "matched_keyword",
    "reason",
    "suggested_action",
)


@dataclass(frozen=True)
class Suggestion:
    kind: str
    place_id: str
    name: str
    category: str
    status: str
    other_place_id: str = ""
    other_name: str = ""
    distance_m: str = ""
    suggested_category: str = ""
    matched_keyword: str = ""
    reason: str = ""
    suggested_action: str = ""

    def as_row(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}


def build_suggestions(
    places: Sequence[Place],
    statuses: Mapping[str, str],
    *,
    top_n: int = TOP_POPULAR,
) -> list[Suggestion]:
    """`places` đã áp override, đã bỏ loại REJECTED. `statuses` ánh xạ id sang trạng thái duyệt."""
    rows: list[Suggestion] = []
    for pair in find_duplicate_pairs(places):
        dropped = pair.dropped
        rows.append(
            Suggestion(
                kind=KIND_DUPLICATE,
                place_id=dropped.id,
                name=dropped.name,
                category=dropped.category.value,
                status=statuses.get(dropped.id, "pending"),
                other_place_id=pair.kept.id,
                other_name=pair.kept.name,
                distance_m=f"{pair.distance_m:.0f}",
                reason=f"{pair.reason}; cách {pair.distance_m:.0f} m; loại tương thích",
                suggested_action=f"gộp: giữ {pair.kept.id}",
            )
        )
    for place in places:
        suspect = category_suspect(place)
        if suspect is None:
            continue
        target = suspect.rule.suggested
        rows.append(
            Suggestion(
                kind=KIND_CATEGORY,
                place_id=place.id,
                name=place.name,
                category=place.category.value,
                status=statuses.get(place.id, "pending"),
                suggested_category="" if target is None else target.value,
                matched_keyword=suspect.keyword,
                reason=suspect.rule.label,
                suggested_action=(
                    f"đổi loại thành {target.value} nếu xác nhận"
                    if target is not None
                    else "giữ market; người duyệt quyết định vì không có loại shop"
                ),
            )
        )
    for place in top_popular(places, top_n):
        missing = missing_key_data(place)
        if not missing:
            continue
        rows.append(
            Suggestion(
                kind=KIND_MISSING,
                place_id=place.id,
                name=place.name,
                category=place.category.value,
                status=statuses.get(place.id, "pending"),
                reason=f"{', '.join(missing)}; {review_count(place)} lượt đánh giá",
                suggested_action=(
                    "tra nguồn kiểm chứng rồi sửa trong travel-agent review "
                    "(giờ mở cửa cần evidence)"
                ),
            )
        )
    return rows


def count_by_kind(rows: Sequence[Suggestion]) -> dict[str, int]:
    counts = dict.fromkeys(KIND_ORDER, 0)
    for row in rows:
        counts[row.kind] = counts.get(row.kind, 0) + 1
    return counts
