"""Lệnh CLI cho eval: make-evalset, eval."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import TextIO

from travel_agent.domain.models import Place
from travel_agent.review.models import ReviewStatus
from travel_agent.review.store import ReviewStore
from travel_agent.routing.travel_time import HaversineEstimator
from travel_agent.training.generator import DEFAULT_HOST, OllamaGenerator
from travel_agent.training.metrics import EvalSummary, PlanOutcome, regressions, summarize
from travel_agent.training.requests import Split, build_eval_set, read_eval_set, write_eval_set
from travel_agent.training.runner import run_eval
from travel_agent.training.tracking import log_eval_run

EXIT_OK = 0
EXIT_REGRESSION = 1
EXIT_USAGE = 2


def add_training_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    evalset = sub.add_parser("make-evalset", help="Sinh bộ eval 100 request (chạy một lần)")
    evalset.add_argument("--out", type=Path, required=True)
    evalset.add_argument("--seed", type=int, required=True)
    evalset.set_defaults(func=_cmd_make_evalset)

    run = sub.add_parser("eval", help="Chạy bộ eval qua một model trong Ollama")
    run.add_argument("--db", type=Path, required=True)
    run.add_argument("--evalset", type=Path, required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--split", type=Split, choices=list(Split), default=Split.DEV)
    run.add_argument("--allow-test", action="store_true", help="Cho phép chạy bộ test đóng băng")
    run.add_argument("--limit", type=int, help="Chỉ chạy N request đầu (smoke test)")
    run.add_argument("--host", default=DEFAULT_HOST)
    run.add_argument("--temperature", type=float, default=0.0)
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--num-predict", type=int, default=2048)
    run.add_argument("--num-ctx", type=int, default=8192, help="Cửa sổ ngữ cảnh gửi cho Ollama")
    run.add_argument("--no-schema", action="store_true", help='Dùng format "json" thay schema')
    run.add_argument("--run-name", default="eval")
    run.add_argument("--mlflow", action="store_true", help="Ghi tham số và metric vào MLflow")
    run.add_argument("--baseline", type=Path, help="File kết quả mốc trước; kém hơn thì exit 1")
    run.set_defaults(func=_cmd_eval)


def load_usable_places(db: Path) -> list[Place]:
    """Mọi địa điểm trừ loại người duyệt đã loại; đã áp override của người duyệt."""
    store = ReviewStore(db, read_only=True)  # file DB là dependency của DVC, không được ghi
    try:
        items, _ = store.query(limit=-1)  # LIMIT -1 = không giới hạn
    finally:
        store.close()
    return [item.effective_place() for item in items if item.status is not ReviewStatus.REJECTED]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def _load_baseline(path: Path) -> EvalSummary | None:
    """Đọc phần summary của file mốc; in lỗi tiếng Việt và trả None nếu thiếu hoặc sai dạng."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return EvalSummary.model_validate(data["summary"])
    except OSError:
        print(f"Không đọc được file mốc {path}.", file=sys.stderr)
    except (ValueError, KeyError, TypeError) as exc:
        print(f"File mốc {path} không hợp lệ: {exc}", file=sys.stderr)
    return None


def _append_outcome(handle: TextIO, outcome: PlanOutcome) -> None:
    handle.write(outcome.model_dump_json() + "\n")
    handle.flush()


def _cmd_make_evalset(args: argparse.Namespace) -> int:
    entries = build_eval_set(args.seed)
    write_eval_set(entries, args.out)
    test = sum(1 for entry in entries if entry.split is Split.TEST)
    dev = len(entries) - test
    print(f"Đã ghi {len(entries)} request vào {args.out} (dev {dev}, test {test}).")
    return EXIT_OK


def _cmd_eval(args: argparse.Namespace) -> int:
    for path in (args.db, args.evalset):
        if not path.exists():
            print(f"Không tìm thấy {path}.", file=sys.stderr)
            return EXIT_USAGE
    if args.split is Split.TEST and not args.allow_test:
        print("Bộ test đóng băng. Thêm --allow-test khi chạy so sánh cuối.", file=sys.stderr)
        return EXIT_USAGE

    baseline: EvalSummary | None = None
    if args.baseline is not None:
        baseline = _load_baseline(args.baseline)
        if baseline is None:
            return EXIT_USAGE

    entries = read_eval_set(args.evalset, args.split)
    if args.limit is not None:
        entries = entries[: args.limit]
    generator = OllamaGenerator(
        args.model,
        host=args.host,
        temperature=args.temperature,
        seed=args.seed,
        num_predict=args.num_predict,
        num_ctx=args.num_ctx,
        schema_format=not args.no_schema,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    outcomes_path = args.out.with_suffix(".outcomes.jsonl")
    # Ghi từng outcome ngay khi có: lỗi giữa chừng (Ollama chết) không làm mất phần đã chạy.
    with outcomes_path.open("w", encoding="utf-8", newline="\n") as handle:
        outcomes = run_eval(
            entries,
            load_usable_places(args.db),
            generator,
            HaversineEstimator(),
            on_outcome=lambda outcome: _append_outcome(handle, outcome),
        )
    summary = summarize(outcomes)
    meta: dict[str, str | int | float] = {
        "run_name": args.run_name,
        "model": args.model,
        "split": args.split.value,
        "temperature": args.temperature,
        "seed": args.seed,
        "num_predict": args.num_predict,
        "num_ctx": args.num_ctx,
        "schema_format": not args.no_schema,
        "limit": "all" if args.limit is None else args.limit,
        "host": args.host,
        "git_commit": current_commit(),
        "evalset_sha256": file_sha256(args.evalset),
        "db_sha256": file_sha256(args.db),
    }

    report = {"meta": meta, "summary": summary.model_dump(mode="json")}
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{args.run_name}: {summary.n} request, model {args.model}, split {args.split.value}")
    print(f"  first_pass_valid_rate: {summary.first_pass_valid_rate:.3f}")
    print(f"  parse_error_rate:      {summary.parse_error_rate:.3f}")
    print(f"  unknown_place_rate:    {summary.unknown_place_rate:.3f}")
    print(f"  avg_stops_per_day:     {summary.avg_stops_per_day:.2f}")
    print(f"  distinct_place_count:  {summary.distinct_place_count}")
    print(f"  latency_p50_s:         {summary.latency_p50_s:.1f}")
    for code, count in summary.issue_code_distribution.items():
        print(f"  issue {code}: {count}")

    if args.mlflow:
        log_eval_run(args.run_name, meta, summary)
    if baseline is not None:
        problems = regressions(summary, baseline)
        for problem in problems:
            print(f"KHÔNG QUA CỔNG: {problem}", file=sys.stderr)
        if problems:
            return EXIT_REGRESSION
    return EXIT_OK
