"""Ghi `models/sft/<run_name>/model_card.json` từ số liệu đã có. Không cần torch.

    python scripts/train/write_model_card.py --config configs/sft.yaml

Đọc `data/sft/manifest.json`, `train_metrics.json` và `export.json` của run, kết quả eval dev
(`reports/eval/sft_dev.json`) và, nếu có, `checkpoints.json` (first_pass_valid_rate dev của từng
checkpoint đã thử). File nào chưa có thì mục tương ứng ghi null.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from travel_agent.training.commands import current_commit
from travel_agent.training.model_card import build_model_card, write_model_card
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


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("configs/sft.yaml"))
    parser.add_argument("--manifest", type=Path, default=Path("data/sft/manifest.json"))
    parser.add_argument("--eval-report", type=Path, default=Path("reports/eval/sft_dev.json"))
    args = parser.parse_args(argv)

    config = load_sft_config(args.config)
    artifacts = repo_artifacts_dir(config.sft.run_name)
    card_path = artifacts / "model_card.json"
    manifest = read_json(args.manifest)
    if manifest is None:
        raise SystemExit(f"Không đọc được {args.manifest}.")
    train = read_json(artifacts / "train_metrics.json")
    export = read_json(artifacts / "export.json")
    report = read_json(args.eval_report)
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


if __name__ == "__main__":
    sys.exit(main())
