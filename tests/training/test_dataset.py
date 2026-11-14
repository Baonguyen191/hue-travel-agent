import json
import re
from pathlib import Path
from typing import Any

import yaml

from tests.training.dataset_factories import PARAMS, TRAVEL, pool, small_build
from travel_agent.data.place_repository import InMemoryPlaceRepository
from travel_agent.domain.models import Category
from travel_agent.planning.candidates import select_candidates
from travel_agent.planning.prompt import build_messages, format_itinerary
from travel_agent.training.corrupt import CorruptionKind
from travel_agent.training.dataset import (
    DISTRIBUTION_VALUES,
    SampleKind,
    build_manifest,
    build_samples,
    derive_seed,
    eval_keys,
    load_config,
    write_samples,
)
from travel_agent.training.generator import itinerary_format_schema
from travel_agent.training.parsing import parse_itinerary
from travel_agent.training.requests import (
    EvalEntry,
    Split,
    generate_requests,
    request_key,
    write_eval_set,
)
from travel_agent.validation.validator import validate_itinerary

REPO = Path(__file__).parents[2]


def conforms(value: Any, schema: dict[str, Any]) -> bool:
    """Kiểm JSON theo đúng các từ khóa mà `itinerary_format_schema` dùng."""
    kinds = schema.get("type")
    kinds = kinds if isinstance(kinds, list) else [kinds]
    type_ok = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "null": value is None,
    }
    if not any(type_ok[kind] for kind in kinds):
        return False
    if isinstance(value, dict):
        if any(name not in value for name in schema.get("required", [])):
            return False
        props = schema.get("properties", {})
        return all(conforms(value[name], props[name]) for name in props if name in value)
    if isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", len(value)):
            return False
        return all(conforms(item, schema["items"]) for item in value)
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            return False
        return "pattern" not in schema or re.search(schema["pattern"], value) is not None
    return True


def test_build_reaches_target_with_repair_share() -> None:
    result = small_build()
    kinds = [sample.kind for sample in result.samples]
    assert len(kinds) == PARAMS.target_samples
    assert kinds.count(SampleKind.REPAIR) == round(PARAMS.target_samples * PARAMS.repair_share)


def test_answers_are_canonical_valid_and_schema_conformant() -> None:
    lookup_all = {place.id: place for place in pool()}
    for sample in small_build().samples:
        assert [m["role"] for m in sample.messages] == ["system", "user", "assistant"]
        answer_text = sample.messages[-1]["content"]
        answer = parse_itinerary(answer_text)
        assert answer is not None
        assert format_itinerary(answer) == answer_text
        data = json.loads(answer_text)
        assert conforms(data, itinerary_format_schema(sample.request.num_days))
        assert list(data["days"][0]["stops"][0]) == ["place_id", "arrive", "depart", "note"]
        candidates = [lookup_all[pid] for pid in sample.candidate_ids]
        report = validate_itinerary(
            sample.request, answer, InMemoryPlaceRepository(candidates), TRAVEL
        )
        assert report.is_valid


def test_generation_prompt_comes_from_build_messages() -> None:
    by_id = {place.id: place for place in pool()}
    for sample in small_build().samples:
        if sample.kind is SampleKind.GENERATE:
            candidates = [by_id[pid] for pid in sample.candidate_ids]
            assert sample.messages[:2] == build_messages(sample.request, candidates)
            assert sample.broken is None and sample.corruption is None


def test_repair_prompt_shows_a_broken_plan_and_answers_the_original() -> None:
    by_id = {place.id: place for place in pool()}
    repairs = [s for s in small_build().samples if s.kind is SampleKind.REPAIR]
    assert repairs
    for sample in repairs:
        assert sample.corruption is not None and sample.broken is not None
        broken = parse_itinerary(sample.broken)
        assert broken is not None
        candidates = [by_id[pid] for pid in sample.candidate_ids]
        report = validate_itinerary(
            sample.request, broken, InMemoryPlaceRepository(candidates), TRAVEL
        )
        assert not report.is_valid
        expected = build_messages(sample.request, candidates, broken=broken, issues=report.issues)
        assert sample.messages[:2] == expected
        assert sample.broken != sample.messages[-1]["content"]


