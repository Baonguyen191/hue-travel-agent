"""Trích thông tin câu tự do bằng LLM (Ollama, JSON schema), rồi xử lý phần còn lại bằng code.

LLM chỉ chép nguyên văn: intent, cụm ngày, cụm thời lượng, giờ, sở thích, tên địa điểm, yêu cầu
mềm. Code làm mọi phần tính toán: giải ngày theo ngày tham chiếu, đọc số ngày, ánh xạ sở thích
vào 9 interest, liên kết tên địa điểm với DB, điền mặc định, và quyết định có hỏi lại không.

Prompt và few-shot viết tay, không lấy từ bộ eval (data/eval/query_eval_v1.jsonl) để số đo không
bị rò rỉ. Mọi tham số sinh (temperature, seed, num_ctx, num_predict) là hằng số ở training/tài liệu.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from travel_agent.domain.models import Category, Pace, Place, PlanRequest, TravelMode
from travel_agent.training.generator import PlanGenerator
from travel_agent.understanding.dates import resolve_date_text
from travel_agent.understanding.link import link_places
from travel_agent.understanding.models import DurationSpec, Intent, ParsedQuery
from travel_agent.understanding.normalize import map_interests, parse_duration, strip_diacritics

CITY = "hue"
DEFAULT_START = dt.time(8, 0)
DEFAULT_END = dt.time(21, 0)
HALF_DAY_HOURS = 4
MAX_ATTEMPTS = 2  # một lần gọi và một lần thử lại khi JSON sai schema
MAX_DAYS = 7

_CLOCK_PATTERN = "^([01][0-9]|2[0-3]):[0-5][0-9]$"
_CLOCK_RE = re.compile(_CLOCK_PATTERN)
_HUE_NAMES = frozenset({"hue", "thanh pho hue", "tp hue"})
_WEEKDAY_NAMES = ("thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật")

# Cụm loại địa điểm -> Category (đã bỏ dấu khi so). Cụm dài hơn được ưu tiên như nhau: mọi khóa
# khớp đều được lấy, nên "quán cà phê" vẫn ra CAFE qua khóa "ca phe".
_CATEGORY_PHRASES: dict[str, Category] = {
    "cho": Category.MARKET,
    "chua": Category.RELIGIOUS,
    "den tho": Category.RELIGIOUS,
    "lang": Category.HISTORIC,
    "lang tam": Category.HISTORIC,
    "di tich": Category.HISTORIC,
    "bao tang": Category.MUSEUM,
    "ca phe": Category.CAFE,
    "cafe": Category.CAFE,
    "quan an": Category.RESTAURANT,
    "nha hang": Category.RESTAURANT,
    "cong vien": Category.PARK,
}

_DATE_PHRASE_RE = re.compile(
    r"(?<![a-z0-9])("
    r"\d{1,2}\s*[./-]\s*\d{1,2}(?:\s*[./-]\s*\d{4})?(?: nam sau)?"
    r"|(?:ngay )?\d{1,2} thang \d{1,2}(?: nam (?:\d{4}|sau))?"
    r"|(?:dau|giua|cuoi) thang \d{1,2}(?: nam sau)?"
    r"|cuoi tuan(?: (?:nay|toi|sau))?"
    r"|tuan (?:sau|toi)"
    r"|(?:thu (?:\d|hai|ba|tu|nam|sau|bay)|t[2-7]|chu nhat|cn)(?: tuan nay| nay| toi| sau)?"
    # "mốt" một mình là ngày kia; "một" đứng trước danh từ đếm (một ngày, một mình) thì không phải.
    r"|hom nay|ngay mai|ngay kia|ngay mot|mai|mot(?! (?:ngay|hom|buoi|dem|minh|nguoi|chut|lan))"
    r"|tet duong lich|giang sinh|noel"
    r")(?![a-z0-9])"
)

# ---------------------------------------------------------------------------
# Schema đầu ra (Ollama `format`) và model đọc JSON
# ---------------------------------------------------------------------------

_NULLABLE_STRING: dict[str, Any] = {"type": ["string", "null"]}
_STRING_LIST: dict[str, Any] = {"type": "array", "items": {"type": "string"}}

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": [item.value for item in Intent]},
        "date_text": _NULLABLE_STRING,
        "duration_text": _NULLABLE_STRING,
        "travel_mode": {
            "type": ["string", "null"],
            "enum": [*[item.value for item in TravelMode], None],
        },
        "pace": {"type": ["string", "null"], "enum": [*[item.value for item in Pace], None]},
        "day_start": {"type": ["string", "null"], "pattern": _CLOCK_PATTERN},
        "day_end": {"type": ["string", "null"], "pattern": _CLOCK_PATTERN},
        "interest_phrases": _STRING_LIST,
        "must_include_mentions": _STRING_LIST,
        "exclude_mentions": _STRING_LIST,
        "exclude_category_phrases": _STRING_LIST,
        "soft_preferences": _STRING_LIST,
        "city": _NULLABLE_STRING,
    },
    "required": [
        "intent",
        "date_text",
        "duration_text",
        "travel_mode",
        "pace",
        "day_start",
        "day_end",
        "interest_phrases",
        "must_include_mentions",
        "exclude_mentions",
        "exclude_category_phrases",
        "soft_preferences",
        "city",
    ],
    "additionalProperties": False,
}


class Extraction(BaseModel):
    """JSON mà LLM trả về. Giờ là chuỗi HH:MM; code đổi sang dt.time sau."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    date_text: str | None = None
    duration_text: str | None = None
    travel_mode: TravelMode | None = None
    pace: Pace | None = None
    day_start: str | None = None
    day_end: str | None = None
    interest_phrases: list[str] = Field(default_factory=list)
    must_include_mentions: list[str] = Field(default_factory=list)
    exclude_mentions: list[str] = Field(default_factory=list)
    exclude_category_phrases: list[str] = Field(default_factory=list)
    soft_preferences: list[str] = Field(default_factory=list)
    city: str | None = None

    @field_validator("day_start", "day_end")
    @classmethod
    def _clock_format(cls, value: str | None) -> str | None:
        if value is not None and _CLOCK_RE.fullmatch(value) is None:
            raise ValueError("giờ phải dạng HH:MM")
        return value


