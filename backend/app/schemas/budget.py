"""Transparent deterministic cost and budget contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.offer import HotelOffer, TransportOffer

PriceKind = Literal["QUOTED", "ESTIMATED", "UNKNOWN"]
BudgetStatus = Literal[
    "WITHIN_BUDGET",
    "WITHIN_BUDGET_EXCLUDING_UNKNOWN",
    "OVER_BUDGET",
    "UNKNOWN",
]
BudgetLabel = Literal["BUDGET", "BALANCED", "COMFORT"]


class CostItem(BaseModel):
    """One cost line. An unknown amount is never silently treated as zero."""

    code: str
    label: str
    amount_vnd: int | None = Field(default=None, ge=0)
    amount_max_vnd: int | None = Field(default=None, ge=0)
    quantity: int = Field(ge=1)
    price_unit: str
    source: str
    price_kind: PriceKind
    note: str | None = None
    poi_id: str | None = None

    @model_validator(mode="after")
    def max_not_below_min(self) -> "CostItem":
        if self.amount_max_vnd is not None and self.amount_vnd is not None:
            if self.amount_max_vnd < self.amount_vnd:
                raise ValueError("amount_max_vnd must be >= amount_vnd")
        return self


class BudgetOption(BaseModel):
    """One selected transport/hotel combination and its fully itemised cost."""

    transport_outbound: TransportOffer | None = None
    transport_return: TransportOffer | None = None
    hotel: HotelOffer | None = None
    items: list[CostItem]
    known_total_vnd: int = Field(ge=0)
    known_total_max_vnd: int = Field(ge=0)
    unknown_item_count: int = Field(ge=0)
    budget_status: BudgetStatus
    budget_remaining_vnd: int | None = None
    label: BudgetLabel | None = None
    warnings: list[str]


class BudgetResult(BaseModel):
    """Ranked, repeatable budget options; no LLM arithmetic is involved."""

    options: list[BudgetOption]
    warnings: list[str]
    shortfall_vnd: int | None = None
