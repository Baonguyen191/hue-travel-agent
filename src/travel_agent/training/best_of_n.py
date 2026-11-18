"""Best-of-N cho RL (plan 5 Task 4): chọn mẫu, dựng dataset SFT, thống kê vòng. Logic thuần.

Mỗi request sinh `samples` mẫu, chấm bằng `score_reward`; mẫu reward cao nhất được giữ nếu đạt
ngưỡng. Hàm trong file này không gọi mạng: việc gọi model nằm ở `scripts/train/best_of_n.py`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel

from travel_agent.planning.prompt import format_itinerary
from travel_agent.training.dataset import DatasetSample, SampleKind, derive_seed
from travel_agent.training.parsing import parse_itinerary
from travel_agent.training.reward import RewardBreakdown
from travel_agent.training.rl_data import RlPrompt


class ScoredSample(BaseModel):
    """Một mẫu model sinh cho một request, kèm điểm. Mỗi dòng `samples.jsonl` là một mẫu."""

    key: str
    index: int  # số thứ tự mẫu trong request, từ 0; dùng để phá hòa
    seed: int
    raw: str  # output thô của model, chưa chuẩn hóa
    reward: RewardBreakdown
    latency_s: float


class RoundStats(BaseModel):
    requests: int
    samples: int
    kept: int
    keep_rate: float
    mean_reward: float  # trung bình reward của mọi mẫu
    mean_best_reward: float  # trung bình reward cao nhất của mỗi request có mẫu
    parse_failures: int
    valid_samples: int
    issue_totals: dict[str, float]  # tổng phạt theo khóa, mọi mẫu cộng lại (số âm)
    mean_latency_s: float


def sample_seed(base_seed: int, key: str, round_index: int, index: int) -> int:
    """Seed riêng cho (request, vòng, số mẫu): cùng đầu vào thì cùng seed, khác mẫu thì khác."""
    return derive_seed(base_seed, key, f"best_of_n:{round_index}:{index}")


def round_prompts(prompts: Sequence[RlPrompt], round_index: int, per_round: int) -> list[RlPrompt]:
    """Vòng K (đánh số từ 1) lấy `per_round` prompt liên tiếp, không chồng với vòng khác."""
    if round_index < 1:
        raise ValueError("số vòng phải từ 1 trở lên")
    if per_round < 1:
        raise ValueError("số request mỗi vòng phải lớn hơn 0")
    start = (round_index - 1) * per_round
    end = start + per_round
    if end > len(prompts):
        raise ValueError(
            f"vòng {round_index} cần prompt {start + 1} đến {end}, "
            f"nhưng chỉ có {len(prompts)} prompt"
        )
    return list(prompts[start:end])


def select_best(samples: Sequence[ScoredSample], threshold: float) -> ScoredSample | None:
    """Mẫu reward cao nhất; hòa thì lấy mẫu có số thứ tự nhỏ hơn. Dưới ngưỡng thì trả None."""
    best: ScoredSample | None = None
    for sample in samples:
        if best is None or sample.reward.total > best.reward.total:
            best = sample
        elif sample.reward.total == best.reward.total and sample.index < best.index:
            best = sample
    if best is None or best.reward.total < threshold:
        return None
    return best


def to_dataset_sample(prompt: RlPrompt, raw: str) -> DatasetSample:
    """Đổi mẫu thắng thành dòng dataset SFT. Đáp án được chuẩn hóa như đáp án của solver.

    Output không parse được thì raise: mẫu như vậy không bao giờ đạt ngưỡng, nên không được vào
    dataset.
    """
    itinerary = parse_itinerary(raw)
    if itinerary is None:
        raise ValueError(f"output của request {prompt.key} không parse được thành Itinerary")
    return DatasetSample(
        key=prompt.key,
        kind=SampleKind.GENERATE,
        request=prompt.request,
        candidate_ids=[place.id for place in prompt.candidates],
        messages=[
            *prompt.messages,
            {"role": "assistant", "content": format_itinerary(itinerary)},
        ],
    )


def round_stats(groups: Mapping[str, Sequence[ScoredSample]], threshold: float) -> RoundStats:
    """Thống kê một vòng. `requests` là số key có trong `groups`; key không có mẫu nào thì không
    đóng góp vào trung bình reward cao nhất, nhưng vẫn được đếm trong `requests`."""
    all_samples = [sample for group in groups.values() for sample in group]
    best_rewards = [
        max(sample.reward.total for sample in group) for group in groups.values() if group
    ]
    kept = sum(1 for group in groups.values() if select_best(group, threshold) is not None)
    issue_totals: dict[str, float] = {}
    for sample in all_samples:
        for key, amount in sample.reward.penalties.items():
            issue_totals[key] = round(issue_totals.get(key, 0.0) + amount, 6)

    requests = len(groups)
    return RoundStats(
        requests=requests,
        samples=len(all_samples),
        kept=kept,
        keep_rate=kept / requests if requests else 0.0,
        mean_reward=_mean([sample.reward.total for sample in all_samples]),
        mean_best_reward=_mean(best_rewards),
        parse_failures=sum(1 for sample in all_samples if not sample.reward.parsed),
        valid_samples=sum(1 for sample in all_samples if sample.reward.valid),
        issue_totals=dict(sorted(issue_totals.items())),
        mean_latency_s=_mean([sample.latency_s for sample in all_samples]),
    )


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0
