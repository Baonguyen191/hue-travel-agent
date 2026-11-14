"""`model_card.json` của một run (spec mục 10.5). Hàm thuần; script train và export điền số liệu.

Card ghi đủ để dựng lại model: base model và revision, hash dataset, config, số đo train, checkpoint
được chọn, cách export và metric dev. RL sẽ ghi `parent` là run SFT mà nó train tiếp.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from travel_agent.training.chat import CHAT_TEMPLATE_FILE, TOKENIZER_FILE
from travel_agent.training.sft_config import SftConfig

CARD_VERSION = 1
REQUIRED_SECTIONS = (
    "run_name",
    "stage",
    "parent",
    "git_commit",
    "base_model",
    "dataset",
    "config",
    "train",
    "checkpoint",
    "export",
    "metrics_dev",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build_model_card(
    *,
    config: SftConfig,
    config_path: Path,
    snapshot_dir: Path,
    manifest: Mapping[str, Any],
    git_commit: str,
    train: Mapping[str, Any] | None = None,
    checkpoint: Mapping[str, Any] | None = None,
    export: Mapping[str, Any] | None = None,
    metrics_dev: Mapping[str, Any] | None = None,
    stage: str = "sft",
    parent: str | None = None,
) -> dict[str, Any]:
    """Card đủ các mục ở spec 10.5. Mục chưa có số liệu ghi `null`, không bỏ khóa."""
    base = config.sft.base_model
    return {
        "card_version": CARD_VERSION,
        "run_name": config.sft.run_name,
        "stage": stage,
        "parent": parent,
        "git_commit": git_commit,
        "base_model": {
            "repo": base.repo,
            "revision": base.revision,
            "license": base.license,
            "license_source": base.license_source,
            "tokenizer_sha256": sha256_file(snapshot_dir / TOKENIZER_FILE),
            "chat_template_sha256": sha256_file(snapshot_dir / CHAT_TEMPLATE_FILE),
        },
        "dataset": {
            "path": config.sft.dataset.as_posix(),
            "name": manifest.get("name"),
            "jsonl_sha256": manifest.get("jsonl_sha256"),
            "db_sha256": manifest.get("db_sha256"),
            "samples": manifest.get("samples"),
            "samples_by_kind": manifest.get("samples_by_kind"),
            "git_commit": manifest.get("git_commit"),
        },
        "config": {
            "path": config_path.as_posix(),
            "sha256": sha256_file(config_path),
            "values": config.model_dump(mode="json"),
        },
        "train": dict(train) if train is not None else None,
        "checkpoint": dict(checkpoint) if checkpoint is not None else None,
        "export": dict(export) if export is not None else None,
        "metrics_dev": dict(metrics_dev) if metrics_dev is not None else None,
    }


def write_model_card(card: Mapping[str, Any], path: Path) -> None:
    missing = [section for section in REQUIRED_SECTIONS if section not in card]
    if missing:
        raise ValueError(f"model card thiếu mục: {', '.join(missing)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(card, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
