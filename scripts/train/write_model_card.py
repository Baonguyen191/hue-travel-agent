"""Ghi model card của run SFT hoặc RL từ số liệu đã có. Không cần torch.

    python scripts/train/write_model_card.py --config configs/sft.yaml
    python scripts/train/write_model_card.py --stage rl --rl-config configs/rl.yaml

Stage SFT ghi `models/sft/<run_name>/model_card.json`. Đọc `data/sft/manifest.json`,
`train_metrics.json` và `export.json` của run, kết quả eval dev (`reports/eval/sft_dev.json`) và,
nếu có, `checkpoints.json` (first_pass_valid_rate dev của từng checkpoint đã thử). File nào chưa có
thì mục tương ứng ghi null.

Stage RL ghi `models/rl/<run_name>/model_card.json`. Đọc dataset của vòng đã chọn (`final.dataset`
và `final.stats`), adapter SFT khởi đầu (`parent`), `models/rl/<run_name>/export.json` và eval dev
(`reports/eval/rl_dev.json`). Base model lấy từ config SFT mà `rl.sft_config` trỏ tới.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from travel_agent.training.gitinfo import current_commit
from travel_agent.training.model_card import (
    build_model_card,
    build_rl_model_card,
    sha256_file,
    write_model_card,
)
from travel_agent.training.rl_config import load_rl_config, repo_rl_artifacts_dir
from travel_agent.training.sft_config import load_sft_config, repo_artifacts_dir
from travel_agent.training.tokens import hf_snapshot_dir

TRAIN_KEYS = (
    "optimizer_steps",
    "train_loss",
    "train_seconds",
    "seconds_per_step",
    "peak_vram_allocated_gb",
    "peak_vram_reserved_gb",
    "gpu",
    "python",
    "packages",
    "trained_tokens",
)
ADAPTER_WEIGHTS = "adapter_model.safetensors"
DEFAULT_SFT_REPORT = Path("reports/eval/sft_dev.json")
DEFAULT_RL_REPORT = Path("reports/eval/rl_dev.json")


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", choices=("sft", "rl"), default="sft")
    parser.add_argument("--config", type=Path, default=Path("configs/sft.yaml"))
    parser.add_argument("--rl-config", type=Path, default=Path("configs/rl.yaml"))
    parser.add_argument("--manifest", type=Path, default=Path("data/sft/manifest.json"))
    parser.add_argument(
        "--eval-report",
        type=Path,
        default=None,
        help="Mặc định reports/eval/sft_dev.json (sft) hoặc reports/eval/rl_dev.json (rl)",
    )
    args = parser.parse_args(argv)
    if args.stage == "rl":
        return rl_card(args.rl_config, args.eval_report or DEFAULT_RL_REPORT)

    config = load_sft_config(args.config)
    artifacts = repo_artifacts_dir(config.sft.run_name)
    card_path = artifacts / "model_card.json"
    manifest = read_json(args.manifest)
    if manifest is None:
        raise SystemExit(f"Không đọc được {args.manifest}.")
    train = read_json(artifacts / "train_metrics.json")
    export = read_json(artifacts / "export.json")
    report = read_json(args.eval_report or DEFAULT_SFT_REPORT)
    checkpoints = read_json(artifacts / "checkpoints.json")
    chosen = {"step": export["checkpoint"]} if export else None
    if chosen is not None and checkpoints is not None:
        chosen["dev_first_pass_valid_rate_by_step"] = checkpoints
    card = build_model_card(
        config=config,
        config_path=args.config,
        snapshot_dir=hf_snapshot_dir(config.sft.base_model.repo, config.sft.base_model.revision),
        manifest=manifest,
        git_commit=current_commit([card_path]),
        train={key: train.get(key) for key in TRAIN_KEYS} if train else None,
        checkpoint=chosen,
        export=export,
        metrics_dev=report,
    )
    write_model_card(card, card_path)
    print(f"Đã ghi {card_path}.")
    return 0


def step_of(adapter: Path) -> int:
    """Step của adapter SFT, từ tên thư mục `step-<N>`."""
    match = re.fullmatch(r"step-(\d+)", adapter.name)
    if match is None:
        raise SystemExit(f"Tên adapter {adapter} phải có dạng step-<N>.")
    return int(match.group(1))


def count_samples(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def rl_card(rl_config_path: Path, eval_report: Path) -> int:
    rl = load_rl_config(rl_config_path)
    sft_config = load_sft_config(rl.rl.sft_config)
    artifacts = repo_rl_artifacts_dir(rl.rl.run_name)
    card_path = artifacts / "model_card.json"
    init = rl.rl.init_adapter

    dataset_path, stats = rl.final.dataset, read_json(rl.final.stats)
    if not dataset_path.is_file():
        raise SystemExit(f"Không có dataset RL {dataset_path}.")
    if stats is None:
        raise SystemExit(f"Không đọc được {rl.final.stats}.")
    parent = {
        "run_name": sft_config.sft.run_name,
        "checkpoint": step_of(init),
        "adapter_sha256": sha256_file(init / ADAPTER_WEIGHTS),
    }
    dataset = {
        "path": dataset_path.as_posix(),
        "name": dataset_path.stem,
        "jsonl_sha256": sha256_file(dataset_path),
        "samples": count_samples(dataset_path),
        "stats": stats,
    }
    adapter = artifacts / "adapter"
    checkpoint = (
        {"adapter": adapter.as_posix(), "adapter_sha256": sha256_file(adapter / ADAPTER_WEIGHTS)}
        if (adapter / ADAPTER_WEIGHTS).is_file()
        else None
    )
    card = build_rl_model_card(
        rl=rl,
        config_path=rl_config_path,
        sft_config=sft_config,
        snapshot_dir=hf_snapshot_dir(
            sft_config.sft.base_model.repo, sft_config.sft.base_model.revision
        ),
        git_commit=current_commit([card_path]),
        parent=parent,
        dataset=dataset,
        checkpoint=checkpoint,
        export=read_json(artifacts / "export.json"),
        metrics_dev=read_json(eval_report),
    )
    write_model_card(card, card_path)
    print(f"Đã ghi {card_path}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
