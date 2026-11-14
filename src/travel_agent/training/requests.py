"""Sinh PlanRequest đa dạng và bộ eval đóng băng (dev/test)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from travel_agent.domain.models import Pace, PlanRequest, TravelMode
from travel_agent.planning.candidates import INTEREST_CATEGORIES

EVAL_SIZE = 100
TEST_SIZE = 30

BASE_DATE = dt.date(2026, 12, 1)
DATE_SPAN_DAYS = 28
NUM_DAYS_CHOICES = (1, 2, 3)
DAY_STARTS = (dt.time(7, 30), dt.time(8, 0), dt.time(9, 0))
DAY_ENDS = (dt.time(18, 0), dt.time(20, 0), dt.time(21, 0))
MAX_INTERESTS = 3


class Split(StrEnum):
    DEV = "dev"
    TEST = "test"


class EvalEntry(BaseModel):
    key: str
    split: Split
    request: PlanRequest


def request_key(request: PlanRequest) -> str:
    canonical = json.dumps(request.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _random_request(rng: random.Random) -> PlanRequest:
    interest_count = rng.randint(1, MAX_INTERESTS)
    return PlanRequest(
        start_date=BASE_DATE + dt.timedelta(days=rng.randrange(DATE_SPAN_DAYS)),
        num_days=rng.choice(NUM_DAYS_CHOICES),
        day_start=rng.choice(DAY_STARTS),
        day_end=rng.choice(DAY_ENDS),
        travel_mode=rng.choice(list(TravelMode)),
        pace=rng.choice(list(Pace)),
        interests=sorted(rng.sample(sorted(INTEREST_CATEGORIES), interest_count)),
    )


ATTEMPTS_PER_REQUEST = 100


def generate_requests(count: int, seed: int, max_attempts: int | None = None) -> list[PlanRequest]:
    """`count` request khác nhau; báo lỗi thay vì lặp mãi khi không gian request không đủ lớn."""
    rng = random.Random(seed)
    limit = count * ATTEMPTS_PER_REQUEST if max_attempts is None else max_attempts
    by_key: dict[str, PlanRequest] = {}
    attempts = 0
    while len(by_key) < count:
        if attempts >= limit:
            raise ValueError(
                f"không đủ request khác nhau: cần {count}, có {len(by_key)} sau {limit} lần thử"
            )
        attempts += 1
        request = _random_request(rng)
        by_key.setdefault(request_key(request), request)
    return list(by_key.values())


def build_eval_set(seed: int) -> list[EvalEntry]:
    """Xếp theo key (hash) rồi cắt: 30 entry đầu là test, còn lại là dev."""
    requests = sorted(generate_requests(EVAL_SIZE, seed), key=request_key)
    return [
        EvalEntry(
            key=request_key(request),
            split=Split.TEST if index < TEST_SIZE else Split.DEV,
            request=request,
        )
        for index, request in enumerate(requests)
    ]


def write_eval_set(entries: Sequence[EvalEntry], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for entry in entries:
            handle.write(entry.model_dump_json() + "\n")


def read_eval_set(path: Path, split: Split | None = None) -> list[EvalEntry]:
    lines = path.read_text(encoding="utf-8").splitlines()
    entries = [EvalEntry.model_validate_json(line) for line in lines if line.strip()]
    return [entry for entry in entries if split is None or entry.split is split]
