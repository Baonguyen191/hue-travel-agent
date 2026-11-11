"""Canh file bộ eval đã commit. Vỡ nếu file bị sửa tay hoặc sinh lại sai."""

from pathlib import Path

from travel_agent.training.requests import (
    EVAL_SIZE,
    TEST_SIZE,
    Split,
    read_eval_set,
    request_key,
)

EVALSET = Path(__file__).parents[2] / "data" / "eval" / "hue_eval_v1.jsonl"


def test_committed_eval_set_is_intact() -> None:
    entries = read_eval_set(EVALSET)
    keys = [entry.key for entry in entries]
    assert len(entries) == EVAL_SIZE
    assert len(set(keys)) == EVAL_SIZE
    assert sum(1 for entry in entries if entry.split is Split.TEST) == TEST_SIZE
    assert all(entry.key == request_key(entry.request) for entry in entries)
