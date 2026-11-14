from pathlib import Path

import pytest

from tests.planning.factories import make_request
from travel_agent.domain.models import Pace
from travel_agent.planning.candidates import INTEREST_CATEGORIES
from travel_agent.training.requests import (
    EVAL_SIZE,
    TEST_SIZE,
    Split,
    build_eval_set,
    generate_requests,
    read_eval_set,
    request_key,
    write_eval_set,
)


def test_key_is_stable_and_sensitive_to_fields() -> None:
    assert request_key(make_request()) == request_key(make_request())
    assert request_key(make_request()) != request_key(make_request(pace=Pace.PACKED))
    assert len(request_key(make_request())) == 16


def test_generates_unique_requests() -> None:
    requests = generate_requests(200, seed=1)
    assert len(requests) == 200
    assert len({request_key(request) for request in requests}) == 200


def test_generation_is_deterministic() -> None:
    first = [request_key(request) for request in generate_requests(50, seed=9)]
    second = [request_key(request) for request in generate_requests(50, seed=9)]
    assert first == second


def test_requests_stay_inside_eval_space() -> None:
    for request in generate_requests(200, seed=2):
        assert 1 <= request.num_days <= 3
        assert 1 <= len(request.interests) <= 3
        assert set(request.interests) <= set(INTEREST_CATEGORIES)
        assert request.interests == sorted(request.interests)


def test_eval_set_split_sizes_and_no_overlap() -> None:
    entries = build_eval_set(seed=3)
    dev = {entry.key for entry in entries if entry.split is Split.DEV}
    test = {entry.key for entry in entries if entry.split is Split.TEST}
    assert len(entries) == EVAL_SIZE
    assert len(test) == TEST_SIZE
    assert len(dev) == EVAL_SIZE - TEST_SIZE
    assert not dev & test


def test_entry_key_matches_its_request() -> None:
    for entry in build_eval_set(seed=3):
        assert entry.key == request_key(entry.request)


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    entries = build_eval_set(seed=3)
    path = tmp_path / "eval" / "set.jsonl"
    write_eval_set(entries, path)
    assert read_eval_set(path) == entries
    assert len(read_eval_set(path, Split.TEST)) == TEST_SIZE


def test_generate_requests_refuses_impossible_count() -> None:
    with pytest.raises(ValueError, match="không đủ request khác nhau"):
        generate_requests(10**9, seed=1, max_attempts=1000)
