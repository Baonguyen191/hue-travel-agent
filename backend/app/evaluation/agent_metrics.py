"""Multi-agent metrics: per-turn handler routing and tool-call correctness."""

from __future__ import annotations

from collections.abc import Sequence

from app.evaluation.gold import ScenarioExpect


def handler_hits(expected: Sequence[str], actual: Sequence[str]) -> tuple[int, int]:
    """(turns routed to the gold handler, gold turns); a missing actual turn is a miss."""
    hits = sum(1 for i, name in enumerate(expected) if i < len(actual) and actual[i] == name)
    return hits, len(expected)


def tools_exact(called: set[str], expect: ScenarioExpect) -> bool:
    """Every required tool was called and no forbidden tool was."""
    return set(expect.tools_called) <= called and not (set(expect.tools_not_called) & called)


def tool_counts(called: set[str], expect: ScenarioExpect) -> tuple[int, int, int]:
    """(required tools called, forbidden tools called, required tools missed)."""
    required, forbidden = set(expect.tools_called), set(expect.tools_not_called)
    return len(required & called), len(forbidden & called), len(required - called)
