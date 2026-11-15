"""Test scripts/train/check_export.py: token prompt và kiểm JSON, không gọi Ollama.

`load_entries_and_places`, `load_counter`, `make_generator` được thay bằng bản giả.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from scripts.train import check_export
from tests.training.factories import PLACES, REQUEST, VALID_RAW
from travel_agent.training.generator import Generation, itinerary_format_schema
from travel_agent.training.requests import EvalEntry, Split, request_key

REPO = Path(__file__).parents[2]
SFT_YAML = REPO / "configs" / "sft.yaml"
EVAL_YAML = REPO / "configs" / "eval.yaml"

REQUESTS = [
    REQUEST.model_copy(
        update={
            "num_days": 1 + index % 3,
            "start_date": REQUEST.start_date + dt.timedelta(days=index),
        }
    )
    for index in range(4)
]
ENTRIES = [EvalEntry(key=request_key(req), split=Split.DEV, request=req) for req in REQUESTS]
PROMPT_TOKENS = 100


def fixed_counter(messages: Sequence[Mapping[str, str]]) -> int:
    return PROMPT_TOKENS


def _ok(prompt_tokens: int | None = PROMPT_TOKENS, content: str = VALID_RAW) -> Generation:
    return Generation(content=content, done_reason="stop", prompt_tokens=prompt_tokens)


class FakeGenerator:
    def __init__(self, responses: list[Generation]) -> None:
        self.responses = responses
        self.schemas: list[dict[str, Any] | None] = []

    def generate(
        self, messages: list[dict[str, str]], format_schema: dict[str, Any] | None = None
    ) -> Generation:
        self.schemas.append(format_schema)
        return self.responses[len(self.schemas) - 1]


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    responses: list[Generation],
    *extra: str,
) -> tuple[int, FakeGenerator]:
    db = tmp_path / "hue.sqlite"
    db.write_bytes(b"")
    evalset = tmp_path / "hue_eval_v1.jsonl"
    evalset.write_text("", encoding="utf-8")
    generator = FakeGenerator(responses)
    monkeypatch.setattr(check_export, "load_entries_and_places", lambda args: (ENTRIES, PLACES))
    monkeypatch.setattr(check_export, "load_counter", lambda config: fixed_counter)
    monkeypatch.setattr(check_export, "make_generator", lambda args, generation: generator)
    argv = [
        "--model",
        "travel-sft-v1-smoke",
        "--config",
        str(SFT_YAML),
        "--eval-config",
        str(EVAL_YAML),
        "--db",
        str(db),
        "--evalset",
        str(evalset),
        *extra,
    ]
    return check_export.main(argv), generator


def test_all_tokens_match_and_all_json_parses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "reports" / "check.json"
    responses = [_ok() for _ in range(4)]
    rc, generator = _run(
        tmp_path, monkeypatch, responses, "--tokens", "3", "--json", "2", "--out", str(out)
    )

    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["model"] == "travel-sft-v1-smoke"
    assert report["tokens_checked"] == 3
    assert report["tokens_matched"] == 3
    assert report["json_checked"] == 2
    assert report["json_parsed"] == 2
    assert [entry["key"] for entry in report["entries"]] == [e.key for e in ENTRIES[:3]]
    # Prompt và schema giống bước eval: schema ghim đúng số ngày của từng request.
    assert generator.schemas == [itinerary_format_schema(e.request.num_days) for e in ENTRIES[:3]]


def test_one_token_mismatch_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "check.json"
    responses = [_ok(), _ok(prompt_tokens=PROMPT_TOKENS - 1), _ok()]
    rc, _ = _run(
        tmp_path, monkeypatch, responses, "--tokens", "3", "--json", "0", "--out", str(out)
    )

    assert rc == 1
    report = json.loads(out.read_text(encoding="utf-8"))
    assert [entry["tokens_match"] for entry in report["entries"]] == [True, False, True]
    assert report["entries"][1]["ollama_tokens"] == PROMPT_TOKENS - 1
    assert report["entries"][1]["expected_tokens"] == PROMPT_TOKENS
    assert report["tokens_matched"] == 2


def test_missing_prompt_tokens_counts_as_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "check.json"
    rc, _ = _run(
        tmp_path,
        monkeypatch,
        [_ok(prompt_tokens=None)],
        "--tokens",
        "1",
        "--json",
        "0",
        "--out",
        str(out),
    )

    assert rc == 1
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["entries"][0]["tokens_match"] is False
    assert report["entries"][0]["ollama_tokens"] is None


def test_unparseable_output_within_json_checks_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "check.json"
    responses = [_ok(), _ok(content="không phải JSON"), _ok()]
    rc, _ = _run(
        tmp_path, monkeypatch, responses, "--tokens", "0", "--json", "3", "--out", str(out)
    )

    assert rc == 1
    report = json.loads(out.read_text(encoding="utf-8"))
    assert [entry["parsed"] for entry in report["entries"]] == [True, False, True]
    assert report["json_checked"] == 3
    assert report["json_parsed"] == 2


def test_output_beyond_json_checks_is_not_parse_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "check.json"
    # Hai request cuối không parse được, nhưng nằm ngoài --json 2 nên không được tính.
    responses = [_ok(), _ok(), _ok(content="hỏng"), _ok(content="hỏng")]
    rc, _ = _run(
        tmp_path, monkeypatch, responses, "--tokens", "4", "--json", "2", "--out", str(out)
    )

    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert "parsed" not in report["entries"][2]
    assert "parsed" not in report["entries"][3]
    assert report["json_checked"] == 2
    assert report["tokens_checked"] == 4


def test_token_check_applies_only_to_first_tokens_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # --tokens 2 --json 3: JSON kiểm 3 request đầu, token chỉ kiểm 2 request đầu.
    out = tmp_path / "check.json"
    responses = [_ok(), _ok(), _ok(prompt_tokens=1)]
    rc, generator = _run(
        tmp_path, monkeypatch, responses, "--tokens", "2", "--json", "3", "--out", str(out)
    )

    assert rc == 0  # request thứ ba lệch token nhưng không được kiểm token
    report = json.loads(out.read_text(encoding="utf-8"))
    assert len(generator.schemas) == 3
    assert report["tokens_checked"] == 2
    assert report["json_checked"] == 3
    third = report["entries"][2]
    assert "tokens_match" not in third
    assert "expected_tokens" not in third
    assert third["parsed"] is True


def test_make_generator_uses_generation_section_of_eval_yaml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, Any] = {}

    class RecordingGenerator:
        def __init__(self, model: str, **kwargs: Any) -> None:
            recorded["model"] = model
            recorded.update(kwargs)

    monkeypatch.setattr(check_export, "OllamaGenerator", RecordingGenerator)
    args = check_export.parse_args(["--model", "travel-sft-v1-smoke"])
    check_export.make_generator(args, check_export.load_eval_generation(EVAL_YAML))

    assert recorded == {
        "model": "travel-sft-v1-smoke",
        "host": check_export.DEFAULT_HOST,
        "temperature": 0.0,
        "seed": 0,
        "num_predict": 2048,
        "num_ctx": 8192,
    }


def test_load_counter_counts_prompt_with_generation_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    class FakeChat:
        @classmethod
        def from_dir(cls, model_dir: Path) -> FakeChat:
            seen["model_dir"] = model_dir
            return cls()

        def render(
            self, messages: Sequence[Mapping[str, str]], *, add_generation_prompt: bool
        ) -> str:
            text = "".join(message["content"] for message in messages)
            return text + ("|GEN" if add_generation_prompt else "")

        def encode(self, text: str) -> list[int]:
            return [ord(char) for char in text]

    monkeypatch.setattr(check_export, "ChatTokenizer", FakeChat)
    monkeypatch.setattr(check_export, "hf_snapshot_dir", lambda repo, revision: tmp_path)
    counter = check_export.load_counter(check_export.load_sft_config(SFT_YAML))

    assert seen["model_dir"] == tmp_path
    # "ab" + "|GEN" = 6 ký tự; không có generation prompt thì chỉ là 2.
    assert counter([{"role": "user", "content": "ab"}]) == 6


def test_missing_input_file_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_export, "load_entries_and_places", lambda args: (ENTRIES, PLACES))
    with pytest.raises(SystemExit):
        check_export.main(
            [
                "--model",
                "m",
                "--config",
                str(tmp_path / "missing.yaml"),
                "--eval-config",
                str(EVAL_YAML),
            ]
        )
