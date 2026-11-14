"""Đếm token của một mẫu chat theo đúng tokenizer và chat template của model sẽ train.

Không có xấp xỉ: nếu không nạp được tokenizer thật thì báo `TokenizerUnavailable`, để bước kiểm
dataset nói rõ là chưa kiểm độ dài thay vì đưa ra một con số đoán.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

TokenCounter = Callable[[Sequence[Mapping[str, str]]], int]

TOKENIZER_FILE = "tokenizer.json"
CHAT_TEMPLATE_FILE = "chat_template.jinja"


class TokenizerUnavailable(RuntimeError):
    """Không nạp được tokenizer thật (thiếu thư viện hoặc thiếu file)."""


def hf_hub_cache() -> Path:
    """Thư mục cache Hugging Face theo đúng thứ tự biến môi trường của huggingface_hub."""
    if "HF_HUB_CACHE" in os.environ:
        return Path(os.environ["HF_HUB_CACHE"])
    if "HF_HOME" in os.environ:
        return Path(os.environ["HF_HOME"]) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def hf_snapshot_dir(repo: str, revision: str, hub_cache: Path | None = None) -> Path:
    """Thư mục snapshot đã tải sẵn của `repo` tại commit `revision`. Không gọi mạng."""
    org_name = repo.replace("/", "--")
    return (hub_cache or hf_hub_cache()) / f"models--{org_name}" / "snapshots" / revision


def load_chat_token_counter(model_dir: Path) -> TokenCounter:
    """Counter render cả hội thoại bằng chat template của model (thinking tắt) rồi đếm token.

    Đây là chuỗi mà bước SFT đưa vào model, nên số token so thẳng được với `max_seq`.
    """
    try:
        from jinja2.ext import loopcontrols
        from jinja2.sandbox import ImmutableSandboxedEnvironment
        from tokenizers import Tokenizer
    except ImportError as exc:  # extra `dataset` chưa cài
        raise TokenizerUnavailable(f"thiếu thư viện để đếm token: {exc.name}") from exc

    tokenizer_path = model_dir / TOKENIZER_FILE
    template_path = model_dir / CHAT_TEMPLATE_FILE
    for path in (tokenizer_path, template_path):
        if not path.is_file():
            raise TokenizerUnavailable(f"không thấy {path}")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))

    def raise_exception(message: str) -> None:
        raise ValueError(f"chat template báo lỗi: {message}")

    # Cùng thiết lập transformers dùng khi render chat template.
    env = ImmutableSandboxedEnvironment(
        trim_blocks=True, lstrip_blocks=True, extensions=[loopcontrols]
    )
    env.globals["raise_exception"] = raise_exception
    template = env.from_string(template_path.read_text(encoding="utf-8"))

    def count(messages: Sequence[Mapping[str, str]]) -> int:
        context: dict[str, Any] = {
            "messages": [dict(message) for message in messages],
            "add_generation_prompt": False,
            "enable_thinking": False,
        }
        text = template.render(**context)
        return len(tokenizer.encode(text, add_special_tokens=False).ids)

    return count
