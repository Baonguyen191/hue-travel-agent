"""Model cho việc duyệt tay địa điểm.

Dữ liệu OSM gốc không bị sửa. Mọi chỉnh sửa của người duyệt lưu riêng dưới dạng override,
để biết trường nào đến từ OSM và trường nào do người sửa (kèm nguồn kiểm chứng).
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from travel_agent.domain.models import Category, Place
from travel_agent.domain.opening_hours import parse_opening_hours


class ReviewStatus(StrEnum):
    PENDING = "pending"  # chưa duyệt (không có bản ghi review)
    APPROVED = "approved"  # dùng được cho lập lịch
    REJECTED = "rejected"  # loại: trùng, đóng cửa, không phải điểm du lịch...
    NEEDS_FIX = "needs_fix"  # cần kiểm tra thêm trước khi dùng


class ReviewInput(BaseModel):
    place_id: str = Field(min_length=1)
    status: ReviewStatus
    name_override: str | None = None
    category_override: Category | None = None
    opening_hours_override: str | None = None
    evidence: str | None = None
    note: str | None = None

    @field_validator("name_override", "opening_hours_override", "evidence", "note", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def _check_rules(self) -> ReviewInput:
        if self.status is ReviewStatus.PENDING:
            raise ValueError("Không lưu trạng thái pending; hãy xóa đánh giá thay vào đó")
        if self.opening_hours_override is not None:
            if parse_opening_hours(self.opening_hours_override) is None:
                raise ValueError(
                    "opening_hours_override không đúng cú pháp được hỗ trợ "
                    "(ví dụ: Mo-Su 07:00-17:30 hoặc Mo-Fr 08:00-11:30,13:30-17:00)"
                )
            if self.evidence is None:
                raise ValueError("Sửa giờ mở cửa phải kèm nguồn kiểm chứng (evidence)")
        return self


class Review(ReviewInput):
    reviewed_at: dt.datetime


class ReviewedPlace(BaseModel):
    place: Place
    status: ReviewStatus
    review: Review | None = None

    def effective_place(self) -> Place:
        """Place sau khi áp override của người duyệt. `self.place` giữ nguyên dữ liệu OSM."""
        if self.review is None:
            return self.place
        updates: dict[str, Any] = {}
        if self.review.name_override is not None:
            updates["name"] = self.review.name_override
        if self.review.category_override is not None:
            updates["category"] = self.review.category_override
        if self.review.opening_hours_override is not None:
            updates["opening_hours_raw"] = self.review.opening_hours_override
        return self.place.model_copy(update=updates)
