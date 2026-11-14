"""Lệnh CLI cho eval và dataset: make-evalset, eval, build-dataset, check-dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from travel_agent.data.place_repository import InMemoryPlaceRepository
from travel_agent.domain.models import Place
from travel_agent.review.models import ReviewStatus
from travel_agent.review.store import ReviewStore
from travel_agent.routing.travel_time import HaversineEstimator
from travel_agent.training.dataset import (
    CheckParams,
    build_manifest,
    build_samples,
    eval_keys,
    load_config,
    write_samples,
)
from travel_agent.training.dataset_check import check_dataset
from travel_agent.training.generator import DEFAULT_HOST, OllamaGenerator
from travel_agent.training.metrics import (
    EvalSummary,
    PlanOutcome,
    incomparable,
    regressions,
    summarize,
)
from travel_agent.training.requests import Split, build_eval_set, read_eval_set, write_eval_set
from travel_agent.training.runner import run_eval
from travel_agent.training.tokens import (
    TokenCounter,
    TokenizerUnavailable,
    hf_snapshot_dir,
    load_chat_token_counter,
)
from travel_agent.training.tracking import log_eval_run

EXIT_OK = 0
# 1 là exit code mặc định của Python khi crash; không dùng cho kết quả của cổng.
EXIT_USAGE = 2  # sai cách dùng, hoặc báo cáo mốc chạy khác điều kiện
EXIT_REGRESSION = 3
EXIT_DATASET_INVALID = 4  # dataset không đạt (build không đủ mẫu, hoặc check-dataset hỏng)


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
    run.add_argument(
        "--baseline",
        type=Path,
        help="File kết quả mốc trước; khác điều kiện chạy thì exit 2, kém hơn thì exit 3",
    )
    run.set_defaults(func=_cmd_eval)

    build = sub.add_parser(
        "build-dataset", help="Dựng dataset SFT từ solver (configs/dataset.yaml)"
    )
    build.add_argument("--config", type=Path, required=True)
    build.add_argument("--db", type=Path, required=True)
    build.add_argument("--evalset", type=Path, required=True, help="Bộ eval; request trùng bị loại")
    build.add_argument("--out", type=Path, required=True, help="File JSONL dataset")
    build.add_argument("--manifest", type=Path, required=True)
    build.set_defaults(func=_cmd_build_dataset)

    check = sub.add_parser("check-dataset", help="Kiểm dataset SFT; hỏng thì exit 4")
    check.add_argument("--config", type=Path, required=True)
    check.add_argument("--db", type=Path, required=True)
    check.add_argument("--evalset", type=Path, required=True)
    check.add_argument("--dataset", type=Path, required=True)
    check.add_argument("--out", type=Path, required=True, help="File JSON báo cáo kiểm tra")
    check.add_argument(
        "--tokenizer-dir",
        type=Path,
        help="Thư mục có tokenizer.json và chat_template.jinja; mặc định lấy theo config từ "
        "cache Hugging Face",
    )
    check.add_argument(
        "--allow-skip-tokens",
        action="store_true",
        help="Cho qua khi không nạp được tokenizer (báo cáo ghi token_check=skipped)",
    )
    check.set_defaults(func=_cmd_check_dataset)


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
    """Commit đang chạy; thêm `-dirty` khi file đã track có thay đổi chưa commit.

    File chưa track (ví dụ báo cáo eval mới sinh) không tính, vì không đổi code đang chạy.
    """
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    commit = head.stdout.strip()
    return f"{commit}-dirty" if status.stdout.strip() else commit


def _load_baseline(path: Path) -> tuple[dict[str, object], EvalSummary] | None:
    """Đọc meta và summary của file mốc; in lỗi tiếng Việt và trả None nếu thiếu hoặc sai dạng."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        meta = data["meta"]
        if not isinstance(meta, dict):
            raise TypeError("meta không phải object")
        return meta, EvalSummary.model_validate(data["summary"])
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

    baseline: tuple[dict[str, object], EvalSummary] | None = None
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
        baseline_meta, baseline_summary = baseline
        differing = incomparable(meta, baseline_meta)
        if differing:
            print(f"Không so được với mốc: khác {', '.join(differing)}.", file=sys.stderr)
            return EXIT_USAGE
        problems = regressions(summary, baseline_summary)
        for problem in problems:
            print(f"KHÔNG QUA CỔNG: {problem}", file=sys.stderr)
        if problems:
            return EXIT_REGRESSION
    return EXIT_OK


