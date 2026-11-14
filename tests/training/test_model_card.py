import json
from pathlib import Path

import pytest

from travel_agent.training.chat import CHAT_TEMPLATE_FILE, TOKENIZER_FILE
from travel_agent.training.model_card import (
    REQUIRED_SECTIONS,
    build_model_card,
    sha256_file,
    write_model_card,
)
from travel_agent.training.sft_config import load_sft_config

REPO = Path(__file__).parents[2]
SFT_YAML = REPO / "configs" / "sft.yaml"
MANIFEST = {
    "name": "hue_sft_v1",
    "jsonl_sha256": "j",
    "db_sha256": "d",
    "samples": 4000,
    "samples_by_kind": {"generate": 3400, "repair": 600},
    "git_commit": "c",
}


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    (tmp_path / TOKENIZER_FILE).write_text("{}", encoding="utf-8")
    (tmp_path / CHAT_TEMPLATE_FILE).write_text("{{ messages }}", encoding="utf-8")
    return tmp_path


def card(snapshot: Path, **extra: object) -> dict[str, object]:
    return build_model_card(
        config=load_sft_config(SFT_YAML),
        config_path=SFT_YAML,
        snapshot_dir=snapshot,
        manifest=MANIFEST,
        git_commit="abc",
        **extra,  # type: ignore[arg-type]
    )


def test_card_has_every_spec_section(snapshot: Path) -> None:
    built = card(snapshot)
    assert set(REQUIRED_SECTIONS) <= set(built)
    assert built["stage"] == "sft" and built["parent"] is None
    base = built["base_model"]
    assert isinstance(base, dict)
    assert base["repo"] == "Qwen/Qwen3.5-4B"
    assert base["tokenizer_sha256"] == sha256_file(snapshot / TOKENIZER_FILE)
    dataset = built["dataset"]
    assert isinstance(dataset, dict) and dataset["jsonl_sha256"] == "j"
    config = built["config"]
    assert isinstance(config, dict) and config["sha256"] == sha256_file(SFT_YAML)


def test_sections_without_numbers_are_null_not_missing(snapshot: Path) -> None:
    built = card(snapshot, train={"steps": 20})
    assert built["train"] == {"steps": 20}
    assert built["metrics_dev"] is None and built["export"] is None


def test_write_refuses_an_incomplete_card(tmp_path: Path, snapshot: Path) -> None:
    built = card(snapshot)
    path = tmp_path / "out" / "model_card.json"
    write_model_card(built, path)
    assert json.loads(path.read_text(encoding="utf-8"))["run_name"] == "sft-v1"
    del built["metrics_dev"]
    with pytest.raises(ValueError):
        write_model_card(built, path)