class ExtractionError(RuntimeError):
    """LLM trả JSON không đúng schema, kể cả sau lần thử lại. Không phải lỗi hạ tầng."""


# ---------------------------------------------------------------------------
# Prompt và few-shot
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Bạn trích thông tin từ một câu nhờ lập lịch du lịch Huế.
Chỉ trả về JSON đúng schema, không giải thích.

Quy tắc chung:
- Chỉ chép nguyên văn từ câu. Không tự tính ngày: "cuối tuần này" giữ nguyên là
  "cuối tuần này", không đổi thành ngày.
- Không suy diễn trường không được nhắc. Không có thì để null (chuỗi, giờ, phương tiện,
  nhịp) hoặc [] (danh sách).

Các trường:
- intent: plan_new (xin lên lịch đi Huế), modify_plan (sửa lịch đã có: bỏ điểm, đổi
  phương tiện, thêm ngày), place_info (hỏi thông tin một địa điểm: giờ mở cửa, giá vé,
  khoảng cách), out_of_scope (không phải du lịch Huế: thành phố khác, thời tiết, đặt vé,
  viết văn...).
- date_text: cụm chỉ thời điểm đi, chép nguyên văn, ví dụ "cuối tuần này", "thứ 7 tới",
  "20/12", "đầu tháng 12", "ngày 3 tháng 1 năm sau".
- duration_text: cụm chỉ số ngày đi, chép nguyên văn, ví dụ "2 ngày", "2n1đ", "nửa ngày".
- travel_mode: walk (đi bộ), motorbike (xe máy, xe số, xe ga), car (ô tô, xe hơi).
  Không nói thì null.
- pace: relaxed chỉ khi người dùng nói rõ muốn nhẹ nhàng, thong thả, chậm rãi; packed khi
  nói lịch dày, càng nhiều càng tốt, tranh thủ; moderate khi nói vừa phải. Không nói rõ
  thì null. Việc đi cùng người lớn tuổi, bố mẹ già hay trẻ nhỏ KHÔNG đổi pace; ghi vào
  soft_preferences.
- day_start, day_end: giờ bắt đầu và giờ kết thúc mỗi ngày, dạng HH:MM 24 giờ, chỉ khi
  người dùng nói rõ giờ.
- interest_phrases: cụm thể hiện một sở thích cụ thể người dùng muốn làm, ví dụ "đi chùa",
  "chụp ảnh", "đặc sản". Chỉ ghi điều người dùng muốn, KHÔNG ghi điều họ không muốn.
  Tên địa điểm cụ thể không ghi ở đây.
