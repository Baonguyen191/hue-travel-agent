"""Lệnh CLI hiểu câu: parse "câu" (một câu, in JSON), qu-eval (đo trên bộ eval), ask (hiểu rồi
lập lịch).

Đăng ký từ travel_agent/cli.py, không nằm trong training/commands.py, để closure của stage DVC
(tests/training/test_dvc_pipeline.py) không đổi.

Tham số sinh cố định cho parse và qu-eval (không đọc từ configs/eval.yaml, để đo QU không lẫn với
eval lập lịch): temperature 0, seed 0, num_ctx 4096, num_predict 512. Lệnh ask hiểu câu bằng bộ
tham số đó, còn lập lịch dùng mục generation của configs/eval.yaml như lệnh plan.

Lưu ý VRAM: model QU mặc định qwen3.5:4b (~3,3 GB) và model lập lịch (~3,4 GB) cùng vừa 8 GB VRAM,
nên Ollama không phải đổi model. Nếu chọn qwen3.5:9b (~6,6 GB) thì hai model không cùng vừa,
Ollama sẽ tải đổi qua lại và lần gọi đầu có thể chậm thêm vài giây.

Mã thoát của ask: 0 là có lịch hợp lệ, từ chối, hoặc báo chưa hỗ trợ; 2 sai cách dùng;
3 lịch còn lỗi ERROR; 4 cần hỏi lại (không lập lịch); 5 lỗi hạ tầng Ollama; 6 model hiểu câu
trả JSON sai schema sau khi thử lại. Mã 3 của parse và mã 3 của ask là hai ý nghĩa khác nhau,
mỗi lệnh có bảng mã riêng.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from travel_agent.planning.candidates import DEFAULT_LANDMARKS
from travel_agent.training.commands import (
    EVAL_CONFIG,
    RL_CONFIG,
    _generation_params,
    _rl_final_model,
    file_sha256,
    load_usable_places,
)
from travel_agent.training.generator import DEFAULT_HOST, GenerationError, OllamaGenerator
from travel_agent.training.gitinfo import current_commit
from travel_agent.understanding.ask import AskOutcome, ask_query, render_ask
from travel_agent.understanding.evaluate import (
    EVAL_FILE,
    EVAL_REF,
    QuSplit,
    QuSummary,
    read_gold,
    run_eval,
    split_items,
    summarize,
)
from travel_agent.understanding.extract import ExtractionError, parse_query

EXIT_OK = 0
EXIT_USAGE = 2  # sai cách dùng hoặc thiếu file
EXIT_EXTRACTION = 3  # model trả JSON sai schema sau khi thử lại (lệnh parse)
EXIT_GENERATION = 5  # lỗi hạ tầng: Ollama không chạy, model chưa pull, timeout
EXIT_PLAN_INVALID = 3  # ask: lịch còn lỗi ERROR (cùng số với EXIT_EXTRACTION, khác ý nghĩa)
EXIT_CLARIFY = 4  # ask: câu thiếu thông tin, cần hỏi lại; không gọi model lập lịch
EXIT_ASK_EXTRACTION = 6  # ask: model hiểu câu trả JSON sai schema sau khi thử lại

DEFAULT_DB = Path("data/hue.sqlite")
# Mặc định 4b: trên tập test QU đạt full match 0,88 (9b: 0,86), nhanh hơn (~2,1 s so với ~3,2 s),
# và 4b cùng model lập lịch vừa 8 GB VRAM nên không phải đổi model.
DEFAULT_QU_MODEL = "qwen3.5:4b"
# Hằng số sinh cố định của bộ hiểu câu. Đổi các số này là đổi kết quả đo, nên ghi vào báo cáo.
TEMPERATURE = 0.0
SEED = 0
NUM_CTX = 4096
NUM_PREDICT = 512


def add_understanding_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parse = sub.add_parser("parse", help="Hiểu một câu tự do qua Ollama; in ParsedQuery JSON")
    parse.add_argument("text", help="Câu yêu cầu, đặt trong dấu nháy")
    parse.add_argument("--model", help="Tag Ollama; mặc định là final.ollama_model trong rl.yaml")
    parse.add_argument("--ref", type=_date_arg, help="Ngày tham chiếu YYYY-MM-DD; mặc định hôm nay")
    parse.add_argument("--host", default=DEFAULT_HOST)
    parse.add_argument("--db", type=Path, default=DEFAULT_DB, help="DB địa điểm để liên kết tên")
    parse.set_defaults(func=_cmd_parse)

    evaluate = sub.add_parser("qu-eval", help="Đo hiểu câu trên bộ eval; ghi JSON báo cáo")
    evaluate.add_argument("--model", required=True, help="Tag Ollama cần đo")
    evaluate.add_argument(
        "--split", type=QuSplit, choices=list(QuSplit), default=QuSplit.DEV, help="dev hoặc test"
    )
    evaluate.add_argument(
        "--allow-test", action="store_true", help="Bắt buộc khi chạy --split test (bộ đóng băng)"
    )
    evaluate.add_argument("--out", type=Path, required=True, help="File JSON báo cáo")
    evaluate.add_argument("--limit", type=int, help="Chỉ chạy N mục đầu của tập đã chọn")
    evaluate.add_argument("--evalset", type=Path, default=EVAL_FILE)
    evaluate.add_argument("--db", type=Path, default=DEFAULT_DB)
    evaluate.add_argument("--host", default=DEFAULT_HOST)
    evaluate.set_defaults(func=_cmd_qu_eval)

    ask = sub.add_parser(
        "ask",
        help="Hiểu một câu tự do rồi lập lịch trình Huế (hoặc hỏi lại, từ chối, báo chưa hỗ trợ)",
        description=(
            "Hiểu câu bằng model QU, rồi lập lịch bằng model lập lịch. Câu ngoài phạm vi được từ "
            "chối; sửa lịch và hỏi thông tin địa điểm chưa hỗ trợ; câu thiếu ngày hoặc số ngày "
            "thì hỏi lại (mã thoát 4)."
        ),
        epilog=(
            "Lưu ý VRAM: mặc định QU là qwen3.5:4b (~3,3 GB), cùng model lập lịch (~3,4 GB) "
            "vừa 8 GB VRAM nên Ollama không đổi model. Dùng qwen3.5:9b (~6,6 GB) thì hai model "
            "không cùng vừa, Ollama sẽ đổi qua lại và lần gọi đầu chậm thêm vài giây."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ask.add_argument("text", help="Câu yêu cầu, đặt trong dấu nháy")
    ask.add_argument(
        "--qu-model", default=DEFAULT_QU_MODEL, help="Tag Ollama hiểu câu (mặc định qwen3.5:4b)"
    )
    ask.add_argument(
        "--plan-model", help="Tag Ollama lập lịch; mặc định là final.ollama_model trong rl.yaml"
    )
    ask.add_argument("--ref", type=_date_arg, help="Ngày tham chiếu YYYY-MM-DD; mặc định hôm nay")
    ask.add_argument("--max-repairs", type=int, default=2, help="Số lần sửa tối đa (mặc định 2)")
    ask.add_argument(
        "--landmarks",
        type=int,
        default=DEFAULT_LANDMARKS,
        help="Số điểm tham quan nổi tiếng thêm vào candidate, 0 để tắt (mặc định 6)",
    )
    ask.add_argument("--no-retime", action="store_true", help="Không xếp lại giờ theo quy tắc")
    ask.add_argument(
        "--no-fill",
        action="store_true",
        help="Không lấp khoảng trống (bữa ăn, quãng trống dài) bằng điểm thêm",
    )
    ask.add_argument("--db", type=Path, default=DEFAULT_DB, help="DB địa điểm")
    ask.add_argument("--host", default=DEFAULT_HOST)
    ask.add_argument("--json", action="store_true", help="In JSON máy đọc thay vì chữ tiếng Việt")
    ask.set_defaults(func=_cmd_ask)


def _date_arg(text: str) -> dt.date:
    try:
        return dt.date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("cần ngày dạng YYYY-MM-DD") from exc


def _generator(model: str, host: str) -> OllamaGenerator:
    return OllamaGenerator(
        model,
        host=host,
        temperature=TEMPERATURE,
        seed=SEED,
        num_predict=NUM_PREDICT,
        num_ctx=NUM_CTX,
    )


def _missing(paths: Sequence[Path]) -> bool:
    for path in paths:
        if not path.exists():
            print(f"Không tìm thấy {path}.", file=sys.stderr)
            return True
    return False


def _cmd_parse(args: argparse.Namespace) -> int:
    if _missing([args.db]):
        return EXIT_USAGE
    model = args.model or _rl_final_model(RL_CONFIG)
    if model is None:
        print("Thiếu --model và configs/rl.yaml không có final.ollama_model.", file=sys.stderr)
        return EXIT_USAGE
    ref = args.ref or dt.date.today()
    try:
        query = parse_query(
            args.text, ref, _generator(model, args.host), load_usable_places(args.db)
        )
    except ExtractionError as exc:
        print(f"Không đọc được đầu ra của model: {exc}", file=sys.stderr)
        return EXIT_EXTRACTION
    except GenerationError as exc:
        print(f"Lỗi khi gọi model: {exc}", file=sys.stderr)
        return EXIT_GENERATION
    print(query.model_dump_json(indent=2))
    return EXIT_OK


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def _print_summary(summary: QuSummary, split: QuSplit, model: str) -> None:
    print(f"{split.value}: {summary.n} mục, model {model}, lỗi trích {summary.errors}")
    print(f"  intent_acc:                  {_fmt(summary.intent_acc)}")
    print(
        f"  clarify precision / recall:  {_fmt(summary.clarify_precision)} / "
        f"{_fmt(summary.clarify_recall)}"
    )
    for name, value in summary.field_acc.items():
        print(f"  {name + ':':<28} {_fmt(value)}")
    print(
        f"  interests exact / micro F1:  {_fmt(summary.interests_exact_acc)} / "
        f"{_fmt(summary.interests_micro_f1)}"
    )
    print(f"  must_include exact:          {_fmt(summary.must_include_exact_acc)}")
    print(f"  exclude exact:               {_fmt(summary.exclude_exact_acc)}")
    print(f"  exclude_categories exact:    {_fmt(summary.exclude_categories_exact_acc)}")
    print(f"  soft_preferences recall:     {_fmt(summary.soft_recall)}")
    print(f"  full_match:                  {_fmt(summary.full_match_rate)}")
    print(f"  latency_p50_s:               {_fmt(summary.latency_p50_s)}")


def _cmd_qu_eval(args: argparse.Namespace) -> int:
    if _missing([args.db, args.evalset]):
        return EXIT_USAGE
    if args.split is QuSplit.TEST and not args.allow_test:
        print("Bộ test đóng băng. Thêm --allow-test khi chạy so sánh cuối.", file=sys.stderr)
        return EXIT_USAGE
    if args.limit is not None and args.limit < 1:
        print("--limit phải lớn hơn 0.", file=sys.stderr)
        return EXIT_USAGE

    items = split_items(read_gold(args.evalset))[args.split]
    if args.limit is not None:
        items = items[: args.limit]
    try:
        records = run_eval(
            items,
            load_usable_places(args.db),
            _generator(args.model, args.host),
            EVAL_REF,
            time.perf_counter,
        )
    except GenerationError as exc:
        print(f"Lỗi khi gọi model: {exc}", file=sys.stderr)
        return EXIT_GENERATION

    summary = summarize(records)
    meta: dict[str, str | int | float | bool | None] = {
        "model": args.model,
        "split": args.split.value,
        "ref_date": EVAL_REF.isoformat(),
        "temperature": TEMPERATURE,
        "seed": SEED,
        "num_predict": NUM_PREDICT,
        "num_ctx": NUM_CTX,
        "limit": "all" if args.limit is None else args.limit,
        "host": args.host,
        "evalset_sha256": file_sha256(args.evalset),
        "db_sha256": file_sha256(args.db),
        "git_commit": current_commit([args.out]),
    }
    report = {
        "meta": meta,
        "summary": summary.model_dump(mode="json"),
        "items": [record.model_dump(mode="json") for record in records],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _print_summary(summary, args.split, args.model)
    print(f"Đã ghi báo cáo vào {args.out}")
    return EXIT_OK


def _plan_generator(model: str, host: str, generation: dict[str, Any]) -> OllamaGenerator:
    """Model lập lịch: tham số sinh lấy từ configs/eval.yaml, đúng như lệnh plan."""
    return OllamaGenerator(
        model,
        host=host,
        temperature=generation["temperature"],
        seed=generation["seed"],
        num_predict=generation["num_predict"],
        num_ctx=generation["num_ctx"],
    )


def _ask_exit_code(outcome: AskOutcome) -> int:
    if outcome.kind == "clarification":
        return EXIT_CLARIFY
    if outcome.kind == "plan" and outcome.plan is not None and not outcome.plan.valid:
        return EXIT_PLAN_INVALID
    return EXIT_OK


def _ask_payload(outcome: AskOutcome) -> dict[str, object]:
    return {
        "outcome": outcome.kind,
        "query": outcome.query.model_dump(mode="json"),
        "plan": outcome.plan.model_dump(mode="json") if outcome.plan is not None else None,
    }


def _cmd_ask(args: argparse.Namespace) -> int:
    if _missing([args.db]):
        return EXIT_USAGE
    if args.landmarks < 0:
        print("--landmarks không được âm.", file=sys.stderr)
        return EXIT_USAGE
    if args.max_repairs < 0:
        print("--max-repairs không được âm.", file=sys.stderr)
        return EXIT_USAGE
    plan_model = args.plan_model or _rl_final_model(RL_CONFIG)
    if plan_model is None:
        print("Thiếu --plan-model và configs/rl.yaml không có final.ollama_model.", file=sys.stderr)
        return EXIT_USAGE
    try:
        generation = _generation_params(EVAL_CONFIG)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"Không đọc được tham số sinh: {exc}", file=sys.stderr)
        return EXIT_USAGE

    ref = args.ref or dt.date.today()
    places = load_usable_places(args.db)
    try:
        outcome = ask_query(
            args.text,
            ref,
            _generator(args.qu_model, args.host),
            _plan_generator(plan_model, args.host, generation),
            places,
            retime=not args.no_retime,
            max_repairs=args.max_repairs,
            landmarks=args.landmarks,
            fill_gaps=not args.no_fill,
        )
    except ExtractionError as exc:
        print(f"Không đọc được đầu ra của model hiểu câu: {exc}", file=sys.stderr)
        return EXIT_ASK_EXTRACTION
    except GenerationError as exc:
        print(f"Lỗi khi gọi model: {exc}", file=sys.stderr)
        return EXIT_GENERATION

    if args.json:
        print(json.dumps(_ask_payload(outcome), ensure_ascii=False, indent=2))
    else:
        print(render_ask(outcome, places))
    return _ask_exit_code(outcome)
