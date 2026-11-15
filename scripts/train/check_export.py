"""Kiểm model SFT đã export vào Ollama: token prompt khớp, output parse được.

    python scripts/train/check_export.py --model travel-sft-v1-smoke
    python scripts/train/check_export.py --model travel-sft-v1 --tokens 10 --json 3 --out PATH

Chạy `max(--tokens, --json)` request dev đầu tiên qua Ollama, mỗi request một lần, cùng prompt
và format schema với bước eval (`training/runner.py`). Với mỗi request trong `--tokens` đầu:
`prompt_eval_count` của Ollama phải bằng số token của prompt do `training/chat.py` render
(`add_generation_prompt=True`, thinking tắt), tức đúng chuỗi model thấy lúc sinh. Với mỗi request
trong `--json` đầu: output phải được `parse_itinerary` nhận. Exit 0 khi mọi lần kiểm đều đạt, còn
lại exit 1. Lỗi hạ tầng (mạng, model chưa pull) để `GenerationError` dừng lệnh, không tính là
model hỏng.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from travel_agent.domain.models import Place
from travel_agent.planning.candidates import select_candidates
from travel_agent.planning.prompt import build_messages
from travel_agent.training.chat import ChatTokenizer, TokenizerUnavailable
from travel_agent.training.commands import load_usable_places
from travel_agent.training.generator import (
    DEFAULT_HOST,
    OllamaGenerator,
    PlanGenerator,
    itinerary_format_schema,
)
from travel_agent.training.parsing import parse_itinerary
from travel_agent.training.requests import EvalEntry, Split, read_eval_set
from travel_agent.training.runner import candidate_seed
from travel_agent.training.sft_config import SftConfig, load_sft_config
from travel_agent.training.tokens import TokenCounter, hf_snapshot_dir

DEFAULT_TOKENS = 10
DEFAULT_JSON = 3


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True, help="Tên model trong Ollama")
    parser.add_argument("--config", type=Path, default=Path("configs/sft.yaml"))
    parser.add_argument("--eval-config", type=Path, default=Path("configs/eval.yaml"))
    parser.add_argument("--db", type=Path, default=Path("data/hue.sqlite"))
    parser.add_argument("--evalset", type=Path, default=Path("data/eval/hue_eval_v1.jsonl"))
    parser.add_argument("--tokens", type=int, default=DEFAULT_TOKENS, help="Số request kiểm token")
    parser.add_argument("--json", type=int, default=DEFAULT_JSON, help="Số request kiểm JSON")
    parser.add_argument("--out", type=Path, help="Ghi báo cáo JSON ra file")
    return parser.parse_args(argv)


def load_eval_generation(path: Path) -> dict[str, Any]:
    """Mục `generation` của configs/eval.yaml. Đây là bộ tham số mà DVC dùng cho eval."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    generation = data.get("generation") if isinstance(data, dict) else None
    if not isinstance(generation, dict):
        raise SystemExit(f"{path} thiếu mục generation.")
    return generation


def load_entries_and_places(args: argparse.Namespace) -> tuple[list[EvalEntry], list[Place]]:
    """Dev entry của bộ eval, và địa điểm theo đúng cách lệnh `eval` nạp (`load_usable_places`)."""
    return read_eval_set(args.evalset, Split.DEV), load_usable_places(args.db)


def load_counter(config: SftConfig) -> TokenCounter:
    """Đếm token prompt theo tokenizer của base model.

    Không dùng `ChatTokenizer.count`: nó render với `add_generation_prompt=False`, tức không có
    đầu lượt assistant mà Ollama vẫn tính vào `prompt_eval_count`.
    """
    model_dir = hf_snapshot_dir(config.sft.base_model.repo, config.sft.base_model.revision)
    chat = ChatTokenizer.from_dir(model_dir)

    def count(messages: Sequence[Mapping[str, str]]) -> int:
        return len(chat.encode(chat.render(messages, add_generation_prompt=True)))

    return count


