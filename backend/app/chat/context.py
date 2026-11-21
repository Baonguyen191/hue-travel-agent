"""Chat context stored as JSON on the conversation.

`draft` is the plan being collected (only values the user stated or confirmed), `request`
is the latest plan request, `thread_id` the current plan thread, `pending` a confirmation
waiting for an answer, and `keys` the booking idempotency keys by quote hash.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ChatContext:
    """Everything the chat remembers between two messages of one conversation."""

    draft: dict[str, Any] = field(default_factory=dict)
    request: dict[str, Any] | None = None
    thread_id: str | None = None
    pending: dict[str, Any] | None = None
    keys: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_json(cls, raw: str | None) -> ChatContext:
        """Read a stored context; an empty or missing value is a new context."""
        if not raw:
            return cls()
        return cls(**json.loads(raw))

    def to_json(self) -> str:
        """Serialize for the conversation row."""
        return json.dumps(asdict(self), ensure_ascii=False)
