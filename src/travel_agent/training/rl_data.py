"""Request và prompt cho RL. Logic thuần, xác định: cùng config, cùng DB thì cùng danh sách.

Request train RL không được trùng bộ eval (dev lẫn test) hay dataset SFT, nên điểm RL không bị
thổi phồng bởi các request model đã học. Candidate chọn bằng `candidate_seed(key)`, như lúc eval
và lúc đo reward, nên một request có cùng candidate ở mọi nơi.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from travel_agent.domain.models import Place, PlanRequest
from travel_agent.planning.candidates import select_candidates
from travel_agent.planning.prompt import build_messages
from travel_agent.training.dataset import DatasetSample, eval_keys
from travel_agent.training.requests import generate_requests, request_key
from travel_agent.training.rl_config import RlParams
from travel_agent.training.runner import candidate_seed


@dataclass(frozen=True)
class RlPrompt:
    key: str
    request: PlanRequest
    candidates: list[Place]
    messages: list[dict[str, str]]  # chưa render; render bằng ChatTokenizer lúc train


def sft_keys(path: Path) -> set[str]:
    """Key của request trong dataset SFT. Tính lại từ `request`, không tin trường `key`."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return {
        request_key(DatasetSample.model_validate_json(line).request)
        for line in lines
        if line.strip()
    }


def rl_requests(params: RlParams) -> list[PlanRequest]:
    """`params.requests` request khác nhau, không trùng eval hay SFT, theo `params.seed`.

    Sinh dư bằng số key cần loại: mọi key bị loại đều nằm trong số dư đó, nên vẫn đủ request.
    `generate_requests` cho cùng thứ tự đầu với mọi `count`, nên kết quả không đổi theo số dư.
    """
    excluded = eval_keys(params.evalset) | sft_keys(params.sft_dataset)
    pool = generate_requests(params.requests + len(excluded), params.seed)
    kept = [request for request in pool if request_key(request) not in excluded]
    if len(kept) < params.requests:  # không xảy ra với `generate_requests` đủ dư; chặn để chắc
        raise ValueError(f"chỉ còn {len(kept)} request sau khi loại trùng, cần {params.requests}")
    return kept[: params.requests]


def build_prompts(requests: Sequence[PlanRequest], places: Sequence[Place]) -> list[RlPrompt]:
    prompts: list[RlPrompt] = []
    for request in requests:
        key = request_key(request)
        candidates = select_candidates(request, places, candidate_seed(key))
        prompts.append(
            RlPrompt(
                key=key,
                request=request,
                candidates=candidates,
                messages=build_messages(request, candidates),
            )
        )
    return prompts