- must_include_mentions: tên địa điểm cụ thể người dùng muốn đến, chép đúng cách họ viết
  (kể cả chữ "chùa", "lăng", "chợ" đi kèm).
- exclude_mentions: tên địa điểm cụ thể người dùng không muốn đến, hoặc đã đi rồi nên bỏ qua.
- exclude_category_phrases: loại địa điểm người dùng không muốn. "không đi chợ" ghi "chợ";
  "bỏ bảo tàng" ghi "bảo tàng".
- soft_preferences: yêu cầu khác không có trường riêng, chép nguyên văn cụm: người đi cùng
  (bố mẹ già, trẻ nhỏ, người yêu), yên tĩnh, lãng mạn, ngân sách.
- city: thành phố nơi chuyến đi diễn ra, nếu câu nêu rõ. Không nêu thì null.

Một sở thích cụ thể có thể nằm cả ở interest_phrases và soft_preferences; không bắt buộc.
"""

# Ví dụ viết tay, không chép từ bộ eval. Mỗi ví dụ là (câu, JSON đúng).
_FEW_SHOT: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "Cuối tuần này mình đi Huế hai ngày bằng ô tô, thích đặc sản và đi chùa.",
        {
            "intent": "plan_new",
            "date_text": "Cuối tuần này",
            "duration_text": "hai ngày",
            "travel_mode": "car",
            "pace": None,
            "day_start": None,
            "day_end": None,
            "interest_phrases": ["đặc sản", "đi chùa"],
            "must_include_mentions": [],
            "exclude_mentions": [],
            "exclude_category_phrases": [],
            "soft_preferences": [],
            "city": None,
        },
    ),
    (
        "Bố mẹ mình lớn tuổi rồi, lên lịch thong thả giúp mình: "
        "đi Huế từ 3/1 năm sau trong 2 ngày, xem lăng và bảo tàng.",
        {
            "intent": "plan_new",
            "date_text": "3/1 năm sau",
            "duration_text": "2 ngày",
            "travel_mode": None,
            "pace": "relaxed",
            "day_start": None,
            "day_end": None,
            "interest_phrases": ["lăng", "bảo tàng"],
            "must_include_mentions": [],
            "exclude_mentions": [],
            "exclude_category_phrases": [],
            "soft_preferences": ["bố mẹ lớn tuổi"],
            "city": None,
        },
    ),
    (
        "Lên kế hoạch đi Đà Nẵng 3 ngày từ 10/12 cho mình nhé.",
        {
            "intent": "out_of_scope",
            "date_text": None,
            "duration_text": None,
            "travel_mode": None,
            "pace": None,
            "day_start": None,
            "day_end": None,
            "interest_phrases": [],
            "must_include_mentions": [],
            "exclude_mentions": [],
            "exclude_category_phrases": [],
            "soft_preferences": [],
            "city": "Đà Nẵng",
        },
    ),
    (
        "Lăng Khải Định mở cửa lúc mấy giờ vậy bạn?",
        {
            "intent": "place_info",
            "date_text": None,
            "duration_text": None,
            "travel_mode": None,
            "pace": None,
            "day_start": None,
            "day_end": None,
            "interest_phrases": [],
            "must_include_mentions": ["Lăng Khải Định"],
            "exclude_mentions": [],
            "exclude_category_phrases": [],
            "soft_preferences": [],
            "city": None,
        },
    ),
    (
        "Mình đi Huế 2 ngày, lịch dày, muốn chụp ảnh nhiều. Đừng xếp chợ vào nhé.",
        {
            "intent": "plan_new",
            "date_text": None,
            "duration_text": "2 ngày",
            "travel_mode": None,
            "pace": "packed",
            "day_start": None,
            "day_end": None,
            "interest_phrases": ["chụp ảnh"],
            "must_include_mentions": [],
            "exclude_mentions": [],
            "exclude_category_phrases": ["chợ"],
            "soft_preferences": [],
            "city": None,
        },
    ),
    (
        "Đi Huế 3 ngày bằng xe máy từ ngày 20 tháng 12, ghé chùa Thiên Mụ, "
        "còn Đại Nội thì mình đi rồi nên bỏ qua.",
        {
            "intent": "plan_new",
            "date_text": "ngày 20 tháng 12",
            "duration_text": "3 ngày",
            "travel_mode": "motorbike",
            "pace": None,
            "day_start": None,
            "day_end": None,
            "interest_phrases": [],
            "must_include_mentions": ["chùa Thiên Mụ"],
            "exclude_mentions": ["Đại Nội"],
            "exclude_category_phrases": [],
            "soft_preferences": [],
            "city": None,
        },
    ),
)


def _user_content(text: str, ref: dt.date) -> str:
    weekday = _WEEKDAY_NAMES[ref.weekday()]
    header = f"Hôm nay là {weekday}, {ref.isoformat()} (chỉ để tham khảo, không tự tính ngày)."
    return f"{header}\nCâu: {text}"


def build_extraction_messages(text: str, ref: dt.date) -> list[dict[str, str]]:
    """Prompt đầy đủ: system, các cặp few-shot (user, assistant JSON), rồi câu cần trích."""
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for example_text, answer in _FEW_SHOT:
        messages.append({"role": "user", "content": _user_content(example_text, ref)})
        messages.append({"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)})
    messages.append({"role": "user", "content": _user_content(text, ref)})
    return messages


# ---------------------------------------------------------------------------
# Gọi LLM
# ---------------------------------------------------------------------------


def extract(text: str, ref: dt.date, generator: PlanGenerator) -> Extraction:
    """Gọi LLM tối đa MAX_ATTEMPTS lần, JSON sai schema thì thử lại.

    Lỗi hạ tầng (GenerationError) để nổi lên, không thử lại.
    """
    messages = build_extraction_messages(text, ref)
    last_error: ValidationError | None = None
    for _ in range(MAX_ATTEMPTS):
        generation = generator.generate(messages, format_schema=EXTRACTION_SCHEMA)
        try:
            return Extraction.model_validate_json(generation.content)
        except ValidationError as exc:
            last_error = exc
    raise ExtractionError(f"LLM trả JSON sai schema sau {MAX_ATTEMPTS} lần: {last_error}")


# ---------------------------------------------------------------------------
# Xử lý bằng code
# ---------------------------------------------------------------------------


def _plain(text: str) -> str:
    """Chữ thường không dấu, chỉ còn chữ số, "/", ".", "-" và khoảng trắng."""
    return " ".join(re.sub(r"[^a-z0-9./\- ]", " ", strip_diacritics(text)).split())


def _find_date_phrase(text: str, ref: dt.date) -> tuple[str, dt.date] | None:
    """Cụm ngày đầu tiên trong câu mà resolve_date_text hiểu được (dùng khi LLM bỏ sót)."""
    for match in _DATE_PHRASE_RE.finditer(_plain(text)):
        phrase = match.group(1)
        resolved = resolve_date_text(phrase, ref)
        if resolved is not None:
            return phrase, resolved
    return None


def _resolve_start(
    date_text: str | None, text: str, ref: dt.date
) -> tuple[str | None, dt.date | None]:
    if date_text:
        resolved = resolve_date_text(date_text, ref)
        if resolved is not None:
            return date_text, resolved
    found = _find_date_phrase(text, ref)
    if found is not None:
        return found
    return date_text, None


def _duration(duration_text: str | None, text: str) -> DurationSpec | None:
    if duration_text:
        spec = parse_duration(duration_text)
        if spec is not None:
            return spec
    return parse_duration(text)


def _category_phrases(phrases: Iterable[str]) -> tuple[list[Category], list[str]]:
    """Cụm loại -> Category theo bảng; cụm không khớp được trả về nguyên văn."""
    found: set[Category] = set()
    unmatched: list[str] = []
    for phrase in phrases:
        cleaned = _plain(phrase)
        hits = {
            category for key, category in _CATEGORY_PHRASES.items() if f" {key} " in f" {cleaned} "
        }
        if hits:
            found |= hits
        elif cleaned:
            unmatched.append(phrase)
    return sorted(found, key=lambda item: item.value), unmatched


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        stripped = item.strip()
        if stripped:
            seen.setdefault(stripped, None)
    return list(seen)


def _half_day_end(start: dt.time) -> dt.time | None:
    """Nửa ngày = bốn giờ kể từ giờ bắt đầu; quá nửa đêm thì None."""
    minutes = start.hour * 60 + start.minute + HALF_DAY_HOURS * 60
    if minutes > 23 * 60 + 59:
        return None
    return dt.time(minutes // 60, minutes % 60)


def _clock(text: str | None) -> dt.time | None:
    return dt.time.fromisoformat(text) if text else None


def _clock_text(value: dt.time) -> str:
    return value.strftime("%H:%M")


def _clarification(
    start: dt.date | None, date_text: str | None, num_days: int | None, days_over_limit: bool
) -> str | None:
    """Câu hỏi lại tiếng Việt, hoặc None nếu đã đủ để dựng request."""
    if days_over_limit:
        return f"Mình chỉ lên lịch tối đa {MAX_DAYS} ngày. Bạn muốn đi mấy ngày?"
    if start is None and num_days is None:
        return "Bạn muốn đi Huế từ ngày nào và đi mấy ngày?"
    if start is None:
        if date_text:
            return f'Mình chưa hiểu ngày đi "{date_text}". Bạn muốn đi từ ngày nào?'
        return "Bạn muốn đi Huế từ ngày nào?"
    if num_days is None:
        return "Bạn định đi Huế mấy ngày?"
    return None


def build_parsed_query(
    text: str,
    ref: dt.date,
    extraction: Extraction,
    places: Sequence[Place],
) -> ParsedQuery:
    """Từ JSON của LLM dựng ParsedQuery. Hàm thuần: mọi tính toán nằm ở đây, không gọi mạng."""
    city = extraction.city
    if extraction.intent is Intent.OUT_OF_SCOPE or (
        city is not None and _plain(city) not in _HUE_NAMES
    ):
        return ParsedQuery(intent=Intent.OUT_OF_SCOPE)

    date_text, start = _resolve_start(extraction.date_text, text, ref)
    duration = _duration(extraction.duration_text, text)
    num_days = duration.num_days if duration is not None else None

    interests, unmatched_interests = map_interests(extraction.interest_phrases)
    categories, unmatched_categories = _category_phrases(extraction.exclude_category_phrases)
    soft = _dedupe([*extraction.soft_preferences, *unmatched_interests, *unmatched_categories])
    must_include = link_places(extraction.must_include_mentions, places)
    exclude = link_places(extraction.exclude_mentions, places)

    day_start = _clock(extraction.day_start)
    day_end = _clock(extraction.day_end)
    if day_end is None and duration is not None and duration.half_day:
        day_end = _half_day_end(day_start or DEFAULT_START)

    partial: dict[str, object] = {
        "interests": interests,
        "soft_preferences": soft,
    }
    if start is not None:
        partial["start_date"] = start.isoformat()
    if num_days is not None:
        partial["num_days"] = num_days
    if extraction.travel_mode is not None:
        partial["travel_mode"] = extraction.travel_mode.value
    if extraction.pace is not None:
        partial["pace"] = extraction.pace.value
    if day_start is not None:
        partial["day_start"] = _clock_text(day_start)
    if day_end is not None:
        partial["day_end"] = _clock_text(day_end)

    base: dict[str, Any] = {
        "intent": extraction.intent,
        "date_text": date_text,
        "must_include": must_include,
        "exclude": exclude,
        "exclude_categories": categories,
        "soft_preferences": soft,
        "partial": partial,
    }
    if extraction.intent is not Intent.PLAN_NEW:
        return ParsedQuery(**base)

    days_over_limit = num_days is not None and num_days > MAX_DAYS
    question = _clarification(start, date_text, num_days, days_over_limit)
    if question is None and day_start is not None and day_end is not None:
        if day_end <= day_start:
            question = "Giờ kết thúc phải sau giờ bắt đầu. Bạn muốn đi từ mấy giờ đến mấy giờ?"
    if question is not None:
        return ParsedQuery(**base, clarification=question)

    defaulted: list[str] = []
    if extraction.travel_mode is None:
        defaulted.append("travel_mode")
    if extraction.pace is None:
        defaulted.append("pace")
    if day_start is None:
        defaulted.append("day_start")
    if day_end is None:
        defaulted.append("day_end")
    request = PlanRequest(
        start_date=start if start is not None else ref,
        num_days=num_days if num_days is not None else 1,
        day_start=day_start or DEFAULT_START,
        day_end=day_end or DEFAULT_END,
        travel_mode=extraction.travel_mode or TravelMode.MOTORBIKE,
        pace=extraction.pace or Pace.MODERATE,
        interests=interests,
    )
    return ParsedQuery(**base, request=request, defaulted=defaulted)


def parse_query(
    text: str,
    ref: dt.date,
    generator: PlanGenerator,
    places: Sequence[Place],
) -> ParsedQuery:
    """Câu tự do -> ParsedQuery. Lỗi LLM sai JSON sau thử lại thì raise ExtractionError."""
    extraction = extract(text, ref, generator)
    return build_parsed_query(text, ref, extraction, places)
