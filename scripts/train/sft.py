"""Train SFT QLoRA cho Qwen3.5-4B. Chạy bằng venv train (C:\\dev\\venvs\\travel), `PYTHONPATH=src`.

Lớp mỏng: đọc `configs/sft.yaml`, tokenize dataset bằng `travel_agent.training.sft_data` (cùng
chat template với lúc kiểm dataset và lúc chạy), gắn LoRA lên base 4-bit, train bằng TRL.

    python scripts/train/sft.py --config configs/sft.yaml               # run đầy đủ
    python scripts/train/sft.py --config configs/sft.yaml --smoke        # smoke test 20 step
    python scripts/train/sft.py --config configs/sft.yaml --resume       # chạy tiếp sau khi đứt

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
from importlib import metadata
from pathlib import Path
from typing import Any

from travel_agent.training.chat import ChatTokenizer
from travel_agent.training.sft_config import SftConfig, load_sft_config, repo_artifacts_dir
from travel_agent.training.sft_data import EncodedSample, encode_lines
from travel_agent.training.tokens import hf_snapshot_dir

PACKAGES = ("torch", "transformers", "peft", "trl", "bitsandbytes", "accelerate", "datasets")
ADAPTER_FILES = ("adapter_config.json", "adapter_model.safetensors")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("configs/sft.yaml"))
    parser.add_argument("--smoke", action="store_true", help="Chỉ train sft.smoke.max_steps step")
    parser.add_argument("--resume", action="store_true", help="Chạy tiếp từ checkpoint gần nhất")
    return parser.parse_args(argv)


def load_samples(config: SftConfig) -> tuple[Path, list[EncodedSample]]:
    sft = config.sft
    snapshot = hf_snapshot_dir(sft.base_model.repo, sft.base_model.revision)
    chat = ChatTokenizer.from_dir(snapshot)
    lines = sft.dataset.read_text(encoding="utf-8").splitlines()
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
    model = peft.get_peft_model(model, lora)
    model.print_trainable_parameters()

    train = sft.train
    args = trl.SFTConfig(
        output_dir=str(out),
        num_train_epochs=train.epochs,
        max_steps=max_steps,
        per_device_train_batch_size=train.per_device_batch_size,
        gradient_accumulation_steps=train.gradient_accumulation_steps,
        learning_rate=train.learning_rate,
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
        run_name=sft.run_name,
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_sft_config(args.config)
    sft = config.sft
    out = sft.run_dir / ("smoke" if args.smoke else "checkpoints")
    out.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    snapshot, samples = load_samples(config)
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
        config, snapshot, samples, out, sft.smoke.max_steps if args.smoke else -1, target
    )
    train_started = time.perf_counter()
    result = trainer.train(resume_from_checkpoint=True if args.resume else None)
    train_seconds = time.perf_counter() - train_started
    steps = int(trainer.state.global_step)
    metrics: dict[str, Any] = {
        "run_name": sft.run_name,
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
        metrics_path = out / "train_metrics.json"
    else:
        last = out / f"checkpoint-{steps}"
        if not last.is_dir():  # step cuối không rơi vào bội số của save_steps
            trainer.save_model(str(last))
        artifacts = repo_artifacts_dir(sft.run_name)
        metrics["adapter_steps"] = copy_adapters(
            out, artifacts / "adapters", sft.train.adapter_every, steps
        )
        metrics_path = artifacts / "train_metrics.json"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Xong {steps} step trong {train_seconds:.0f} giây; số đo ở {metrics_path}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
