from tests.training.factories import PLACES, REQUEST, VALID_RAW
from tests.validation.factories import FixedTravelTime
from travel_agent.training.requests import EvalEntry, Split, request_key
from travel_agent.training.runner import candidate_seed, run_eval


class FakeGenerator:
    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.seen: list[list[dict[str, str]]] = []

    def generate(self, messages: list[dict[str, str]]) -> str:
        self.seen.append(messages)
        return self.raw


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1.5
        return self.now


ENTRY = EvalEntry(key=request_key(REQUEST), split=Split.DEV, request=REQUEST)


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
