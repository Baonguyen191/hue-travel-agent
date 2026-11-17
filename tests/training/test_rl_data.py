from pathlib import Path

from tests.planning.factories import make_place
from travel_agent.domain.models import Category
from travel_agent.training.dataset import DatasetSample, eval_keys
from travel_agent.training.requests import request_key
from travel_agent.training.rl_config import RlParams, load_rl_config
from travel_agent.training.rl_data import build_prompts, rl_requests
from travel_agent.training.runner import candidate_seed

REPO = Path(__file__).parents[2]
RL_YAML = REPO / "configs" / "rl.yaml"


def _params(**update: object) -> RlParams:
    params = load_rl_config(RL_YAML).rl
    return params.model_copy(update=update)


def _sft_request_keys() -> set[str]:
    lines = (REPO / "data" / "sft" / "hue_sft_v1.jsonl").read_text(encoding="utf-8").splitlines()
    return {request_key(DatasetSample.model_validate_json(line).request) for line in lines if line}


def test_rl_requests_avoid_the_eval_set_and_the_sft_dataset() -> None:
    params = _params(requests=200)
    requests = rl_requests(params)
    keys = {request_key(request) for request in requests}

    assert len(requests) == 200
    assert keys.isdisjoint(eval_keys(REPO / params.evalset))
    assert keys.isdisjoint(_sft_request_keys())


def test_rl_requests_are_unique_and_count_is_honoured() -> None:
    requests = rl_requests(_params(requests=150))
    keys = [request_key(request) for request in requests]

    assert len(requests) == 150
    assert len(set(keys)) == 150


def test_same_seed_gives_the_same_requests() -> None:
    first = rl_requests(_params(requests=100))
    second = rl_requests(_params(requests=100))

    assert [request_key(r) for r in first] == [request_key(r) for r in second]


def test_different_seed_gives_different_requests() -> None:
    first = rl_requests(_params(requests=50, seed=1))
    second = rl_requests(_params(requests=50, seed=2))

    assert [request_key(r) for r in first] != [request_key(r) for r in second]


def test_fewer_requests_are_a_prefix_of_more() -> None:
    small = rl_requests(_params(requests=30))
    large = rl_requests(_params(requests=60))

    assert large[:30] == small


def _places():
    return [
        make_place("t:museum", Category.MUSEUM),
        make_place("t:lunch", Category.RESTAURANT),
        make_place("t:dinner", Category.RESTAURANT),
        make_place("t:cafe", Category.CAFE),
        make_place("t:park", Category.PARK),
        make_place("t:temple", Category.RELIGIOUS),
        make_place("t:market", Category.MARKET),
        make_place("t:view", Category.VIEWPOINT),
        make_place("t:hist", Category.HISTORIC),
        make_place("t:attr", Category.ATTRACTION),
        make_place("t:shop", Category.MARKET),
        make_place("t:cafe2", Category.CAFE),
    ]


def test_build_prompts_uses_the_eval_candidate_seed_and_prompt_builder() -> None:
    from travel_agent.planning.candidates import select_candidates
    from travel_agent.planning.prompt import build_messages

    requests = rl_requests(_params(requests=5))
    prompts = build_prompts(requests, _places())

    assert [p.key for p in prompts] == [request_key(r) for r in requests]
    for prompt in prompts:
        expected = select_candidates(prompt.request, _places(), candidate_seed(prompt.key))
        assert [place.id for place in prompt.candidates] == [place.id for place in expected]
        assert prompt.messages == build_messages(prompt.request, expected)


def test_build_prompts_is_deterministic() -> None:
    requests = rl_requests(_params(requests=5))

    first = build_prompts(requests, _places())
    second = build_prompts(requests, _places())

    assert first == second
