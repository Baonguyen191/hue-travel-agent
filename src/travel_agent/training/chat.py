"""Render chat template của model và tokenize. Nguồn duy nhất cho chuỗi model thấy lúc train.

`training/tokens.py` (đếm token khi kiểm dataset) và `training/sft_data.py` (tokenize khi train)
cùng dùng lớp này, nên số token lúc kiểm dataset đúng bằng lúc train. Render bằng Jinja sandbox
với cùng thiết lập transformers dùng cho `apply_chat_template`; thinking luôn tắt.
Chỉ cần `tokenizers` và `jinja2` (extra `dataset`), không cần torch.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jinja2 import Template
    from tokenizers import Tokenizer

TOKENIZER_FILE = "tokenizer.json"
CHAT_TEMPLATE_FILE = "chat_template.jinja"

Messages = Sequence[Mapping[str, str]]


class TokenizerUnavailable(RuntimeError):
    """Không nạp được tokenizer thật (thiếu thư viện hoặc thiếu file)."""


class ChatTokenizer:
    def __init__(self, template: Template, tokenizer: Tokenizer) -> None:
        self._template = template
        self._tokenizer = tokenizer

    @classmethod
    def from_dir(cls, model_dir: Path) -> ChatTokenizer:
        """Nạp `tokenizer.json` và `chat_template.jinja` từ thư mục snapshot của model."""
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

        def raise_exception(message: str) -> None:
            raise ValueError(f"chat template báo lỗi: {message}")

        # Cùng thiết lập transformers dùng khi render chat template.
        env = ImmutableSandboxedEnvironment(
            trim_blocks=True, lstrip_blocks=True, extensions=[loopcontrols]
        )
        env.globals["raise_exception"] = raise_exception
        template = env.from_string(template_path.read_text(encoding="utf-8"))
        return cls(template, Tokenizer.from_file(str(tokenizer_path)))

    def render(self, messages: Messages, *, add_generation_prompt: bool) -> str:
        """Chuỗi chat của `messages`, thinking tắt.

        `add_generation_prompt=True` là prompt lúc sinh (Ollama cũng render như vậy với
        `think: false`); `False` là cả hội thoại lúc train.
        """
        context: dict[str, Any] = {
            "messages": [dict(message) for message in messages],
            "add_generation_prompt": add_generation_prompt,
            "enable_thinking": False,
        }
        return self._template.render(**context)

    def encode(self, text: str) -> list[int]:
        """Token id của `text`; token đặc biệt như `<|im_start|>` được nhận ra trong chuỗi."""
        return list(self._tokenizer.encode(text, add_special_tokens=False).ids)

    def decode(self, ids: Sequence[int]) -> str:
        return str(self._tokenizer.decode(list(ids), skip_special_tokens=False))

    def count(self, messages: Messages) -> int:
        """Số token của cả hội thoại như lúc train."""
        return len(self.encode(self.render(messages, add_generation_prompt=False)))
