"""Schema của câu yêu cầu đã hiểu (ParsedQuery).

LLM chỉ trích chuỗi nguyên văn (cụm ngày, tên địa điểm, sở thích). Ngày, sở thích và liên kết
địa điểm do code tính rồi mới dựng ParsedQuery. Validator ở đây chỉ kiểm tra tổ hợp
intent / request / clarification.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from travel_agent.domain.models import Category, PlanRequest


class Intent(StrEnum):
    PLAN_NEW = "plan_new"
    MODIFY_PLAN = "modify_plan"
    PLACE_INFO = "place_info"
    OUT_OF_SCOPE = "out_of_scope"


class DurationSpec(BaseModel):
    """Số ngày đi đọc từ câu. half_day=True nghĩa là nửa ngày hoặc một buổi (num_days = 1)."""

    model_config = ConfigDict(frozen=True)

    num_days: int = Field(ge=1)
    half_day: bool = False


class PlaceMention(BaseModel):
    """Tên địa điểm người dùng nhắc tới, đã (hoặc chưa) liên kết với một place_id trong DB.

    score là độ khớp trong khoảng 0..1; place_id là None khi không liên kết được.
    """

    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1)
    place_id: str | None = None
    score: float = Field(ge=0.0, le=1.0)


class ParsedQuery(BaseModel):
    intent: Intent
    request: PlanRequest | None = None
    # Cụm ngày nguyên văn từ câu, giữ để kiểm tra; ngày cụ thể đã nằm trong request.start_date.
    date_text: str | None = None
    must_include: list[PlaceMention] = Field(default_factory=list)
    exclude: list[PlaceMention] = Field(default_factory=list)
    exclude_categories: list[Category] = Field(default_factory=list)
    # Sở thích không ánh xạ được vào 9 interest; giữ nguyên văn.
    soft_preferences: list[str] = Field(default_factory=list)
    # Tên trường được điền mặc định (ví dụ "pace", "travel_mode").
    defaulted: list[str] = Field(default_factory=list)
    clarification: str | None = None
    # Các trường đã trích, dạng JSON (ngày ISO, giờ HH:MM, số, chuỗi, danh sách). Giữ cả khi chưa
    # dựng được request (đang hỏi lại), để eval vẫn chấm được phần đã hiểu.
    partial: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _intent_matches_fields(self) -> ParsedQuery:
        if self.intent is Intent.PLAN_NEW and self.request is None and not self.clarification:
            raise ValueError("plan_new cần request hoặc clarification")
        if self.intent is Intent.OUT_OF_SCOPE and self.request is not None:
            raise ValueError("out_of_scope không được kèm request")
        return self
