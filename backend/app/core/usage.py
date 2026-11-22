"""Token counts from Ollama responses, collected per chat turn without passing a recorder around.

`record_usage()` installs a dict in a ContextVar. `asyncio.to_thread` copies the context, so a
worker thread sees the same dict object and its additions are visible to the caller.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


@dataclass
class Usage:
    """Tokens used by one component during one recording."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.calls += 1

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "calls": self.calls,
        }


_CURRENT: ContextVar[dict[str, Usage] | None] = ContextVar("travel_usage", default=None)


@contextmanager
def record_usage() -> Iterator[dict[str, Usage]]:
    """Collect usage by component until the block ends."""
    usage: dict[str, Usage] = {}
    token = _CURRENT.set(usage)
    try:
        yield usage
    finally:
        _CURRENT.reset(token)


def add_usage(component: str, payload: Mapping[str, Any]) -> None:
    """Add one Ollama response's counts; does nothing when no recording is active."""
    usage = _CURRENT.get()
    if usage is None:
        return
    usage.setdefault(component, Usage()).add(
        _count(payload.get("prompt_eval_count")), _count(payload.get("eval_count"))
    )


def _count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value
