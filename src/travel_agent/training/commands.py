"""Lệnh CLI cho eval, dataset và kiểm reward: make-evalset, eval, ..., reward-report."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

import yaml

from travel_agent.data.place_repository import InMemoryPlaceRepository
from travel_agent.domain.models import Pace, Place, PlanRequest, TravelMode
from travel_agent.planning.candidates import DEFAULT_LANDMARKS
from travel_agent.planning.pipeline import PlanResult, plan_trip
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
from travel_agent.training.gitinfo import current_commit
from travel_agent.training.metrics import (
    EvalSummary,
    PlanOutcome,
    incomparable,
    regressions,
    summarize,
)
from travel_agent.training.requests import Split, build_eval_set, read_eval_set, write_eval_set
from travel_agent.training.reward_report import (
    RewardSummary,
    check_report,
    load_outcomes,
    score_outcomes,
    summarize_rewards,
)
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
EXIT_REWARD_FAILED = 4  # reward không qua kiểm tra (reward-report); trùng số với dataset hỏng
EXIT_PLAN_INVALID = (
    EXIT_REGRESSION  # lệnh plan còn lỗi ERROR; cùng số 3 nhưng là kết quả, không phải cổng
)

RL_CONFIG = Path("configs/rl.yaml")  # final.ollama_model: model mặc định của lệnh plan
EVAL_CONFIG = Path("configs/eval.yaml")  # mục generation: tham số sinh, cùng bộ DVC dùng cho eval
GENERATION_KEYS = ("temperature", "seed", "num_predict", "num_ctx")


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

    reward = sub.add_parser(
        "reward-report", help="Chấm reward trên output dev đã có; không qua kiểm tra thì exit 4"
    )
    reward.add_argument("--db", type=Path, default=Path("data/hue.sqlite"))
    reward.add_argument("--evalset", type=Path, default=Path("data/eval/hue_eval_v1.jsonl"))
    reward.add_argument(
        "--outcomes",
        type=_named_path,
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="File *.outcomes.jsonl của một mốc; lặp lại cho nhiều mốc",
    )
    reward.add_argument("--better", required=True, help="Tên mốc được kỳ vọng tốt hơn")
    reward.add_argument("--worse", required=True, help="Tên mốc được kỳ vọng kém hơn")
    reward.add_argument("--out", type=Path, required=True, help="File JSON báo cáo")
    reward.set_defaults(func=_cmd_reward_report)

    plan = sub.add_parser(
        "plan", help="Lập lịch một chuyến đi qua Ollama (xếp giờ, sửa lỗi); in JSON"
    )
    plan.add_argument("--model", help="Tag Ollama; mặc định là final.ollama_model trong rl.yaml")
    plan.add_argument("--request", type=Path, help="File JSON PlanRequest (thay cho các cờ dưới)")
    plan.add_argument("--days", type=int, help="Số ngày, 1 đến 7")
    plan.add_argument("--start-date", type=_date_arg, help="Ngày đầu, dạng YYYY-MM-DD")
    plan.add_argument("--pace", type=Pace, choices=list(Pace))
    plan.add_argument("--interests", type=_csv_arg, help="Sở thích, cách nhau bằng dấu phẩy")
    plan.add_argument("--travel-mode", type=TravelMode, choices=list(TravelMode))
    plan.add_argument("--day-start", type=_clock_arg, help="Giờ bắt đầu ngày, HH:MM")
    plan.add_argument("--day-end", type=_clock_arg, help="Giờ kết thúc ngày, HH:MM")
    plan.add_argument("--no-retime", action="store_true", help="Giữ giờ của model, không xếp lại")
    plan.add_argument(
        "--no-fill",
        action="store_true",
        help="Không lấp khoảng trống (bữa ăn, quãng trống dài) bằng điểm thêm",
    )
    plan.add_argument("--max-repairs", type=int, default=2, help="Số lượt sửa tối đa")
    plan.add_argument(
        "--landmarks",
        type=int,
        default=DEFAULT_LANDMARKS,
        help="Số điểm tham quan nổi tiếng thêm vào candidate, 0 để tắt (mặc định 6)",
    )
    plan.add_argument("--db", type=Path, default=Path("data/hue.sqlite"))
    plan.add_argument("--host", default=DEFAULT_HOST)
    plan.set_defaults(func=_cmd_plan)


_PLAN_FLAGS = {
    "days": "num_days",
    "start_date": "start_date",
    "pace": "pace",
    "interests": "interests",
    "travel_mode": "travel_mode",
    "day_start": "day_start",
    "day_end": "day_end",
}


def _date_arg(text: str) -> dt.date:
    try:
        return dt.date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("cần ngày dạng YYYY-MM-DD") from exc


def _clock_arg(text: str) -> dt.time:
    try:
        return dt.time.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("cần giờ dạng HH:MM") from exc


def _csv_arg(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def _plan_request(args: argparse.Namespace) -> PlanRequest:
    """Từ file JSON hoặc từ các cờ; ném ValueError (kèm lý do tiếng Việt) nếu thiếu hoặc sai."""
    flags = {dest: getattr(args, dest) for dest in _PLAN_FLAGS}
    given = {dest: value for dest, value in flags.items() if value is not None}
    if args.request is not None:
        if given:
            raise ValueError("--request không đi cùng các cờ yêu cầu (--days, --pace, ...)")
        return PlanRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
    if args.days is None or args.start_date is None:
        raise ValueError("cần --request, hoặc tối thiểu --days và --start-date")
    return PlanRequest.model_validate({_PLAN_FLAGS[dest]: value for dest, value in given.items()})


def _rl_final_model(path: Path) -> str | None:
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    final = data.get("final") if isinstance(data, dict) else None
    model = final.get("ollama_model") if isinstance(final, dict) else None
    return model if isinstance(model, str) and model else None


def _generation_params(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    generation = data.get("generation") if isinstance(data, dict) else None
    if not isinstance(generation, dict):
        raise ValueError(f"{path} thiếu mục generation")
    missing = [key for key in GENERATION_KEYS if key not in generation]
    if missing:
        raise ValueError(f"{path} thiếu {', '.join(missing)} trong generation")
    return {key: generation[key] for key in GENERATION_KEYS}


def _plan_payload(result: PlanResult) -> dict[str, Any]:
    issues = result.report.issues if result.report is not None else []
    return {
        "valid": result.valid,
        "itinerary": (
            result.itinerary.model_dump(mode="json") if result.itinerary is not None else None
        ),
        "issues": [
            {"code": issue.code.value, "severity": issue.severity.value, "message": issue.message}
            for issue in issues
        ],
        "dropped": [dataclasses.asdict(stop) for stop in result.dropped],
        "missing_must": result.missing_must,
        "inserted_must": result.inserted_must,
        "added": [dataclasses.asdict(stop) for stop in result.added],
        "attempts": [
            {
                "kind": attempt.kind,
                "parsed": attempt.parsed,
                "error_count": attempt.error_count,
                "latency_s": round(attempt.latency_s, 2),
            }
            for attempt in result.attempts
        ],
    }


def _cmd_plan(args: argparse.Namespace) -> int:
    if not args.db.exists():
        print(f"Không tìm thấy {args.db}.", file=sys.stderr)
        return EXIT_USAGE
    if args.max_repairs < 0:
        print("--max-repairs không được âm.", file=sys.stderr)
        return EXIT_USAGE
    if args.landmarks < 0:
        print("--landmarks không được âm.", file=sys.stderr)
        return EXIT_USAGE
    model = args.model or _rl_final_model(RL_CONFIG)
    if model is None:
        print("Thiếu --model và configs/rl.yaml không có final.ollama_model.", file=sys.stderr)
        return EXIT_USAGE
    try:
        request = _plan_request(args)
        generation = _generation_params(EVAL_CONFIG)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"Yêu cầu không hợp lệ: {exc}", file=sys.stderr)
        return EXIT_USAGE

    generator = OllamaGenerator(
        model,
        host=args.host,
        temperature=generation["temperature"],
        seed=generation["seed"],
        num_predict=generation["num_predict"],
        num_ctx=generation["num_ctx"],
    )
    result = plan_trip(
        request,
        load_usable_places(args.db),
        generator,
        HaversineEstimator(),
        retime=not args.no_retime,
        max_repairs=args.max_repairs,
        landmarks=args.landmarks,
        fill_gaps=not args.no_fill,
    )
    print(json.dumps(_plan_payload(result), ensure_ascii=False, indent=2))
    return EXIT_OK if result.valid else EXIT_PLAN_INVALID


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


def _named_path(text: str) -> tuple[str, Path]:
    name, sep, path = text.partition("=")
    if not sep or not name or not path:
        raise argparse.ArgumentTypeError("cần dạng NAME=PATH")
    return name, Path(path)


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
        "git_commit": current_commit([args.out, outcomes_path]),
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
        git_commit=current_commit([args.out, args.manifest]),
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


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def _print_reward_table(summaries: dict[str, RewardSummary]) -> None:
    header = (
        f"{'mốc':<14}{'n':>4}{'mean':>9}{'valid':>9}{'invalid':>9}"
        f"{'n_valid':>9}{'n_inv':>7}{'mismatch':>10}{'floor_days':>12}"
    )
    print(header)
    for name, summary in summaries.items():
        print(
            f"{name:<14}{summary.n:>4}{summary.mean_reward:>9.3f}"
            f"{_fmt(summary.mean_reward_valid):>9}{_fmt(summary.mean_reward_invalid):>9}"
            f"{summary.n_valid:>9}{summary.n_invalid:>7}{summary.valid_mismatch:>10}"
            f"{summary.below_floor_days:>12}"
        )


def _cmd_reward_report(args: argparse.Namespace) -> int:
    outcome_paths = [path for _, path in args.outcomes]
    if _missing([args.db, args.evalset, *outcome_paths]):
        return EXIT_USAGE
    names = [name for name, _ in args.outcomes]
    if len(set(names)) != len(names):
        print("Tên mốc trong --outcomes bị trùng.", file=sys.stderr)
        return EXIT_USAGE
    unknown = [name for name in (args.better, args.worse) if name not in names]
    if unknown:
        print(f"Không có --outcomes cho: {', '.join(unknown)}.", file=sys.stderr)
        return EXIT_USAGE

    entries = read_eval_set(args.evalset, Split.DEV)
    places = load_usable_places(args.db)
    travel = HaversineEstimator()
    summaries: dict[str, RewardSummary] = {}
    try:
        for name, path in args.outcomes:
            scored = score_outcomes(entries, load_outcomes(path), places, travel)
            summaries[name] = summarize_rewards(scored)
    except ValueError as exc:
        print(f"Không chấm được reward: {exc}", file=sys.stderr)
        return EXIT_USAGE

    failures = check_report(summaries, args.better, args.worse)
    report = {
        "summaries": {name: summary.model_dump(mode="json") for name, summary in summaries.items()},
        "failures": failures,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    _print_reward_table(summaries)
    for failure in failures:
        print(f"KHÔNG QUA KIỂM TRA: {failure}", file=sys.stderr)
    if failures:
        return EXIT_REWARD_FAILED
    print("Reward qua mọi kiểm tra.")
    return EXIT_OK
