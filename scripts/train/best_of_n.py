"""Best-of-N cho RL (plan 5 Task 4): sinh N mẫu mỗi request qua Ollama, rồi chọn mẫu tốt nhất.

Lớp mỏng: logic chọn mẫu và dựng dataset nằm trong `travel_agent.training.best_of_n`. Không cần
torch, chạy bằng venv project; cần Ollama đang chạy và model đã pull.

    python scripts/train/best_of_n.py generate --config configs/rl.yaml --round 1 --model MODEL
    python scripts/train/best_of_n.py generate --config configs/rl.yaml --round 1 \
        --model M --limit 100
    python scripts/train/best_of_n.py select --config configs/rl.yaml --round 1

`generate` ghi từng mẫu vào `<run_dir>/round-K/samples.jsonl` ngay khi có, và bỏ qua mẫu đã có,
nên chạy tiếp được sau khi đứt. `select` đọc file đó, ghi `dataset.jsonl` (định dạng SFT) và
`stats.json` cùng thư mục.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from travel_agent.routing.travel_time import HaversineEstimator
from travel_agent.training.best_of_n import (
    ScoredSample,
    round_prompts,
    round_stats,
    sample_seed,
    select_best,
    to_dataset_sample,
)
from travel_agent.training.commands import (
    EXIT_DATASET_INVALID,
    EXIT_OK,
    EXIT_USAGE,
    load_usable_places,
)
from travel_agent.training.dataset import write_samples
from travel_agent.training.generator import (
    DEFAULT_HOST,
    OllamaGenerator,
    PlanGenerator,
    itinerary_format_schema,
)
from travel_agent.training.reward import score_reward
from travel_agent.training.rl_config import RlConfig, load_rl_config
from travel_agent.training.rl_data import RlPrompt, build_prompts, rl_requests

SAMPLES_FILE = "samples.jsonl"
DATASET_FILE = "dataset.jsonl"
STATS_FILE = "stats.json"

# Dựng generator cho từng mẫu: (model, host, temperature, seed). Test thay bằng bản giả.
GeneratorFactory = Callable[..., PlanGenerator]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate", help="Sinh N mẫu mỗi request của vòng")
    generate.add_argument("--config", type=Path, default=Path("configs/rl.yaml"))
    generate.add_argument("--round", type=int, required=True, help="Số vòng, đánh số từ 1")
    generate.add_argument("--model", required=True, help="Tên model trong Ollama")
    generate.add_argument("--host", default=DEFAULT_HOST)
    generate.add_argument(
        "--limit", type=int, default=None, help="Chỉ N request đầu của vòng (vòng thử)"
    )

    select = sub.add_parser("select", help="Giữ mẫu tốt nhất mỗi request và ghi dataset")
    select.add_argument("--config", type=Path, default=Path("configs/rl.yaml"))
    select.add_argument("--round", type=int, required=True, help="Số vòng, đánh số từ 1")
    return parser.parse_args(argv)


def round_dir(config: RlConfig, round_index: int) -> Path:
    return config.rl.run_dir / f"round-{round_index}"


def round_run_prompts(config: RlConfig, round_index: int) -> list[RlPrompt]:
    """Prompt của vòng K. Dựng lại đúng cùng cách ở mọi lần chạy (config, DB, seed cố định)."""
    rl = config.rl
    prompts = build_prompts(rl_requests(rl), load_usable_places(rl.db))
    return round_prompts(prompts, round_index, config.best_of_n.requests_per_round)


def read_samples(path: Path) -> tuple[list[ScoredSample], int]:
    """Đọc các mẫu đã ghi. Trả thêm số dòng hỏng: dòng dở dang do đứt giữa chừng bị bỏ qua."""
    samples: list[ScoredSample] = []
    broken = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            samples.append(ScoredSample.model_validate_json(line))
        except ValidationError:
            broken += 1
    return samples, broken


def _repair_tail(path: Path) -> None:
    """Nếu file kết thúc giữa dòng (đứt khi ghi), thêm xuống dòng để dòng mới không dính vào."""
    if not path.is_file() or path.stat().st_size == 0:
        return
    with path.open("rb") as handle:
        handle.seek(-1, os.SEEK_END)
        last = handle.read(1)
    if last != b"\n":
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n")


def run_generate(args: argparse.Namespace, make_generator: GeneratorFactory) -> int:
    config = load_rl_config(args.config)
    best = config.best_of_n
    prompts = round_run_prompts(config, args.round)
    if args.limit is not None:
        prompts = prompts[: args.limit]

    out_dir = round_dir(config, args.round)
    out_dir.mkdir(parents=True, exist_ok=True)
    samples_path = out_dir / SAMPLES_FILE
    done: set[tuple[str, int]] = set()
    if samples_path.is_file():
        done = {(sample.key, sample.index) for sample in read_samples(samples_path)[0]}
    _repair_tail(samples_path)

    travel = HaversineEstimator()
    written = 0
    # Mở ở chế độ nối và ghi từng dòng: lỗi giữa chừng (Ollama chết, hết RAM) không làm mất phần
    # đã sinh.
    with samples_path.open("a", encoding="utf-8", newline="\n") as handle:
        for prompt in prompts:
            schema = itinerary_format_schema(prompt.request.num_days)
            for index in range(best.samples):
                if (prompt.key, index) in done:
                    continue
                seed = sample_seed(config.rl.seed, prompt.key, args.round, index)
                generator = make_generator(
                    args.model, host=args.host, temperature=best.temperature, seed=seed
                )
                started = time.perf_counter()
                generation = generator.generate(prompt.messages, format_schema=schema)
                latency_s = time.perf_counter() - started
                reward = score_reward(prompt.request, generation.content, prompt.candidates, travel)
                scored = ScoredSample(
                    key=prompt.key,
                    index=index,
                    seed=seed,
                    raw=generation.content,
                    reward=reward,
                    latency_s=latency_s,
                )
                handle.write(scored.model_dump_json() + "\n")
                handle.flush()
                written += 1

    total = len(prompts) * best.samples
    print(
        f"round {args.round}: {written} mẫu mới, {total - written} đã có hoặc bỏ qua, "
        f"tổng {total} mẫu -> {samples_path}"
    )
    return EXIT_OK


def run_select(args: argparse.Namespace) -> int:
    config = load_rl_config(args.config)
    threshold = config.best_of_n.threshold
    out_dir = round_dir(config, args.round)
    samples_path = out_dir / SAMPLES_FILE
    if not samples_path.is_file():
        print(f"Không tìm thấy {samples_path}. Chạy generate trước.", file=sys.stderr)
        return EXIT_USAGE

    samples, broken = read_samples(samples_path)
    if broken:
        print(f"Bỏ qua {broken} dòng hỏng trong {samples_path}.", file=sys.stderr)
    groups: dict[str, list[ScoredSample]] = {}
    for sample in samples:
        groups.setdefault(sample.key, []).append(sample)

    prompts = {prompt.key: prompt for prompt in round_run_prompts(config, args.round)}
    unknown = [key for key in groups if key not in prompts]
    if unknown:
        print(
            f"{len(unknown)} request trong {samples_path} không thuộc vòng {args.round}.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    kept = []
    for key, group in groups.items():
        best = select_best(group, threshold)
        if best is not None:
            kept.append(to_dataset_sample(prompts[key], best.raw))

    stats = round_stats(groups, threshold)
    write_samples(kept, out_dir / DATASET_FILE)
    (out_dir / STATS_FILE).write_text(stats.model_dump_json(indent=2) + "\n", encoding="utf-8")

    print(f"round {args.round}: giữ {stats.kept}/{stats.requests} request (ngưỡng {threshold:g})")
    print(f"  mean_best_reward: {stats.mean_best_reward:.3f}")
    print(f"  mean_reward:      {stats.mean_reward:.3f}")
    print(f"  parse_failures:   {stats.parse_failures}/{stats.samples}")
    print(f"  valid_samples:    {stats.valid_samples}/{stats.samples}")
    print(f"  dataset: {out_dir / DATASET_FILE}")
    if not kept:
        print("Không request nào đạt ngưỡng: dataset rỗng.", file=sys.stderr)
        return EXIT_DATASET_INVALID
    return EXIT_OK


def main(
    argv: list[str] | None = None,
    make_generator: GeneratorFactory = OllamaGenerator,
) -> int:
    args = parse_args(argv)
    if args.round < 1:
        print("--round phải từ 1 trở lên.", file=sys.stderr)
        return EXIT_USAGE
    if args.command == "generate":
        return run_generate(args, make_generator)
    return run_select(args)


if __name__ == "__main__":
    sys.exit(main())
