"""Đếm token của một mẫu chat theo đúng tokenizer và chat template của model sẽ train.

Không có xấp xỉ: nếu không nạp được tokenizer thật thì báo `TokenizerUnavailable`, để bước kiểm
dataset nói rõ là chưa kiểm độ dài thay vì đưa ra một con số đoán. Render và tokenize nằm ở
`training/chat.py`, dùng chung với bước tokenize khi train.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from travel_agent.training.chat import (
    CHAT_TEMPLATE_FILE,
    TOKENIZER_FILE,
    ChatTokenizer,
    TokenizerUnavailable,
)

__all__ = [
    "CHAT_TEMPLATE_FILE",
    "TOKENIZER_FILE",
    "TokenCounter",
    "TokenizerUnavailable",
    "hf_hub_cache",
    "hf_snapshot_dir",
    "load_chat_token_counter",
]

TokenCounter = Callable[[Sequence[Mapping[str, str]]], int]


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
    return ChatTokenizer.from_dir(model_dir).count
