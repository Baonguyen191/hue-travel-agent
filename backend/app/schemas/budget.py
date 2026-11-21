"""Transparent deterministic cost and budget contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.offer import HotelOffer, TransportOffer

PriceKind = Literal["QUOTED", "ESTIMATED", "UNKNOWN"]
BudgetStatus = Literal["WITHIN_BUDGET", "OVER_BUDGET", "UNKNOWN"]


class CostItem(BaseModel):
    """One cost line. An unknown amount is never silently treated as zero."""

    code: str
    label: str
    amount_vnd: int | None = Field(default=None, ge=0)
    quantity: int = Field(ge=1)
    price_unit: str
    source: str
    price_kind: PriceKind
    note: str | None = None


class BudgetOption(BaseModel):
    """One selected transport/hotel combination and its fully itemised cost."""

    transport_outbound: TransportOffer | None = None
    transport_return: TransportOffer | None = None
    hotel: HotelOffer | None = None
    items: list[CostItem]
    known_total_vnd: int = Field(ge=0)
    unknown_item_count: int = Field(ge=0)
    budget_status: BudgetStatus
    budget_remaining_vnd: int | None = None
    warnings: list[str]


class BudgetResult(BaseModel):
    """Ranked, repeatable budget options; no LLM arithmetic is involved."""

    options: list[BudgetOption]
    warnings: list[str]
