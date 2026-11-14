"""Dựng dataset SFT: mẫu sinh plan và mẫu repair, nhãn lấy từ solver. Logic thuần, xác định.

Cùng config, cùng DB và cùng bộ eval thì cho ra đúng từng byte của file JSONL: mọi seed con
được suy ra từ `request_seed` và key của request, không phụ thuộc thứ tự hay giờ máy.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from travel_agent.domain.models import Itinerary, Pace, Place, PlanRequest, TravelMode
from travel_agent.planning.candidates import select_candidates
from travel_agent.planning.prompt import build_messages, format_itinerary
from travel_agent.planning.solver import DEFAULT_TIME_LIMIT_S, solve
from travel_agent.routing.travel_time import TravelTimeProvider
from travel_agent.training.corrupt import CorruptionKind, corrupt
from travel_agent.training.requests import (
    NUM_DAYS_CHOICES,
    generate_requests,
    read_eval_set,
    request_key,
)


class DatasetParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    request_seed: int
    target_samples: int = Field(gt=0)
    repair_share: float = Field(ge=0, le=1)
    max_requests: int = Field(gt=0)  # trần số request sinh ra để đạt target
    solver_time_limit_s: float = Field(gt=0, default=DEFAULT_TIME_LIMIT_S)
    corruption_kinds: list[CorruptionKind] = Field(
        default_factory=lambda: list(CorruptionKind), min_length=1
    )


class TokenizerRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo: str = Field(min_length=1)  # repo Hugging Face của model sẽ train
    revision: str = Field(min_length=1)  # commit snapshot, để số token không đổi khi repo đổi


class ShareBounds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_share: float = Field(ge=0, le=1)
    max_share: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> ShareBounds:
        if self.min_share > self.max_share:
            raise ValueError("min_share phải <= max_share")
        return self


class CheckParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_tokens: int = Field(gt=0)  # bằng max_seq của SFT
    tokenizer: TokenizerRef
    # Tỉ lệ mỗi giá trị (mỗi số ngày, mỗi pace, mỗi travel_mode) phải nằm trong khoảng này.
    distribution: ShareBounds


class DatasetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: DatasetParams
    check: CheckParams


def load_config(path: Path) -> DatasetConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return DatasetConfig.model_validate(raw)


class SampleKind(StrEnum):
    GENERATE = "generate"
    REPAIR = "repair"


class DatasetSample(BaseModel):
    """Một dòng JSONL. `messages` là thứ đưa vào SFT; các trường khác để kiểm và truy vết."""

    model_config = ConfigDict(extra="forbid")

    key: str
    kind: SampleKind
    corruption: CorruptionKind | None = None
    request: PlanRequest
    candidate_ids: list[str]
    broken: str | None = None  # plan hỏng trong prompt repair, đúng chuỗi có trong prompt
    messages: list[dict[str, str]]


# Các trường phân bố mà manifest ghi và bước kiểm đặt ngưỡng.
DISTRIBUTION_VALUES: dict[str, tuple[str, ...]] = {
    "num_days": tuple(str(days) for days in NUM_DAYS_CHOICES),
    "pace": tuple(pace.value for pace in Pace),
    "travel_mode": tuple(mode.value for mode in TravelMode),
}


def distribution_key(request: PlanRequest) -> dict[str, str]:
    return {
        "num_days": str(request.num_days),
        "pace": request.pace.value,
        "travel_mode": request.travel_mode.value,
    }


def distribution(requests: Iterable[PlanRequest]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = {name: Counter() for name in DISTRIBUTION_VALUES}
    for request in requests:
        for name, value in distribution_key(request).items():
            counts[name][value] += 1
    return {
        name: {value: counts[name][value] for value in values}
        for name, values in DISTRIBUTION_VALUES.items()
    }


def derive_seed(base: int, key: str, purpose: str) -> int:
    """Seed con độc lập cho từng (request, mục đích); không phụ thuộc thứ tự xử lý."""
    digest = hashlib.sha256(f"{base}:{purpose}:{key}".encode()).hexdigest()
    return int(digest[:8], 16)


def eval_keys(path: Path) -> set[str]:
    """Key của mọi request trong bộ eval, cả dev lẫn test. Key tính lại từ request, không tin trường
    `key` ghi trong file."""
    return {request_key(entry.request) for entry in read_eval_set(path)}


@dataclass
class BuildStats:
    requests_generated: int = 0
    eval_collisions_removed: int = 0
    requests_used: int = 0
    solver_dropped: Counter[str] = field(default_factory=Counter)
    repair_fallbacks: int = 0  # request định làm repair nhưng không kiểu phá nào áp dụng được


@dataclass(frozen=True)
class BuildResult:
    samples: list[DatasetSample]
    stats: BuildStats


def build_samples(
    params: DatasetParams,
    places: Sequence[Place],
    excluded_keys: set[str],
    travel: TravelTimeProvider,
) -> BuildResult:
    stats = BuildStats()
    requests = generate_requests(params.max_requests, params.request_seed)
    stats.requests_generated = len(requests)
    kept = [request for request in requests if request_key(request) not in excluded_keys]
    stats.eval_collisions_removed = len(requests) - len(kept)

    samples: list[DatasetSample] = []
    repairs = 0
    for request in kept:
        if len(samples) >= params.target_samples:
            break
        stats.requests_used += 1
        key = request_key(request)
        candidates = select_candidates(
            request, places, derive_seed(params.request_seed, key, "candidates")
        )
        result = solve(
            request,
            candidates,
            travel,
            derive_seed(params.request_seed, key, "solver"),
            time_limit_s=params.solver_time_limit_s,
        )
        if result.itinerary is None:
            stats.solver_dropped[result.status.value] += 1
            continue
        sample: DatasetSample | None = None
        # Giữ tỉ lệ repair sát `repair_share` ở mọi điểm của file, không dồn về cuối.
        if repairs < round((len(samples) + 1) * params.repair_share):
            sample = _repair_sample(params, key, request, candidates, result.itinerary, travel)
            if sample is None:
                stats.repair_fallbacks += 1
            else:
                repairs += 1
        if sample is None:
            sample = _sample(key, SampleKind.GENERATE, request, candidates, result.itinerary)
        samples.append(sample)
    return BuildResult(samples, stats)


def _sample(
    key: str,
    kind: SampleKind,
    request: PlanRequest,
    candidates: Sequence[Place],
    answer: Itinerary,
    messages: list[dict[str, str]] | None = None,
    corruption: CorruptionKind | None = None,
    broken: str | None = None,
) -> DatasetSample:
    prompt = messages if messages is not None else build_messages(request, candidates)
    return DatasetSample(
        key=key,
        kind=kind,
        corruption=corruption,
        request=request,
        candidate_ids=[place.id for place in candidates],
        broken=broken,
        messages=[*prompt, {"role": "assistant", "content": format_itinerary(answer)}],
    )


def _repair_sample(
    params: DatasetParams,
    key: str,
    request: PlanRequest,
    candidates: Sequence[Place],
    itinerary: Itinerary,
    travel: TravelTimeProvider,
) -> DatasetSample | None:
    """Thử các kiểu phá theo thứ tự trộn theo seed; kiểu đầu tiên áp dụng được thắng."""
    seed = derive_seed(params.request_seed, key, "corruption")
    kinds = list(params.corruption_kinds)
    random.Random(seed).shuffle(kinds)
    for kind in kinds:
        corrupted = corrupt(request, itinerary, candidates, travel, kind, seed)
        if corrupted is None:
            continue
        messages = build_messages(
            request, candidates, broken=corrupted.itinerary, issues=corrupted.report.issues
        )
        return _sample(
            key,
            SampleKind.REPAIR,
            request,
            candidates,
            itinerary,
            messages=messages,
            corruption=kind,
            broken=format_itinerary(corrupted.itinerary),
        )
    return None


def write_samples(samples: Iterable[DatasetSample], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for sample in samples:
            handle.write(sample.model_dump_json() + "\n")


def build_manifest(
    params: DatasetParams,
    result: BuildResult,
    *,
    jsonl_sha256: str,
    db_sha256: str,
    evalset_sha256: str,
    git_commit: str,
) -> dict[str, Any]:
    """Các trường spec 10.2 yêu cầu, cộng số liệu để đọc nhanh. Không ghi giờ chạy, để manifest
    cũng tái lập được."""
    samples = result.samples
    stats = result.stats
    by_kind = Counter(sample.kind.value for sample in samples)
    by_corruption = Counter(sample.corruption.value for sample in samples if sample.corruption)
    used_places = {
        stop["place_id"]
        for sample in samples
        for day in json.loads(sample.messages[-1]["content"])["days"]
        for stop in day["stops"]
    }
    return {
        "name": params.name,
        "jsonl_sha256": jsonl_sha256,
        "db_sha256": db_sha256,
        "evalset_sha256": evalset_sha256,
        "git_commit": git_commit,
        "request_seed": params.request_seed,
        "params": params.model_dump(mode="json"),
        "samples": len(samples),
        "samples_by_kind": {kind.value: by_kind[kind.value] for kind in SampleKind},
        "repair_by_corruption": {kind.value: by_corruption[kind.value] for kind in CorruptionKind},
        "distribution": distribution(sample.request for sample in samples),
        "solver_dropped": dict(sorted(stats.solver_dropped.items())),
        "solver_dropped_total": sum(stats.solver_dropped.values()),
        "requests_generated": stats.requests_generated,
        "eval_collisions_removed": stats.eval_collisions_removed,
        "requests_used": stats.requests_used,
        "repair_fallbacks": stats.repair_fallbacks,
        "distinct_places": len(used_places),
    }
