"""Kiểm dataset SFT trước khi train. Hỏng một điều kiện là chặn train.

Kiểm từng mẫu: đúng schema, key khớp request, không trùng bộ eval, không lặp request, prompt dựng
lại từ `build_messages` khớp từng ký tự, đáp án parse được, đúng dạng chuẩn và qua validator không
ERROR với chính candidate của mẫu, độ dài token trong giới hạn. Mẫu repair: plan hỏng trong prompt
phải thật sự có ERROR. Cuối cùng kiểm phân bố số ngày, pace, travel_mode.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from enum import StrEnum

from pydantic import BaseModel, ValidationError

from travel_agent.data.place_repository import InMemoryPlaceRepository, PlaceLookup
from travel_agent.domain.models import Place
from travel_agent.planning.prompt import build_messages, format_itinerary
from travel_agent.routing.travel_time import TravelTimeProvider
from travel_agent.training.dataset import (
    DISTRIBUTION_VALUES,
    CheckParams,
    DatasetSample,
    SampleKind,
    distribution,
)
from travel_agent.training.parsing import parse_itinerary
from travel_agent.training.requests import request_key
from travel_agent.training.tokens import TokenCounter
from travel_agent.validation.report import Severity
from travel_agent.validation.validator import validate_itinerary

MAX_LISTED_FAILURES = 50  # báo cáo liệt kê tối đa chừng này lỗi; số đếm theo loại vẫn đủ


class Check(StrEnum):
    SCHEMA = "schema"
    KEY_MISMATCH = "key_mismatch"
    EVAL_LEAK = "eval_leak"
    DUPLICATE_REQUEST = "duplicate_request"
    UNKNOWN_CANDIDATE = "unknown_candidate"
    ROLES = "roles"
    PROMPT_MISMATCH = "prompt_mismatch"
    ANSWER_PARSE = "answer_parse"
    ANSWER_FORMAT = "answer_format"
    ANSWER_INVALID = "answer_invalid"
    REPAIR_FIELDS = "repair_fields"
    BROKEN_PARSE = "broken_parse"
    BROKEN_VALID = "broken_valid"
    TOO_LONG = "too_long"
    TOKENS_NOT_CHECKED = "tokens_not_checked"
    DISTRIBUTION = "distribution"
    EMPTY = "empty"


class Failure(BaseModel):
    check: Check
    message: str
    line: int | None = None  # dòng trong JSONL, đếm từ 1
    key: str | None = None


class CheckReport(BaseModel):
    samples: int
    samples_by_kind: dict[str, int]
    passed: bool
    failure_counts: dict[str, int]
    failures: list[Failure]  # tối đa MAX_LISTED_FAILURES lỗi đầu tiên
    token_check: str  # "performed" | "skipped" | "missing"
    max_tokens_allowed: int
    max_tokens_seen: int | None
    answer_warning_counts: dict[str, int]
    distribution: dict[str, dict[str, int]]


ROLES = ["system", "user", "assistant"]
_Fail = Callable[[Check, str], None]


def check_dataset(
    lines: Iterable[str],
    places: PlaceLookup,
    eval_keys: set[str],
    params: CheckParams,
    travel: TravelTimeProvider,
    count_tokens: TokenCounter | None,
    *,
    allow_skip_tokens: bool = False,
) -> CheckReport:
    """`count_tokens=None` nghĩa là không có tokenizer thật: là lỗi, trừ khi cho phép bỏ qua."""
    failures: list[Failure] = []
    seen: set[str] = set()
    samples: list[DatasetSample] = []
    warnings: Counter[str] = Counter()
    longest: int | None = None

    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            sample = DatasetSample.model_validate_json(line)
        except ValidationError as exc:
            failures.append(Failure(check=Check.SCHEMA, message=_short(exc), line=line_no))
            continue
        samples.append(sample)

        def fail(
            check: Check, message: str, *, _line: int = line_no, _key: str = sample.key
        ) -> None:
            failures.append(Failure(check=check, message=message, line=_line, key=_key))

        _check_one(sample, places, eval_keys, travel, seen, warnings, fail)
        if count_tokens is not None:
            tokens = count_tokens(sample.messages)
            longest = tokens if longest is None else max(longest, tokens)
            if tokens > params.max_tokens:
                fail(Check.TOO_LONG, f"{tokens} token > giới hạn {params.max_tokens}")

    if not samples:
        failures.append(Failure(check=Check.EMPTY, message="dataset không có mẫu nào"))
    token_check = "performed"
    if count_tokens is None:
        token_check = "skipped" if allow_skip_tokens else "missing"
        if not allow_skip_tokens:
            failures.append(
                Failure(
                    check=Check.TOKENS_NOT_CHECKED,
                    message="chưa kiểm độ dài token: không nạp được tokenizer thật",
                )
            )
    dist = distribution(sample.request for sample in samples)
    failures.extend(_check_distribution(dist, len(samples), params))

    by_kind = Counter(sample.kind.value for sample in samples)
    return CheckReport(
        samples=len(samples),
        samples_by_kind={kind.value: by_kind[kind.value] for kind in SampleKind},
        passed=not failures,
        failure_counts=dict(sorted(Counter(f.check.value for f in failures).items())),
        failures=failures[:MAX_LISTED_FAILURES],
        token_check=token_check,
        max_tokens_allowed=params.max_tokens,
        max_tokens_seen=longest,
        answer_warning_counts=dict(sorted(warnings.items())),
        distribution=dist,
    )


def _check_one(
    sample: DatasetSample,
    places: PlaceLookup,
    eval_keys: set[str],
    travel: TravelTimeProvider,
    seen: set[str],
    warnings: Counter[str],
    fail: _Fail,
) -> None:
    key = request_key(sample.request)
    if key != sample.key:
        fail(Check.KEY_MISMATCH, f"key ghi {sample.key}, tính lại từ request là {key}")
    if key in eval_keys:
        fail(Check.EVAL_LEAK, f"request {key} có trong bộ eval")
    if key in seen:
        fail(Check.DUPLICATE_REQUEST, f"request {key} xuất hiện nhiều lần")
    seen.add(key)

    resolved = [places.get(place_id) for place_id in sample.candidate_ids]
    missing = [pid for pid, place in zip(sample.candidate_ids, resolved, strict=True) if not place]
    if missing:
        fail(Check.UNKNOWN_CANDIDATE, f"candidate không có trong DB: {', '.join(missing[:5])}")
        return
    candidates: list[Place] = [place for place in resolved if place is not None]
    lookup = InMemoryPlaceRepository(candidates)

    roles = [message.get("role") for message in sample.messages]
    if roles != ROLES:
        fail(Check.ROLES, f"vai trò {roles}, cần {ROLES}")
        return

    expected = _expected_prompt(sample, candidates, lookup, travel, fail)
    if expected is not None and expected != sample.messages[:2]:
        fail(Check.PROMPT_MISMATCH, "prompt không khớp build_messages dựng lại từ request")

    answer_text = sample.messages[2].get("content", "")
    answer = parse_itinerary(answer_text)
    if answer is None:
        fail(Check.ANSWER_PARSE, "đáp án không parse được thành Itinerary")
        return
    if format_itinerary(answer) != answer_text:
        fail(Check.ANSWER_FORMAT, "đáp án không đúng dạng chuẩn (thứ tự khóa, giờ HH:MM, JSON gọn)")
    report = validate_itinerary(sample.request, answer, lookup, travel)
    for issue in report.errors():
        fail(Check.ANSWER_INVALID, f"{issue.code.value}: {issue.message}")
    for issue in report.issues:
        if issue.severity is Severity.WARNING:
            warnings[issue.code.value] += 1
    if sample.broken is not None and sample.broken == answer_text:
        fail(Check.BROKEN_VALID, "plan hỏng trùng với đáp án")


def _expected_prompt(
    sample: DatasetSample,
    candidates: list[Place],
    lookup: InMemoryPlaceRepository,
    travel: TravelTimeProvider,
    fail: _Fail,
) -> list[dict[str, str]] | None:
    if sample.kind is SampleKind.GENERATE:
        if sample.broken is not None or sample.corruption is not None:
            fail(Check.REPAIR_FIELDS, "mẫu sinh plan không được có broken/corruption")
        return build_messages(sample.request, candidates)
    if sample.broken is None or sample.corruption is None:
        fail(Check.REPAIR_FIELDS, "mẫu repair thiếu broken hoặc corruption")
        return None
    broken = parse_itinerary(sample.broken)
    if broken is None:
        fail(Check.BROKEN_PARSE, "plan hỏng không parse được thành Itinerary")
        return None
    report = validate_itinerary(sample.request, broken, lookup, travel)
    if report.is_valid:
        fail(Check.BROKEN_VALID, "plan hỏng trong prompt repair không có ERROR nào")
        return None
    return build_messages(sample.request, candidates, broken=broken, issues=report.issues)


def _check_distribution(
    dist: dict[str, dict[str, int]], total: int, params: CheckParams
) -> list[Failure]:
    if total == 0:
        return []
    bounds = params.distribution
    found: list[Failure] = []
    for name, values in DISTRIBUTION_VALUES.items():
        for value in values:
            share = dist[name][value] / total
            if not bounds.min_share <= share <= bounds.max_share:
                found.append(
                    Failure(
                        check=Check.DISTRIBUTION,
                        message=f"{name}={value} chiếm {share:.3f}, ngoài khoảng "
                        f"[{bounds.min_share}, {bounds.max_share}]",
                    )
                )
    return found


def _short(exc: ValidationError) -> str:
    first = exc.errors()[0]
    location = ".".join(str(part) for part in first["loc"])
    return f"{location}: {first['msg']}" if location else str(first["msg"])
