"""RAG metrics: id-based context precision and recall, claim-based faithfulness and correctness."""

from __future__ import annotations

from collections.abc import Collection, Sequence


def context_precision(retrieved: Sequence[str], relevant: Collection[str]) -> float | None:
    """RAGAS form: mean of precision@k over the ranks that hold a relevant id; None for empty gold."""
    if not relevant:
        return None
    hits, total = 0, 0.0
    for rank, poi_id in enumerate(retrieved, start=1):
        if poi_id in relevant:
            hits += 1
            total += hits / rank
    return total / hits if hits else 0.0


def context_recall(retrieved: Sequence[str], relevant: Collection[str], k: int = 5) -> float | None:
    """Gold ids found in the top k, over min(|gold|, k) so a large gold set can still reach 1.0."""
    gold = set(relevant)
    if not gold:
        return None
    return len(set(retrieved[:k]) & gold) / min(len(gold), k)


def faithfulness(supported: Sequence[bool]) -> float | None:
    """Share of answer claims the context supports."""
    return sum(supported) / len(supported) if supported else None


def claim_f1(tp: int, fp: int, fn: int) -> float | None:
    """Claim-level F1 between answer and reference."""
    if tp + fp + fn == 0:
        return None
    return tp / (tp + 0.5 * (fp + fn))