def test_candidate_and_solver_seeds_are_derived_from_the_request() -> None:
    sample = small_build().samples[0]
    seed = derive_seed(PARAMS.request_seed, sample.key, "candidates")
    candidates = select_candidates(sample.request, pool(), seed)
    assert [place.id for place in candidates] == sample.candidate_ids
    assert derive_seed(1, "k", "solver") != derive_seed(1, "k", "candidates")


def test_same_config_rebuilds_the_same_bytes(tmp_path: Path) -> None:
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    write_samples(small_build().samples, first)
    write_samples(build_samples(PARAMS, list(pool()), set(), TRAVEL).samples, second)
    assert first.read_bytes() == second.read_bytes()


def test_eval_requests_are_excluded() -> None:
    stream = generate_requests(PARAMS.max_requests, PARAMS.request_seed)
    leaked = {request_key(request) for request in stream[:7]}
    result = build_samples(PARAMS, pool(), leaked, TRAVEL)
    assert result.stats.eval_collisions_removed == 7
    assert not leaked & {sample.key for sample in result.samples}
    assert len(result.samples) == PARAMS.target_samples


def test_eval_keys_cover_both_splits_and_are_recomputed(tmp_path: Path) -> None:
    requests = generate_requests(4, seed=5)
    entries = [
        EvalEntry(key="ghi-sai", split=Split.DEV if i % 2 else Split.TEST, request=request)
        for i, request in enumerate(requests)
    ]
    path = tmp_path / "eval.jsonl"
    write_eval_set(entries, path)
    assert eval_keys(path) == {request_key(request) for request in requests}


def test_solver_failures_are_dropped_and_counted() -> None:
    breakfast_only = [
        place.model_copy(update={"opening_hours_raw": "06:00-10:00"})
        if place.category is Category.RESTAURANT
        else place
        for place in pool()
    ]
    params = PARAMS.model_copy(update={"target_samples": 5, "max_requests": 5})
    result = build_samples(params, breakfast_only, set(), TRAVEL)
    assert result.samples == []
    assert result.stats.solver_dropped == {"infeasible": 5}


def test_repair_falls_back_to_generation_when_no_corruption_applies() -> None:
    params = PARAMS.model_copy(
        update={
            "target_samples": 6,
            "repair_share": 1.0,
            "corruption_kinds": [CorruptionKind.CLOSED],
        }
    )
    unknown_hours = [place.model_copy(update={"opening_hours_raw": None}) for place in pool()]
    result = build_samples(params, unknown_hours, set(), TRAVEL)
    assert {sample.kind for sample in result.samples} == {SampleKind.GENERATE}
    assert result.stats.repair_fallbacks == 6


def test_manifest_has_the_spec_fields() -> None:
    manifest = build_manifest(
        PARAMS,
        small_build(),
        jsonl_sha256="j",
        db_sha256="d",
        evalset_sha256="e",
        git_commit="c",
    )
    for field in ("jsonl_sha256", "db_sha256", "git_commit", "request_seed", "solver_dropped"):
        assert field in manifest
    assert manifest["samples_by_kind"]["repair"] + manifest["samples_by_kind"]["generate"] == 40
    assert set(manifest["distribution"]) == set(DISTRIBUTION_VALUES)
    assert sum(manifest["distribution"]["pace"].values()) == 40
    assert sum(manifest["repair_by_corruption"].values()) == manifest["samples_by_kind"]["repair"]
    assert set(manifest["repair_by_corruption"]) == {kind.value for kind in CorruptionKind}


def test_repo_config_loads_and_uses_a_seed_other_than_the_eval_seed() -> None:
    config = load_config(REPO / "configs" / "dataset.yaml")
    eval_config = yaml.safe_load((REPO / "configs" / "eval.yaml").read_text(encoding="utf-8"))
    assert config.dataset.request_seed != eval_config["evalset"]["seed"]
    assert config.check.max_tokens > 0