def _missing(paths: Sequence[Path]) -> bool:
    for path in paths:
        if not path.exists():
            print(f"Không tìm thấy {path}.", file=sys.stderr)
            return True
    return False


def _cmd_build_dataset(args: argparse.Namespace) -> int:
    if _missing([args.config, args.db, args.evalset]):
        return EXIT_USAGE
    params = load_config(args.config).dataset
    started = time.perf_counter()
    result = build_samples(
        params, load_usable_places(args.db), eval_keys(args.evalset), HaversineEstimator()
    )
    elapsed = time.perf_counter() - started
    stats = result.stats
    if len(result.samples) < params.target_samples:
        print(
            f"Chỉ dựng được {len(result.samples)}/{params.target_samples} mẫu sau "
            f"{stats.requests_used} request; tăng max_requests. Không ghi file.",
            file=sys.stderr,
        )
        return EXIT_DATASET_INVALID
    write_samples(result.samples, args.out)
    manifest = build_manifest(
        params,
        result,
        jsonl_sha256=file_sha256(args.out),
        db_sha256=file_sha256(args.db),
        evalset_sha256=file_sha256(args.evalset),
        git_commit=current_commit(),
    )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Đã ghi {manifest['samples']} mẫu vào {args.out} ({elapsed:.0f} giây).")
    print(f"  theo loại: {manifest['samples_by_kind']}")
    print(f"  repair theo kiểu phá: {manifest['repair_by_corruption']}")
    print(f"  request dùng: {stats.requests_used}, solver bỏ: {manifest['solver_dropped']}")
    print(f"  request trùng bộ eval đã loại: {stats.eval_collisions_removed}")
    return EXIT_OK


def _token_counter(args: argparse.Namespace, params: CheckParams) -> TokenCounter | None:
    model_dir = args.tokenizer_dir or hf_snapshot_dir(
        params.tokenizer.repo, params.tokenizer.revision
    )
    try:
        return load_chat_token_counter(model_dir)
    except TokenizerUnavailable as exc:
        print(f"Không nạp được tokenizer ({exc}).", file=sys.stderr)
        return None


def _cmd_check_dataset(args: argparse.Namespace) -> int:
    if _missing([args.config, args.db, args.evalset, args.dataset]):
        return EXIT_USAGE
    params = load_config(args.config).check
    counter = _token_counter(args, params)
    places = InMemoryPlaceRepository(load_usable_places(args.db))
    with args.dataset.open(encoding="utf-8") as handle:
        report = check_dataset(
            handle,
            places,
            eval_keys(args.evalset),
            params,
            HaversineEstimator(),
            counter,
            allow_skip_tokens=args.allow_skip_tokens,
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")

    print(f"{report.samples} mẫu {report.samples_by_kind}; token_check: {report.token_check}")
    if report.max_tokens_seen is not None:
        print(
            f"  mẫu dài nhất {report.max_tokens_seen} token (giới hạn {report.max_tokens_allowed})"
        )
    if report.token_check == "skipped":
        print("  CẢNH BÁO: chưa kiểm độ dài token (--allow-skip-tokens).")
    for failure in report.failures[:20]:
        where = f"dòng {failure.line}: " if failure.line is not None else ""
        print(f"  HỎNG {failure.check.value}: {where}{failure.message}", file=sys.stderr)
    if not report.passed:
        print(f"Dataset KHÔNG ĐẠT: {report.failure_counts}", file=sys.stderr)
        return EXIT_DATASET_INVALID
    print("Dataset đạt mọi kiểm tra.")
    return EXIT_OK
