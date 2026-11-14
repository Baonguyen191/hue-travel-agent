from typing import Any

import pytest

from tests.training.factories import PLACES, REQUEST, VALID_RAW
from tests.validation.factories import FixedTravelTime
from travel_agent.training.generator import Generation, GenerationError
from travel_agent.training.metrics import PlanOutcome
from travel_agent.training.requests import EvalEntry, Split, request_key
from travel_agent.training.runner import candidate_seed, run_eval


class FakeGenerator:
    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.seen: list[list[dict[str, str]]] = []
        self.schemas: list[dict[str, Any] | None] = []

    def generate(
        self, messages: list[dict[str, str]], format_schema: dict[str, Any] | None = None
    ) -> Generation:
        self.seen.append(messages)
        self.schemas.append(format_schema)
        return Generation(
            content=self.raw, done_reason="stop", prompt_tokens=120, completion_tokens=80
        )


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1.5
        return self.now


ENTRY = EvalEntry(key=request_key(REQUEST), split=Split.DEV, request=REQUEST)


def test_each_request_gets_a_schema_pinned_to_its_day_count() -> None:
    two_days = REQUEST.model_copy(update={"num_days": 2})
    entry = EvalEntry(key=request_key(two_days), split=Split.DEV, request=two_days)
    generator = FakeGenerator(VALID_RAW)
    run_eval([entry], PLACES, generator, FixedTravelTime(), clock=FakeClock())
    [schema] = generator.schemas
    assert schema is not None
    days = schema["properties"]["days"]
    assert (days["minItems"], days["maxItems"]) == (2, 2)


def test_candidate_seed_is_stable_per_key() -> None:
    assert candidate_seed("00000010abcdef12") == 16
    assert candidate_seed(ENTRY.key) == candidate_seed(ENTRY.key)


def test_runs_each_entry_and_scores_it() -> None:
    generator = FakeGenerator(VALID_RAW)
    [outcome] = run_eval([ENTRY], PLACES, generator, FixedTravelTime(), clock=FakeClock())
    assert outcome.key == ENTRY.key
    assert outcome.valid
    assert outcome.latency_s == 1.5
    [messages] = generator.seen
    assert [message["role"] for message in messages] == ["system", "user"]
    assert "t:museum" in messages[1]["content"]


def test_bad_output_is_counted_not_raised() -> None:
    [outcome] = run_eval([ENTRY], PLACES, FakeGenerator("hỏng"), FixedTravelTime())
    assert not outcome.parsed


def test_outcome_keeps_raw_and_generation_metadata() -> None:
    [outcome] = run_eval([ENTRY], PLACES, FakeGenerator(VALID_RAW), FixedTravelTime())
    assert outcome.raw == VALID_RAW
    assert outcome.stops_per_day == [3]
    assert (outcome.done_reason, outcome.prompt_tokens, outcome.completion_tokens) == (
        "stop",
        120,
        80,
    )


def test_on_outcome_is_called_after_each_request_in_order() -> None:
    seen: list[PlanOutcome] = []
    outcomes = run_eval(
        [ENTRY, ENTRY], PLACES, FakeGenerator(VALID_RAW), FixedTravelTime(), on_outcome=seen.append
    )
    assert seen == outcomes
    assert len(seen) == 2


def test_outcomes_before_a_generation_error_were_already_reported() -> None:
    class FailsOnThird(FakeGenerator):
        def generate(
            self, messages: list[dict[str, str]], format_schema: dict[str, Any] | None = None
        ) -> Generation:
            if len(self.seen) == 2:
                raise GenerationError("Ollama chết")
            return super().generate(messages, format_schema)

    seen: list[PlanOutcome] = []
    with pytest.raises(GenerationError):
        run_eval(
            [ENTRY] * 4,
            PLACES,
            FailsOnThird(VALID_RAW),
            FixedTravelTime(),
            on_outcome=seen.append,
        )
    assert len(seen) == 2