def make_generator(args: argparse.Namespace, generation: dict[str, Any]) -> OllamaGenerator:
    """Cùng cách lệnh `eval` tạo generator, chỉ khác là tham số lấy từ configs/eval.yaml."""
    return OllamaGenerator(
        args.model,
        host=DEFAULT_HOST,
        temperature=generation["temperature"],
        seed=generation["seed"],
        num_predict=generation["num_predict"],
        num_ctx=generation["num_ctx"],
    )


def run_checks(
    entries: Sequence[EvalEntry],
    places: Sequence[Place],
    generator: PlanGenerator,
    counter: TokenCounter,
    tokens: int,
    json_checks: int,
) -> list[dict[str, Any]]:
    """Mỗi entry trong `max(tokens, json_checks)` đầu được sinh đúng một lần.

    Entry nào nằm trong `tokens` đầu mới có các khóa token; entry nào nằm trong `json_checks`
    đầu mới có khóa `parsed`. Entry ngoài cả hai phạm vi không có khóa kiểm nào.
    """
    records: list[dict[str, Any]] = []
    for index, entry in enumerate(entries[: max(tokens, json_checks)]):
        candidates = select_candidates(entry.request, places, candidate_seed(entry.key))
        messages = build_messages(entry.request, candidates)
        schema = itinerary_format_schema(entry.request.num_days)
        generation = generator.generate(messages, format_schema=schema)
        record: dict[str, Any] = {"key": entry.key}
        if index < tokens:
            expected = counter(messages)
            record["expected_tokens"] = expected
            record["ollama_tokens"] = generation.prompt_tokens
            record["tokens_match"] = (
                generation.prompt_tokens is not None and generation.prompt_tokens == expected
            )
        if index < json_checks:
            record["parsed"] = parse_itinerary(generation.content) is not None
        print(_describe(record), flush=True)
        records.append(record)
    return records


def _describe(record: Mapping[str, Any]) -> str:
    parts = [str(record["key"])]
    if "tokens_match" in record:
        status = "khớp" if record["tokens_match"] else "LỆCH"
        parts.append(
            f"token ollama={record['ollama_tokens']} tokenizer={record['expected_tokens']} {status}"
        )
    if "parsed" in record:
        parts.append("json " + ("ok" if record["parsed"] else "KHÔNG PARSE"))
    return "  ".join(parts)


def build_report(model: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    token_records = [record for record in records if "tokens_match" in record]
    json_records = [record for record in records if "parsed" in record]
    return {
        "model": model,
        "tokens_checked": len(token_records),
        "tokens_matched": sum(1 for record in token_records if record["tokens_match"]),
        "json_checked": len(json_records),
        "json_parsed": sum(1 for record in json_records if record["parsed"]),
        "entries": records,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.tokens < 0 or args.json < 0:
        raise SystemExit("--tokens và --json không được âm.")
    for path in (args.config, args.eval_config, args.db, args.evalset):
        if not path.exists():
            raise SystemExit(f"Không tìm thấy {path}.")

    config = load_sft_config(args.config)
    generation = load_eval_generation(args.eval_config)
    try:
        counter = load_counter(config)
    except TokenizerUnavailable as exc:
        raise SystemExit(f"Không nạp được tokenizer ({exc}).") from exc
    entries, places = load_entries_and_places(args)
    wanted = max(args.tokens, args.json)
    if len(entries) < wanted:
        print(
            f"CẢNH BÁO: chỉ có {len(entries)} request dev, ít hơn {wanted} cần kiểm.",
            file=sys.stderr,
        )

    generator = make_generator(args, generation)
    records = run_checks(entries, places, generator, counter, args.tokens, args.json)
    report = build_report(args.model, records)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")

    passed = (
        report["tokens_matched"] == report["tokens_checked"]
        and report["json_parsed"] == report["json_checked"]
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
