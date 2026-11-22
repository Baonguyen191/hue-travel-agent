"""Tool spies: record which provider or retrieval tool a chat turn used."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import app.agents.search as search_module


class CallLog:
    """Tool names in call order."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def record(self, tool: str) -> None:
        self.calls.append(tool)

    def called(self) -> set[str]:
        return set(self.calls)

    def clear(self) -> None:
        self.calls.clear()


def spy_method(obj: Any, method: str, tool: str, log: CallLog) -> None:
    """Replace obj.method on this instance with a wrapper that records `tool` first."""
    original = getattr(obj, method)

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        log.record(tool)
        return original(*args, **kwargs)

    setattr(obj, method, wrapper)


@contextmanager
def spy_poi_search(log: CallLog) -> Iterator[None]:
    """Record "poi_search" for every POI search the Search Agent runs."""
    original = search_module.search_places

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        log.record("poi_search")
        return original(*args, **kwargs)

    search_module.search_places = wrapper
    try:
        yield
    finally:
        search_module.search_places = original
