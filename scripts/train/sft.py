"""Train SFT QLoRA cho Qwen3.5-4B. Chạy bằng venv train (C:\\dev\\venvs\\travel), `PYTHONPATH=src`.

Lớp mỏng: đọc `configs/sft.yaml`, tokenize dataset bằng `travel_agent.training.sft_data` (cùng
chat template với lúc kiểm dataset và lúc chạy), gắn LoRA lên base 4-bit, train bằng TRL.

    python scripts/train/sft.py --config configs/sft.yaml               # run đầy đủ
    python scripts/train/sft.py --config configs/sft.yaml --smoke        # smoke test 20 step
    python scripts/train/sft.py --config configs/sft.yaml --resume       # chạy tiếp sau khi đứt

Các cờ ghi đè dùng cho vòng best-of-N (không có cờ nào thì chạy y như cũ):

    python scripts/train/sft.py --config configs/sft.yaml --init-adapter <adapter> \\
        --dataset <jsonl> --run-dir <dir> --learning-rate 1e-4 --epochs 1 --run-name <name>

`--run-dir` đổi thư mục run thành `<run-dir>` (checkpoint ở `<run-dir>/checkpoints/`, metrics ở
`<run-dir>/train_metrics.json`) và không chép gì vào repo. `--init-adapter` nạp LoRA có sẵn và
train tiếp thay vì gắn LoRA mới. `--adapter-out <dir>` (chỉ đi cùng `--run-dir`) chép adapter của
checkpoint cuối (`<run-dir>/checkpoints/checkpoint-<steps>`) vào `<dir>`, ghi đè nếu đã có.

Checkpoint (adapter + optimizer) nằm ở `<runs_dir>/<run_name>/checkpoints/`, mỗi `save_steps` step.
Adapter của các step là bội số của `adapter_every` và step cuối được chép vào
`models/sft/<run_name>/adapters/step-<N>/` (DVC theo dõi). Số đo ghi ở
`models/sft/<run_name>/train_metrics.json`; smoke test ghi ở `<run_dir>/smoke/` và không đụng repo.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import time
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from travel_agent.training.chat import ChatTokenizer
from travel_agent.training.sft_config import SftConfig, load_sft_config, repo_artifacts_dir
from travel_agent.training.sft_data import EncodedSample, encode_lines
from travel_agent.training.tokens import hf_snapshot_dir

PACKAGES = ("torch", "transformers", "peft", "trl", "bitsandbytes", "accelerate", "datasets")
ADAPTER_FILES = ("adapter_config.json", "adapter_model.safetensors")


@dataclass(frozen=True)
class RunPlan:
    """Cấu hình thực tế của một lần train, sau khi áp cờ ghi đè lên config."""

    dataset: Path
    out: Path  # nơi checkpoint được ghi
    learning_rate: float
    epochs: int
    run_name: str  # tên W&B và run_name trong metrics; không đổi đường dẫn trong repo
    init_adapter: Path | None  # adapter có sẵn để train tiếp; None là gắn LoRA mới
    copy_to_repo: bool  # có chép adapter vào models/sft/<run_name>/ không
    metrics_path: Path
    adapter_out: Path | None = None  # chép adapter cuối vào đây; None là không chép


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("configs/sft.yaml"))
    parser.add_argument("--smoke", action="store_true", help="Chỉ train sft.smoke.max_steps step")
    parser.add_argument("--resume", action="store_true", help="Chạy tiếp từ checkpoint gần nhất")
    parser.add_argument(
        "--init-adapter",
        type=Path,
        default=None,
        help="Nạp LoRA có sẵn (thư mục adapter) và train tiếp, thay vì gắn LoRA mới",
    )
    parser.add_argument("--dataset", type=Path, default=None, help="Ghi đè sft.dataset")
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Ghi đè thư mục run; không chép adapter vào repo",
    )
    parser.add_argument(
        "--learning-rate", type=float, default=None, help="Ghi đè train.learning_rate"
    )
    parser.add_argument("--epochs", type=int, default=None, help="Ghi đè train.epochs")
    parser.add_argument("--run-name", type=str, default=None, help="Tên run trên W&B và metrics")
    parser.add_argument(
        "--adapter-out",
        type=Path,
        default=None,
        help="Chép adapter của checkpoint cuối vào thư mục này; chỉ đi cùng --run-dir",
    )
    return parser.parse_args(argv)


def resolve_run(args: argparse.Namespace, config: SftConfig) -> RunPlan:
    """Áp cờ ghi đè lên config. Không có cờ mới thì đường dẫn và tham số y như trước.

    `--run-dir` thay thư mục run (checkpoint và metrics nằm dưới đó) và tắt việc chép adapter vào
    repo. `--smoke` luôn ghi dưới `<run_dir>/smoke` và không chép vào repo.
    """
    sft = config.sft
    if args.learning_rate is not None and args.learning_rate <= 0:
        raise SystemExit("--learning-rate phải dương.")
    if args.epochs is not None and args.epochs <= 0:
        raise SystemExit("--epochs phải dương.")
    if (
        args.init_adapter is not None
        and not (args.init_adapter / "adapter_model.safetensors").exists()
    ):
        raise SystemExit(f"Không có adapter để train tiếp trong {args.init_adapter}.")
    if args.adapter_out is not None and (args.run_dir is None or args.smoke):
        raise SystemExit("--adapter-out chỉ đi cùng --run-dir, không đi cùng --smoke.")

    base = sft.run_dir if args.run_dir is None else args.run_dir
    out = base / ("smoke" if args.smoke else "checkpoints")
    if args.smoke:
        metrics_path, copy_to_repo = out / "train_metrics.json", False
    elif args.run_dir is not None:
        metrics_path, copy_to_repo = args.run_dir / "train_metrics.json", False
    else:
        metrics_path = repo_artifacts_dir(sft.run_name) / "train_metrics.json"
        copy_to_repo = True
    return RunPlan(
        dataset=sft.dataset if args.dataset is None else args.dataset,
        out=out,
        learning_rate=sft.train.learning_rate if args.learning_rate is None else args.learning_rate,
        epochs=sft.train.epochs if args.epochs is None else args.epochs,
        run_name=sft.run_name if args.run_name is None else args.run_name,
        init_adapter=args.init_adapter,
        copy_to_repo=copy_to_repo,
        metrics_path=metrics_path,
        adapter_out=args.adapter_out,
    )


def load_samples(
    config: SftConfig, dataset: Path | None = None
) -> tuple[Path, list[EncodedSample]]:
    sft = config.sft
    snapshot = hf_snapshot_dir(sft.base_model.repo, sft.base_model.revision)
    chat = ChatTokenizer.from_dir(snapshot)
    path = sft.dataset if dataset is None else dataset
    lines = path.read_text(encoding="utf-8").splitlines()
    return snapshot, encode_lines(lines, chat, sft.max_seq)


def report_target(config: SftConfig, smoke: bool) -> str:
    """Nơi gửi metrics: smoke test luôn tắt, run đầy đủ theo `sft.train.report_to`."""
    return "none" if smoke else config.sft.train.report_to


def make_interval_callback() -> Any:
    """Callback đặt lại khoảng log và save theo config khi bắt đầu train.

    Khi resume, Trainer tính các khoảng step từ args rồi nạp state cũ từ checkpoint (ghi đè).
    Nếu không đặt lại, run resume từ checkpoint cũ vẫn dùng logging_steps/save_steps cũ.
    """
    import transformers

    class ReapplyIntervals(transformers.TrainerCallback):
        def on_train_begin(self, args: Any, state: Any, control: Any, **kwargs: Any) -> Any:
            state.logging_steps = args.logging_steps
            state.save_steps = args.save_steps
            return control

    return ReapplyIntervals()


def build_trainer(
    config: SftConfig,
    snapshot: Path,
    samples: list[EncodedSample],
    out: Path,
    max_steps: int,
    report_to: str,
    *,
    learning_rate: float | None = None,
    epochs: int | None = None,
    run_name: str | None = None,
    init_adapter: Path | None = None,
) -> Any:
    import datasets
    import peft
    import torch
    import transformers
    import trl

    sft = config.sft
    quant = sft.quantization
    bnb = transformers.BitsAndBytesConfig(
        load_in_4bit=quant.load_in_4bit,
        bnb_4bit_quant_type=quant.quant_type,
        bnb_4bit_use_double_quant=quant.double_quant,
        bnb_4bit_compute_dtype=getattr(torch, quant.compute_dtype),
    )
    # AutoModelForCausalLM nạp Qwen3_5ForCausalLM: chỉ phần text, bỏ vision tower.
    model = transformers.AutoModelForCausalLM.from_pretrained(
        str(snapshot),
        quantization_config=bnb,
        dtype=torch.bfloat16,
        device_map={"": 0},
    )
    tokenizer = transformers.AutoTokenizer.from_pretrained(str(snapshot))
    model = peft.prepare_model_for_kbit_training(
        model,
        use_gradient_checkpointing=sft.train.gradient_checkpointing,
        gradient_checkpointing_kwargs={"use_reentrant": False},
    )
    lora = peft.LoraConfig(
        r=sft.lora.r,
        lora_alpha=sft.lora.alpha,
        lora_dropout=sft.lora.dropout,
        target_modules=sft.lora.target_modules,
        task_type="CAUSAL_LM",
    )
    if init_adapter is None:
        model = peft.get_peft_model(model, lora)
    else:
        # Train tiếp từ adapter có sẵn: trọng số LoRA được nạp lại và vẫn train được.
        model = peft.PeftModel.from_pretrained(model, str(init_adapter), is_trainable=True)
    model.print_trainable_parameters()

    train = sft.train
    args = trl.SFTConfig(
        output_dir=str(out),
        num_train_epochs=train.epochs if epochs is None else epochs,
        max_steps=max_steps,
        per_device_train_batch_size=train.per_device_batch_size,
        gradient_accumulation_steps=train.gradient_accumulation_steps,
        learning_rate=train.learning_rate if learning_rate is None else learning_rate,
        lr_scheduler_type=train.lr_scheduler,
        # transformers 5 bỏ warmup_ratio: warmup_steps kiểu float trong [0, 1) là tỷ lệ số step.
        warmup_steps=train.warmup_ratio,
        weight_decay=train.weight_decay,
        optim=train.optimizer,
        gradient_checkpointing=train.gradient_checkpointing,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        bf16=True,
        logging_steps=train.logging_steps,
        save_strategy="steps",
        save_steps=train.save_steps,
        save_total_limit=None,
        seed=sft.seed,
        data_seed=sft.seed,
        max_length=sft.max_seq,  # mọi mẫu đã được kiểm <= max_seq, TRL không cắt gì
        packing=False,
        report_to=report_to,
        run_name=sft.run_name if run_name is None else run_name,
    )
    # Dataset đã tokenize, có sẵn `labels` (-100 ngoài đáp án): TRL dùng nguyên như vậy.
    dataset = datasets.Dataset.from_dict(
        {
            "input_ids": [sample.input_ids for sample in samples],
            "labels": [sample.labels for sample in samples],
        }
    )
    return trl.SFTTrainer(
        model=model,
        args=args,
        train_dataset=dataset,
        processing_class=tokenizer,
        callbacks=[make_interval_callback()],
    )


def copy_adapters(checkpoints: Path, target: Path, every: int, last: int) -> list[int]:
    """Chép adapter (không kèm optimizer) vào repo cho DVC theo dõi.

    Chỉ chép checkpoint có step là bội số của `every` hoặc bằng `last` (step cuối). Checkpoint
    khác vẫn nằm trong `checkpoints` để chạy tiếp, không vào repo. Trả về các step đã chép,
    tăng dần.
    """
    steps: list[int] = []
    for checkpoint in sorted(
        checkpoints.glob("checkpoint-*"), key=lambda p: int(p.name.split("-")[1])
    ):
        step = int(checkpoint.name.split("-")[1])
        if step % every != 0 and step != last:
            continue
        destination = target / f"step-{step}"
        destination.mkdir(parents=True, exist_ok=True)
        for name in ADAPTER_FILES:
            shutil.copy2(checkpoint / name, destination / name)
        steps.append(step)
    return steps


def copy_final_adapter(checkpoint: Path, target: Path) -> None:
    """Chép adapter (không kèm optimizer) của checkpoint cuối vào `target`, ghi đè nếu đã có."""
    target.mkdir(parents=True, exist_ok=True)
    for name in ADAPTER_FILES:
        shutil.copy2(checkpoint / name, target / name)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_sft_config(args.config)
    sft = config.sft
    plan = resolve_run(args, config)
    out = plan.out
    out.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    snapshot, samples = load_samples(config, plan.dataset)
    print(
        f"Đã tokenize {len(samples)} mẫu, dài nhất {max(len(s.input_ids) for s in samples)} token."
    )

    import torch

    torch.manual_seed(sft.seed)
    torch.cuda.reset_peak_memory_stats()
    target = report_target(config, args.smoke)
    if target == "wandb":
        # Chỉ gửi metrics và config; không tải trọng số lên W&B.
        os.environ.setdefault("WANDB_PROJECT", sft.tracking.project)
        os.environ.setdefault("WANDB_LOG_MODEL", "false")
    trainer = build_trainer(
        config,
        snapshot,
        samples,
        out,
        sft.smoke.max_steps if args.smoke else -1,
        target,
        learning_rate=plan.learning_rate,
        epochs=plan.epochs,
        run_name=plan.run_name,
        init_adapter=plan.init_adapter,
    )
    train_started = time.perf_counter()
    result = trainer.train(resume_from_checkpoint=True if args.resume else None)
    train_seconds = time.perf_counter() - train_started
    steps = int(trainer.state.global_step)
    metrics: dict[str, Any] = {
        "run_name": plan.run_name,
        "smoke": args.smoke,
        "samples": len(samples),
        "trained_tokens": sum(sample.trained_tokens for sample in samples),
        "optimizer_steps": steps,
        "train_loss": float(result.training_loss),
        "train_seconds": round(train_seconds, 1),
        "seconds_per_step": round(train_seconds / max(steps, 1), 2),
        "total_seconds": round(time.perf_counter() - started, 1),
        "peak_vram_allocated_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2),
        "peak_vram_reserved_gb": round(torch.cuda.max_memory_reserved() / 2**30, 2),
        "gpu": torch.cuda.get_device_name(0),
        "python": platform.python_version(),
        "packages": {name: metadata.version(name) for name in PACKAGES},
        "log_history": trainer.state.log_history,
    }
    if args.smoke:
        trainer.save_model(str(out / "final"))
    else:
        last = out / f"checkpoint-{steps}"
        if not last.is_dir():  # step cuối không rơi vào bội số của save_steps
            trainer.save_model(str(last))
        if plan.adapter_out is not None:
            copy_final_adapter(last, plan.adapter_out)
        if plan.copy_to_repo:
            metrics["adapter_steps"] = copy_adapters(
                out, repo_artifacts_dir(sft.run_name) / "adapters", sft.train.adapter_every, steps
            )
    metrics_path = plan.metrics_path
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Xong {steps} step trong {train_seconds:.0f} giây; số đo ở {metrics_path}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
