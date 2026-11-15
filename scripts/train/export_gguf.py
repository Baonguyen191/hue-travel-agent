"""Export một checkpoint SFT thành model Ollama. Chạy bằng venv train, `PYTHONPATH=src`.

    python scripts/train/export_gguf.py --config configs/sft.yaml --checkpoint 250
    python scripts/train/export_gguf.py --config configs/sft.yaml --record     # stage export_sft

Các bước: merge adapter vào base bf16 trên CPU, `convert_hf_to_gguf.py` ra GGUF bf16,
`llama-quantize` ra Q4_K_M, chép Modelfile của model mẫu (`qwen3.5:4b`) và chỉ thay `FROM` của
trọng số text, rồi `ollama create`. File nặng nằm ở `<run_dir>/export/step-<N>/`.
`--record` bắt buộc `export.checkpoint` trong config, đặt tên model theo `export.ollama_model` và
ghi `models/sft/<run_name>/export.json`; không có cờ này thì tên model có hậu tố `-step-<N>`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from travel_agent.training.chat import CHAT_TEMPLATE_FILE, TOKENIZER_FILE
from travel_agent.training.export import (
    convert_command,
    from_lines,
    quantize_command,
    swap_model_from,
)
from travel_agent.training.model_card import sha256_file
from travel_agent.training.sft_config import SftConfig, load_sft_config, repo_artifacts_dir
from travel_agent.training.tokens import hf_snapshot_dir

TEXT_ARCHITECTURE = "qwen35"  # general.architecture của GGUF trọng số text (projector là "clip")
TOKENIZER_EXTRAS = ("tokenizer_config.json", "vocab.json", "merges.txt")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("configs/sft.yaml"))
    parser.add_argument(
        "--checkpoint", type=int, help="Step; mặc định export.checkpoint hoặc step cuối"
    )
    parser.add_argument("--record", action="store_true", help="Ghi export.json cho stage DVC")
    parser.add_argument("--skip-ollama", action="store_true", help="Dừng sau khi có GGUF")
    return parser.parse_args(argv)


def run(command: list[str]) -> str:
    print("$", " ".join(command), flush=True)
    return subprocess.run(
        command, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def pick_step(config: SftConfig, requested: int | None) -> int:
    adapters = repo_artifacts_dir(config.sft.run_name) / "adapters"
    available = sorted(int(path.name.split("-")[1]) for path in adapters.glob("step-*"))
    if not available:
        raise SystemExit(f"Không có adapter nào trong {adapters}. Chạy scripts/train/sft.py trước.")
    step = requested or config.export.checkpoint or available[-1]
    if step not in available:
        raise SystemExit(f"Không có adapter step {step}; có {available}.")
    return step


def merge(snapshot: Path, adapter: Path, out: Path) -> None:
    import peft
    import torch
    import transformers

    # Merge trên CPU ở bf16: GPU 8 GB không chứa nổi base bf16 cộng LoRA.
    base = transformers.AutoModelForCausalLM.from_pretrained(
        str(snapshot), dtype=torch.bfloat16, device_map={"": "cpu"}
    )
    merged = peft.PeftModel.from_pretrained(base, str(adapter)).merge_and_unload()
    merged.save_pretrained(str(out), safe_serialization=True)
    for name in (TOKENIZER_FILE, CHAT_TEMPLATE_FILE, *TOKENIZER_EXTRAS):
        shutil.copy2(snapshot / name, out / name)


def text_weights(modelfile: str) -> str:
    """Dòng FROM nào của model mẫu là trọng số text: đọc general.architecture trong GGUF."""
    from gguf import GGUFReader

    found = []
    for path in from_lines(modelfile):
        field = GGUFReader(path).fields.get("general.architecture")
        if field is not None and bytes(field.parts[-1]).decode("utf-8") == TEXT_ARCHITECTURE:
            found.append(path)
    if len(found) != 1:
        raise SystemExit(f"Cần đúng một FROM có kiến trúc {TEXT_ARCHITECTURE}, thấy {found}.")
    return found[0]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_sft_config(args.config)
    if args.record and config.export.checkpoint is None:
        raise SystemExit(
            "--record cần export.checkpoint trong config: chọn checkpoint thắng trước "
            "(plan 4 Task 6 Step 3)."
        )
    sft, export = config.sft, config.export
    step = pick_step(config, None if args.record else args.checkpoint)
    snapshot = hf_snapshot_dir(sft.base_model.repo, sft.base_model.revision)
    adapter = repo_artifacts_dir(sft.run_name) / "adapters" / f"step-{step}"
    work = sft.run_dir / "export" / f"step-{step}"
    merged_dir, bf16_gguf = work / "merged", work / "model-bf16.gguf"
    final_gguf = work / f"model-{export.quantization}.gguf"
    work.mkdir(parents=True, exist_ok=True)

    merge(snapshot, adapter, merged_dir)
    run(convert_command(Path(sys.executable), export.llama_cpp_dir, merged_dir, bf16_gguf))
    run(quantize_command(export.llama_cpp_dir, bf16_gguf, final_gguf, export.quantization))
    bf16_gguf.unlink()  # chỉ giữ bản đã quantize
    record: dict[str, Any] = {
        "checkpoint": step,
        "adapter_sha256": sha256_file(adapter / "adapter_model.safetensors"),
        "quantization": export.quantization,
        "gguf": str(final_gguf),
        "gguf_sha256": sha256_file(final_gguf),
        "llama_cpp_commit": run(
            ["git", "-C", str(export.llama_cpp_dir), "rev-parse", "HEAD"]
        ).strip(),
        "template_model": export.template_model,
    }
    if not args.skip_ollama:
        name = export.ollama_model if args.record else f"{export.ollama_model}-step-{step}"
        template = run(["ollama", "show", "--modelfile", export.template_model])
        modelfile = swap_model_from(template, text_weights(template), final_gguf)
        modelfile_path = work / "Modelfile"
        modelfile_path.write_text(modelfile, encoding="utf-8")
        run(["ollama", "create", name, "-f", str(modelfile_path)])
        record |= {"ollama_model": name, "modelfile_sha256": sha256_file(modelfile_path)}
    if args.record:
        path = repo_artifacts_dir(sft.run_name) / "export.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
